"""Mini-CRM: customers, segments, purchase history, CSV export, bulk import."""
import csv, io, re
from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from pymongo import UpdateOne

from models import CustomerCreate, CustomerUpdate, ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER, gen_id, now_iso
from auth import get_current_user, require_roles, audit

router = APIRouter(prefix="/customers", tags=["customers"])


TRUTHY = {"true", "1", "yes", "y", "t", "sub", "subscribed", "on"}
FALSY = {"false", "0", "no", "n", "f", "unsub", "unsubscribed", "off", ""}


def _to_bool(v, default=None):
    if v is None: return default
    s = str(v).strip().lower()
    if s in TRUTHY: return True
    if s in FALSY: return False
    return default


def _to_float(v):
    if v is None or str(v).strip() == "": return 0.0
    try: return float(str(v).replace(",", "").replace("₹", "").strip())
    except Exception: return 0.0


def _to_int(v):
    return int(_to_float(v))


def _split_tags(v):
    if not v: return []
    return [t.strip() for t in str(v).replace(";", ",").split(",") if t.strip()]


@router.get("")
async def list_customers(
    request: Request,
    q: Optional[str] = None,
    tag: Optional[str] = None,
    consent: Optional[str] = None,     # "email" | "sms" | "whatsapp"
    channel: Optional[str] = None,     # "online (shopify)" | "store"
    skip: int = 0,
    limit: int = 50,
    user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER)),
):
    db = request.app.state.db
    # Only the owner can browse the full customer list. Store staff can only
    # search (POS lookup), a few results at a time, so nobody can page through
    # and copy the whole customer database.
    if user["role"] != ROLE_OWNER:
        if not q or len(q.strip()) < 3:
            raise HTTPException(400, "Type at least 3 characters of a name, phone or email to search.")
        skip, limit = 0, min(int(limit), 10)
    limit = max(1, min(int(limit), 500))
    query: dict = {}
    if q:
        rq = re.escape(q.strip()[:64])
        query["$or"] = [
            {"name": {"$regex": rq, "$options": "i"}},
            {"phone": {"$regex": rq, "$options": "i"}},
            {"email": {"$regex": rq, "$options": "i"}},
        ]
    if tag: query["tags"] = tag
    if consent in ("email", "sms", "whatsapp"):
        query[f"consent_{consent}"] = True
    if channel: query["channel"] = channel
    total = await db.customers.count_documents(query)
    docs = await db.customers.find(query, {"_id": 0}).sort("last_seen", -1).skip(int(skip)).limit(int(limit)).to_list(int(limit))
    return {"total": total, "skip": int(skip), "limit": int(limit), "rows": docs}


@router.post("/import-csv")
async def import_csv(
    request: Request,
    file: UploadFile = File(...),
    actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER)),
):
    """Bulk-import customers from a Shopify (or similar) CSV.
    Expected columns (exact order recommended, extras ignored):
      name, email, phone, total_spent, order_count,
      consent_email, consent_sms, consent_whatsapp,
      city, state, country, tags, channel
    Upsert dedupe: email first, then phone.
    """
    db = request.app.state.db
    content = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    now = now_iso()
    created, updated, skipped, errors = 0, 0, 0, []
    batch: List[UpdateOne] = []
    seen_keys: set = set()

    async def flush(batch_ops):
        nonlocal created, updated
        if not batch_ops: return
        try:
            res = await db.customers.bulk_write(batch_ops, ordered=False)
            created += (res.upserted_count or 0)
            updated += (res.modified_count or 0)
        except Exception as ex:
            errors.append({"batch": "bulk_write", "error": str(ex)[:200]})

    for i, row in enumerate(reader, start=2):
        try:
            email = (row.get("email") or "").strip().lower() or None
            phone = (row.get("phone") or "").strip() or None
            name = (row.get("name") or "").strip()
            if not (email or phone):
                skipped += 1; continue
            key = ("e:" + email) if email else ("p:" + phone)
            if key in seen_keys:
                skipped += 1; continue
            seen_keys.add(key)

            match = {"email": email} if email else {"phone": phone}
            fields = {
                "name": name or (email or phone),
                "email": email, "phone": phone,
                "total_spend": _to_float(row.get("total_spent")),
                "order_count": _to_int(row.get("order_count")),
                "avg_order_value": 0.0,
                "consent_email": _to_bool(row.get("consent_email"), False),
                "consent_sms": _to_bool(row.get("consent_sms"), False),
                "consent_whatsapp": _to_bool(row.get("consent_whatsapp"), False),
                "city": (row.get("city") or "").strip() or None,
                "state": (row.get("state") or "").strip() or None,
                "country": (row.get("country") or "").strip() or None,
                "tags": _split_tags(row.get("tags")),
                "channel": (row.get("channel") or "online (shopify)").strip() or "online (shopify)",
                "imported_from": "shopify_csv",
                "updated_at": now,
            }
            oc = fields["order_count"] or 0
            fields["avg_order_value"] = round(fields["total_spend"] / oc, 2) if oc > 0 else 0.0

            op = UpdateOne(
                match,
                {
                    "$set": fields,
                    "$setOnInsert": {
                        "id": gen_id(),
                        "first_seen": None,
                        "last_seen": None,
                        "created_at": now,
                    },
                },
                upsert=True,
            )
            batch.append(op)
            if len(batch) >= 500:
                await flush(batch); batch = []
        except Exception as ex:
            errors.append({"row": i, "error": str(ex)[:200]})

    await flush(batch)
    total_now = await db.customers.count_documents({})
    await audit(db, actor, "customer.import_csv", "customer", None,
                {"created": created, "updated": updated, "skipped": skipped,
                 "errors": len(errors), "total_after": total_now})
    return {"created": created, "updated": updated, "skipped": skipped,
            "errors": errors[:20], "total_after": total_now}


