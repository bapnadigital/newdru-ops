"""Warranty registration + claims + activity log.

Public endpoints (no auth, rate-limited by IP-lockout on failed lookups):
  GET  /api/public/warranty/product-lookup?code=SKU
  POST /api/public/warranty/register
  GET  /api/public/warranty/status/{warranty_id}
  POST /api/public/warranty/claim/{warranty_id}

Admin endpoints (owner + store_manager for view; owner-only for status change):
  GET   /api/warranty/registrations
  GET   /api/warranty/registrations/{id}
  PATCH /api/warranty/registrations/{id}
  GET   /api/warranty/registrations/{id}/certificate.pdf
  GET   /api/warranty/activity                  (User Activities feed)
  GET   /api/warranty/export.csv
  GET   /api/warranty/analytics
  GET   /api/warranty/claims
  PATCH /api/warranty/claims/{id}
"""
from __future__ import annotations
import re
import csv
import io
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Literal
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, EmailStr, Field, field_validator

from models import gen_id, now_iso, ROLE_OWNER, ROLE_STORE_MANAGER, _blank_to_none
from auth import get_current_user, require_roles, audit, log_export
from security import safe_csv_writer, SafeDictWriter
from services.geoip import lookup as geoip_lookup
from security import client_ip, rate_limit
from services.warranty_pdf import render_certificate

router = APIRouter(tags=["warranty"])


# =============== Helpers ==================================================
def _wid() -> str:
    """8-char human-friendly warranty ID (upper alphanumerics, no confusing chars).
    Uses secrets for cryptographically-strong randomness."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _shorten(s: Optional[str], n: int = 60) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


PURCHASE_SOURCES = ["amazon", "flipkart", "newdru.com", "offline_store", "other"]

# Public-form limits: stop junk/huge uploads filling the database.
MAX_UPLOAD_CHARS = 4_500_000          # ~3 MB file as a base64 data URI
ALLOWED_UPLOAD_PREFIXES = ("data:image/png", "data:image/jpeg", "data:image/jpg",
                           "data:image/webp", "data:image/heic", "data:application/pdf", "https://")


def _safe_upload(v):
    """Only images/PDF data-URIs or https links; blocks javascript: and other tricks."""
    if v is None:
        return v
    v = str(v).strip()
    if len(v) > MAX_UPLOAD_CHARS:
        raise ValueError("File is too large (max 3 MB).")
    if not v.lower().startswith(ALLOWED_UPLOAD_PREFIXES):
        raise ValueError("Upload must be a photo or PDF.")
    return v


async def _public_limit(request: Request, action: str, limit: int, window: int):
    await rate_limit(request.app.state.db, f"warranty-{action}:{client_ip(request)}", limit, window)


# =============== Models ===================================================
class WarrantyRegisterIn(BaseModel):
    product_code: str = Field(max_length=64)  # SKU / barcode / FNSKU
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=6, max_length=20)
    purchase_date: str = Field(max_length=10)  # ISO date (YYYY-MM-DD)
    purchase_source: str = Field(max_length=32)  # one of PURCHASE_SOURCES
    retailer_name: Optional[str] = Field(default=None, max_length=120)
    invoice_url: Optional[str] = None   # data-URI or link to the uploaded invoice
    notes: Optional[str] = Field(default=None, max_length=1000)

    _norm = field_validator("retailer_name", "invoice_url", "notes", mode="before")(
        lambda cls, v: _blank_to_none(v)
    )
    _upload = field_validator("invoice_url", mode="after")(lambda cls, v: _safe_upload(v))


class WarrantyRegistrationUpdate(BaseModel):
    status: Optional[Literal["active", "approved", "rejected", "expired"]] = None
    admin_notes: Optional[str] = None


class ClaimIn(BaseModel):
    issue_type: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=2000)
    images: List[str] = Field(default_factory=list, max_length=4)

    _imgs = field_validator("images", mode="after")(lambda cls, v: [_safe_upload(x) for x in v])


class ClaimUpdate(BaseModel):
    status: Optional[Literal["submitted", "under_review", "approved", "rejected", "resolved"]] = None
    resolution: Optional[str] = None


# =============== Public endpoints =========================================
public = APIRouter(prefix="/public/warranty", tags=["warranty-public"])


@public.get("/product-lookup")
async def public_product_lookup(request: Request, code: str):
    """Given SKU/barcode/FNSKU return {sku, name, image, warranty_months}."""
    await _public_limit(request, "lookup", 60, 600)
    db = request.app.state.db
    code = (code or "")[:64]
    code = (code or "").strip()
    if not code:
        raise HTTPException(400, "Missing code")
    q = {
        "$or": [
            {"sku": code},
            {"barcode": code},
            {"amazon_fnsku": code},
            {"shipping_mark": code},
        ]
    }
    p = await db.products.find_one(q, {"_id": 0})
    if not p:
        raise HTTPException(404, "Product not found. Please check the SKU on your invoice.")
    return {
        "sku": p["sku"],
        "name": p["name"],
        "image": (p.get("images") or [None])[0],
        "warranty_months": int(p.get("warranty_months") or 6),
    }


@public.post("/register")
async def public_register(body: WarrantyRegisterIn, request: Request):
    await _public_limit(request, "register", 10, 3600)
    db = request.app.state.db

    # 1) Resolve product
    p = await db.products.find_one(
        {"$or": [{"sku": body.product_code}, {"barcode": body.product_code},
                 {"amazon_fnsku": body.product_code}]},
        {"_id": 0},
    )
    if not p:
        raise HTTPException(404, "Product not found. Check the SKU on your invoice.")

    if body.purchase_source not in PURCHASE_SOURCES:
        raise HTTPException(400, f"purchase_source must be one of {PURCHASE_SOURCES}")

    # 2) Duplicate guard — same (SKU + email + invoice month) can only register once
    try:
        pd = datetime.fromisoformat(body.purchase_date)
    except Exception:
        raise HTTPException(400, "purchase_date must be YYYY-MM-DD")
    if pd > datetime.now():
        raise HTTPException(400, "Purchase date cannot be in the future.")
    if (datetime.now() - pd).days > 400:
        raise HTTPException(400, "Purchase must be within the last 400 days to be eligible.")

    dupe = await db.warranty_registrations.find_one({
        "product_id": p["id"],
        "email": body.email.lower(),
    })
    if dupe:
        raise HTTPException(400,
            f"A warranty is already registered for this SKU + email (ID #{dupe.get('warranty_id')}).")

    # 3) Enrich with IP + geo
    ip = client_ip(request)
    ua = request.headers.get("user-agent", "")
    geo = await geoip_lookup(ip)

    # 4) Warranty term (SKU override else default 6 months)
    months = int(p.get("warranty_months") or 6)
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=months * 30)

    # 5) Upsert into mini-CRM
    cust = await db.customers.find_one({"email": body.email.lower()})
    if not cust:
        cust_id = gen_id()
        await db.customers.insert_one({
            "id": cust_id, "name": body.name, "email": body.email.lower(),
            "phone": body.phone, "channel": "warranty",
            "consent_email": True, "consent_sms": False, "consent_whatsapp": False,
            "tags": ["warranty"], "total_spend": 0.0, "order_count": 0,
            "first_seen": start.isoformat(), "last_seen": start.isoformat(),
        })
    else:
        cust_id = cust["id"]
        await db.customers.update_one(
            {"id": cust_id},
            {"$set": {"last_seen": start.isoformat()},
             "$addToSet": {"tags": "warranty"}},
        )

    # 6) Insert warranty registration + activity events
    wid = _wid()
    while await db.warranty_registrations.find_one({"warranty_id": wid}):
        wid = _wid()

    reg = {
        "id": gen_id(),
        "warranty_id": wid,
        "product_id": p["id"],
        "sku": p["sku"],
        "product_name": p["name"],
        "customer_id": cust_id,
        "name": body.name,
        "email": body.email.lower(),
        "phone": body.phone,
        "purchase_date": pd.isoformat(),
        "purchase_source": body.purchase_source,
        "retailer_name": body.retailer_name,
        "invoice_url": body.invoice_url,
        "notes": body.notes,
        "warranty_months": months,
        "warranty_start": start.isoformat(),
        "warranty_end": end.isoformat(),
        "status": "active",
        "ip": ip, "user_agent": ua,
        "geo": geo,
        "created_at": start.isoformat(), "updated_at": start.isoformat(),
    }
    await db.warranty_registrations.insert_one(reg)

    # Activity: Purchased + Warranty Registered
    tracking_id = f"{ip}_{int(start.timestamp())}"
    events = [
        {"id": gen_id(), "warranty_id": wid, "product_id": p["id"], "sku": p["sku"],
         "product_name": p["name"], "event": "purchased",
         "tracking_id": tracking_id, "ip": ip, "user_agent": ua, "geo": geo,
         "created_at": (start - timedelta(seconds=1)).isoformat()},
        {"id": gen_id(), "warranty_id": wid, "product_id": p["id"], "sku": p["sku"],
         "product_name": p["name"], "event": "warranty_registered",
         "tracking_id": tracking_id, "ip": ip, "user_agent": ua, "geo": geo,
         "created_at": start.isoformat()},
    ]
    await db.warranty_activity.insert_many(events)

    await audit(db, None, "warranty.register", "warranty", reg["id"],
                {"warranty_id": wid, "sku": p["sku"], "email": body.email.lower()})

    reg.pop("_id", None)
    return {
        "warranty_id": wid,
        "product_name": p["name"],
        "warranty_end": end.isoformat(),
        "warranty_months": months,
        "certificate_url": f"/api/warranty/public/certificate/{wid}.pdf",
    }


@public.get("/status/{warranty_id}")
async def public_status(warranty_id: str, request: Request):
    await _public_limit(request, "status", 30, 600)
    db = request.app.state.db
    warranty_id = warranty_id[:16]
    r = await db.warranty_registrations.find_one({"warranty_id": warranty_id.upper()}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Warranty not found")
    # Recompute days_left
    try:
        end = datetime.fromisoformat(r["warranty_end"].replace("Z", "+00:00"))
        days_left = max(0, (end - datetime.now(timezone.utc)).days)
    except Exception:
        days_left = 0
    return {
        "warranty_id": r["warranty_id"],
        "product_name": r["product_name"],
        "sku": r["sku"],
        "name": (r.get("name") or "").split(" ")[0],  # first name only on the public page
        "warranty_start": r["warranty_start"],
        "warranty_end": r["warranty_end"],
        "days_left": days_left,
        "status": r["status"],
    }


@public.post("/claim/{warranty_id}")
async def public_claim(warranty_id: str, body: ClaimIn, request: Request):
    await _public_limit(request, "claim", 5, 3600)
    db = request.app.state.db
    warranty_id = warranty_id[:16]
    r = await db.warranty_registrations.find_one({"warranty_id": warranty_id.upper()})
    if not r:
        raise HTTPException(404, "Warranty not found")
    if r["status"] not in ("active", "approved"):
        raise HTTPException(400, f"Cannot claim on a {r['status']} warranty")
    # Check not expired
    try:
        end = datetime.fromisoformat(r["warranty_end"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > end:
            raise HTTPException(400, "Warranty has expired")
    except HTTPException:
        raise
    except Exception:
        pass

    now = now_iso()
    ip = client_ip(request)
    claim = {
        "id": gen_id(),
        "warranty_id": r["warranty_id"],
        "registration_id": r["id"],
        "product_id": r["product_id"],
        "sku": r["sku"],
        "customer_id": r["customer_id"],
        "name": r["name"],
        "email": r["email"],
        "phone": r["phone"],
        "issue_type": body.issue_type,
        "description": body.description,
        "images": body.images,
        "status": "submitted",
        "resolution": None,
        "ip": ip,
        "created_at": now, "updated_at": now,
    }
    await db.warranty_claims.insert_one(claim)
    await db.warranty_activity.insert_one({
        "id": gen_id(), "warranty_id": r["warranty_id"],
        "product_id": r["product_id"], "sku": r["sku"],
        "product_name": r["product_name"], "event": "claim_submitted",
        "tracking_id": f"{ip}_{int(datetime.now().timestamp())}",
        "ip": ip, "geo": await geoip_lookup(ip),
        "user_agent": request.headers.get("user-agent", ""),
        "created_at": now,
    })
    claim.pop("_id", None)
    return {"claim_id": claim["id"], "status": "submitted"}


router.include_router(public)


# =============== Admin endpoints ==========================================
admin = APIRouter(prefix="/warranty", tags=["warranty-admin"])


# Public certificate PDF (no auth so email links work)
@admin.get("/public/certificate/{warranty_id}.pdf")
async def public_certificate(warranty_id: str, request: Request):
    await _public_limit(request, "certificate", 30, 600)
    db = request.app.state.db
    warranty_id = warranty_id[:16]
    r = await db.warranty_registrations.find_one({"warranty_id": warranty_id.upper()}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Warranty not found")
    p = await db.products.find_one({"id": r["product_id"]}, {"_id": 0}) or {"sku": r.get("sku"), "name": r.get("product_name")}
    pdf = render_certificate(r, p)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="warranty-{warranty_id}.pdf"'})


@admin.get("/registrations")
async def list_registrations(
    request: Request,
    q: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    skip: int = 0, limit: int = 50,
    user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER)),
):
    db = request.app.state.db
    query: dict = {}
    if status: query["status"] = status
    if source: query["purchase_source"] = source
    if q:
        query["$or"] = [
            {"warranty_id": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"sku": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"product_name": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"name": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"email": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"phone": {"$regex": re.escape(q[:64]), "$options": "i"}},
        ]
    total = await db.warranty_registrations.count_documents(query)
    rows = await db.warranty_registrations.find(query, {"_id": 0}) \
        .sort("created_at", -1).skip(int(skip)).limit(int(limit)).to_list(int(limit))
    now = datetime.now(timezone.utc)
    for r in rows:
        try:
            end = datetime.fromisoformat(r["warranty_end"].replace("Z", "+00:00"))
            r["days_left"] = max(0, (end - now).days)
        except Exception:
            r["days_left"] = 0
    return {"total": total, "skip": int(skip), "limit": int(limit), "rows": rows}


@admin.get("/registrations/{rid}")
async def get_registration(rid: str, request: Request,
                            user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER))):
    db = request.app.state.db
    r = await db.warranty_registrations.find_one(
        {"$or": [{"id": rid}, {"warranty_id": rid.upper()}]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Not found")
    claims = await db.warranty_claims.find({"warranty_id": r["warranty_id"]}, {"_id": 0}) \
        .sort("created_at", -1).to_list(50)
    activity = await db.warranty_activity.find({"warranty_id": r["warranty_id"]}, {"_id": 0}) \
        .sort("created_at", -1).to_list(50)
    product = await db.products.find_one({"id": r["product_id"]}, {"_id": 0})
    now = datetime.now(timezone.utc)
    try:
        end = datetime.fromisoformat(r["warranty_end"].replace("Z", "+00:00"))
        r["days_left"] = max(0, (end - now).days)
    except Exception:
        r["days_left"] = 0
    return {"registration": r, "claims": claims, "activity": activity, "product": product}


@admin.patch("/registrations/{rid}")
async def update_registration(rid: str, body: WarrantyRegistrationUpdate, request: Request,
                               actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "Nothing to update")
    updates["updated_at"] = now_iso()
    r = await db.warranty_registrations.update_one(
        {"$or": [{"id": rid}, {"warranty_id": rid.upper()}]}, {"$set": updates})
    if r.matched_count == 0:
        raise HTTPException(404, "Not found")
    await audit(db, actor, "warranty.update", "warranty", rid, updates)
    return {"ok": True}


@admin.get("/activity")
async def activity_feed(
    request: Request,
    q: Optional[str] = None,
    event: Optional[str] = None,
    skip: int = 0, limit: int = 50,
    user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER)),
):
    """Dyrect-style User Activities feed."""
    db = request.app.state.db
    query: dict = {}
    if event: query["event"] = event
    if q:
        query["$or"] = [
            {"sku": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"product_name": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"warranty_id": {"$regex": re.escape(q[:64]), "$options": "i"}},
        ]
    total = await db.warranty_activity.count_documents(query)
    rows = await db.warranty_activity.find(query, {"_id": 0}) \
        .sort("created_at", -1).skip(int(skip)).limit(int(limit)).to_list(int(limit))
    return {"total": total, "rows": rows}


@admin.get("/export.csv", dependencies=[Depends(log_export("warranty"))])
async def export_csv(request: Request,
                     user: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    rows = await db.warranty_registrations.find({}, {"_id": 0}).sort("created_at", -1).to_list(20000)
    out = io.StringIO()
    w = safe_csv_writer(out)
    w.writerow(["Warranty ID", "SKU", "Product", "Customer", "Email", "Phone",
                "Purchase Date", "Source", "Retailer", "Registered On",
                "Warranty End", "Status", "IP City", "IP State", "IP Country"])
    for r in rows:
        geo = r.get("geo") or {}
        w.writerow([r.get("warranty_id"), r.get("sku"), r.get("product_name"),
                    r.get("name"), r.get("email"), r.get("phone"),
                    (r.get("purchase_date") or "")[:10],
                    r.get("purchase_source"), r.get("retailer_name"),
                    (r.get("created_at") or "")[:10],
                    (r.get("warranty_end") or "")[:10],
                    r.get("status"),
                    geo.get("city"), geo.get("region"), geo.get("country_code")])
    out.seek(0)
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="warranty-registrations.csv"'})


@admin.get("/analytics")
async def analytics(request: Request, months: int = 12,
                     user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER))):
    db = request.app.state.db
    now = datetime.now(timezone.utc)
    months = max(3, min(int(months), 24))
    d30 = (now - timedelta(days=30)).isoformat()
    d60 = (now - timedelta(days=60)).isoformat()

    total = await db.warranty_registrations.count_documents({})
    last_30 = await db.warranty_registrations.count_documents({"created_at": {"$gte": d30}})
    prev_30 = await db.warranty_registrations.count_documents({"created_at": {"$gte": d60, "$lt": d30}})
    active = await db.warranty_registrations.count_documents({"status": "active"})
    claims_open = await db.warranty_claims.count_documents({"status": {"$in": ["submitted", "under_review"]}})
    claims_total = await db.warranty_claims.count_documents({})
    claim_rate_pct = round((claims_total / total * 100), 2) if total else 0.0
    mom_change_pct = round(((last_30 - prev_30) / prev_30 * 100), 1) if prev_30 else (100.0 if last_30 else 0.0)

    # By source
    by_source_cursor = db.warranty_registrations.aggregate([
        {"$group": {"_id": "$purchase_source", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ])
    by_source = [{"source": r["_id"] or "unknown", "count": r["count"]} async for r in by_source_cursor]

    # By state (top 10)
    by_state_cursor = db.warranty_registrations.aggregate([
        {"$group": {"_id": "$geo.region", "count": {"$sum": 1}}},
        {"$match": {"_id": {"$ne": None}}},
        {"$sort": {"count": -1}}, {"$limit": 10},
    ])
    by_state = [{"state": r["_id"], "count": r["count"]} async for r in by_state_cursor]

    # Top SKUs (with claim counts + claim-rate)
    top_sku_cursor = db.warranty_registrations.aggregate([
        {"$group": {"_id": {"sku": "$sku", "name": "$product_name"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}, {"$limit": 10},
    ])
    top_skus = []
    async for r in top_sku_cursor:
        sku = r["_id"]["sku"]
        claim_ct = await db.warranty_claims.count_documents({"sku": sku})
        top_skus.append({
            "sku": sku, "name": r["_id"]["name"], "count": r["count"],
            "claims": claim_ct,
            "claim_rate_pct": round((claim_ct / r["count"] * 100), 2) if r["count"] else 0.0,
        })

    # Month-over-month: last N months of registrations + claims
    # Build the bucket labels first (UTC) so empty months render as zero.
    def _floor_month(d: datetime) -> datetime:
        return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    labels: list[str] = []
    cur = _floor_month(now)
    for _ in range(months):
        labels.append(cur.strftime("%Y-%m"))
        # step back one month
        cur = _floor_month(cur - timedelta(days=1))
    labels.reverse()
    since_iso = (datetime.strptime(labels[0], "%Y-%m").replace(tzinfo=timezone.utc)).isoformat()

    reg_by_month: dict[str, int] = {k: 0 for k in labels}
    claim_by_month: dict[str, int] = {k: 0 for k in labels}
    async for d in db.warranty_registrations.find(
        {"created_at": {"$gte": since_iso}}, {"created_at": 1, "_id": 0}
    ):
        try:
            m = datetime.fromisoformat(d["created_at"].replace("Z", "+00:00")).strftime("%Y-%m")
            if m in reg_by_month:
                reg_by_month[m] += 1
        except Exception:
            pass
    async for d in db.warranty_claims.find(
        {"created_at": {"$gte": since_iso}}, {"created_at": 1, "_id": 0}
    ):
        try:
            m = datetime.fromisoformat(d["created_at"].replace("Z", "+00:00")).strftime("%Y-%m")
            if m in claim_by_month:
                claim_by_month[m] += 1
        except Exception:
            pass
    mom_series = [{
        "month": k,
        "registrations": reg_by_month[k],
        "claims": claim_by_month[k],
        "claim_rate_pct": round((claim_by_month[k] / reg_by_month[k] * 100), 2) if reg_by_month[k] else 0.0,
    } for k in labels]

    return {
        "total": total, "last_30_days": last_30, "prev_30_days": prev_30,
        "mom_change_pct": mom_change_pct,
        "active": active,
        "claims_open": claims_open, "claims_total": claims_total,
        "claim_rate_pct": claim_rate_pct,
        "by_source": by_source, "by_state": by_state, "top_skus": top_skus,
        "mom_series": mom_series,
    }


@admin.get("/claims")
async def list_claims(request: Request, status: Optional[str] = None,
                      skip: int = 0, limit: int = 100,
                      user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER))):
    db = request.app.state.db
    q: dict = {}
    if status: q["status"] = status
    total = await db.warranty_claims.count_documents(q)
    rows = await db.warranty_claims.find(q, {"_id": 0}) \
        .sort("created_at", -1).skip(int(skip)).limit(int(limit)).to_list(int(limit))
    return {"total": total, "rows": rows}


@admin.patch("/claims/{cid}")
async def update_claim(cid: str, body: ClaimUpdate, request: Request,
                        actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "Nothing to update")
    updates["updated_at"] = now_iso()
    if body.status:
        updates["resolved_by"] = actor.get("email")
    r = await db.warranty_claims.update_one({"id": cid}, {"$set": updates})
    if r.matched_count == 0:
        raise HTTPException(404, "Not found")
    # log activity
    claim = await db.warranty_claims.find_one({"id": cid})
    if claim:
        await db.warranty_activity.insert_one({
            "id": gen_id(), "warranty_id": claim["warranty_id"],
            "product_id": claim.get("product_id"), "sku": claim.get("sku"),
            "product_name": claim.get("product_name") or "",
            "event": f"claim_{body.status}" if body.status else "claim_updated",
            "created_at": now_iso(),
        })
    await audit(db, actor, "warranty.claim.update", "claim", cid, updates)
    return {"ok": True}


@admin.get("/settings")
async def get_settings(request: Request,
                       user: dict = Depends(require_roles(ROLE_OWNER))):
    """Per-SKU warranty months override list."""
    db = request.app.state.db
    prods = await db.products.find(
        {}, {"_id": 0, "sku": 1, "name": 1, "warranty_months": 1}
    ).sort("sku", 1).to_list(2000)
    return {"default_months": 6, "products": prods}


class WarrantyMonthsIn(BaseModel):
    sku: str
    warranty_months: int


@admin.post("/settings/product")
async def set_product_warranty(body: WarrantyMonthsIn, request: Request,
                                actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    if body.warranty_months < 0 or body.warranty_months > 60:
        raise HTTPException(400, "warranty_months must be 0..60")
    r = await db.products.update_one(
        {"sku": body.sku}, {"$set": {"warranty_months": int(body.warranty_months)}})
    if r.matched_count == 0:
        raise HTTPException(404, "SKU not found")
    await audit(db, actor, "warranty.setting.update", "product", body.sku,
                {"warranty_months": body.warranty_months})
    return {"ok": True}


router.include_router(admin)