@router.get("/segments")
async def segments(request: Request,
                   min_spend: Optional[float] = 0,
                   inactive_days: Optional[int] = None,
                   category: Optional[str] = None,
                   user: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    query: dict = {}
    if min_spend: query["total_spend"] = {"$gte": float(min_spend)}
    if inactive_days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(inactive_days))).isoformat()
        query["last_seen"] = {"$lte": cutoff}
    docs = await db.customers.find(query, {"_id": 0}).to_list(2000)

    if category:
        cust_ids: set = set()
        prods = await db.products.find({"category": category}, {"id": 1}).to_list(5000)
        pids = [p["id"] for p in prods]
        sales = await db.sales.find({"items.product_id": {"$in": pids}}, {"customer_id": 1}).to_list(20000)
        for s in sales:
            if s.get("customer_id"): cust_ids.add(s["customer_id"])
        docs = [d for d in docs if d["id"] in cust_ids]
    return docs


@router.get("/export/csv")
async def export_csv(request: Request,
                     min_spend: Optional[float] = 0,
                     inactive_days: Optional[int] = None,
                     tag: Optional[str] = None,
                     user: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    query: dict = {}
    if min_spend: query["total_spend"] = {"$gte": float(min_spend)}
    if inactive_days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(inactive_days))).isoformat()
        query["last_seen"] = {"$lte": cutoff}
    if tag: query["tags"] = tag
    docs = await db.customers.find(query, {"_id": 0}).to_list(20000)
    output = io.StringIO()
    fieldnames = ["name", "phone", "email", "channel", "first_seen", "last_seen",
                  "total_spend", "order_count", "avg_order_value", "tags"]
    w = csv.DictWriter(output, fieldnames=fieldnames)
    w.writeheader()
    for d in docs:
        row = {k: d.get(k, "") for k in fieldnames}
        row["tags"] = ",".join(d.get("tags", []) or [])
        w.writerow(row)
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=customers.csv"})


@router.get("/{customer_id}")
async def get_customer(customer_id: str, request: Request, user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER))):
    db = request.app.state.db
    c = await db.customers.find_one({"id": customer_id}, {"_id": 0})
    if not c: raise HTTPException(404, "Customer not found")
    history = await db.sales.find({"customer_id": customer_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"customer": c, "history": history}


@router.post("")
async def create_customer(body: CustomerCreate, request: Request,
                          actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER))):
    db = request.app.state.db
    now = now_iso()
    query = []
    if body.phone: query.append({"phone": body.phone})
    if body.email: query.append({"email": body.email})
    if query:
        existing = await db.customers.find_one({"$or": query}, {"_id": 0})
        if existing: return existing
    doc = {
        **body.model_dump(),
        "id": gen_id(),
        "first_seen": now, "last_seen": now,
        "total_spend": 0.0, "order_count": 0, "avg_order_value": 0.0,
    }
    await db.customers.insert_one(doc)
    await audit(db, actor, "customer.create", "customer", doc["id"], {"name": doc["name"]})
    doc.pop("_id", None)
    return doc


@router.patch("/{customer_id}")
async def update_customer(customer_id: str, body: CustomerUpdate, request: Request,
                          actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER))):
    db = request.app.state.db
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not updates: raise HTTPException(400, "Nothing to update")
    res = await db.customers.update_one({"id": customer_id}, {"$set": updates})
    if res.matched_count == 0: raise HTTPException(404, "Customer not found")
    await audit(db, actor, "customer.update", "customer", customer_id, updates)
    doc = await db.customers.find_one({"id": customer_id}, {"_id": 0})
    return doc
