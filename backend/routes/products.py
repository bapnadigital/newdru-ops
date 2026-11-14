"""Product master, CSV import/export, barcode logic."""
import re
import csv, io, secrets
from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, File, Query
from fastapi.responses import StreamingResponse

from models import (
    ProductCreate, ProductUpdate, ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER,
    gen_id, now_iso,
)
from auth import get_current_user, require_roles, audit, can_see_cost
from services.pricing import compute_pricing, redact_cost_fields

router = APIRouter(prefix="/products", tags=["products"])


def _gen_internal_barcode() -> str:
    return f"NW{secrets.token_hex(5).upper()}"[:14]


def _serialize(p: dict, include_cost: bool = True) -> dict:
    p = {k: v for k, v in p.items() if k != "_id"}
    if include_cost:
        p["pricing"] = compute_pricing(
            p.get("buy_price", 0), p.get("gst_rate", 18), p.get("sell_price") or None
        )
    else:
        p = redact_cost_fields(p)
    return p


@router.get("")
async def list_products(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    status: str | None = None,
    placeholder_pricing: bool | None = None,
    limit: int = 500,
    user: dict = Depends(get_current_user),
):
    db = request.app.state.db
    query: dict = {}
    if q:
        query["$or"] = [
            {"sku": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"name": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"barcode": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"brand": {"$regex": re.escape(q[:64]), "$options": "i"}},
        ]
    if category: query["category"] = category
    if status: query["status"] = status
    if placeholder_pricing is True:
        query["placeholder_pricing"] = True
    elif placeholder_pricing is False:
        query["placeholder_pricing"] = {"$ne": True}
    docs = await db.products.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)
    include_cost = can_see_cost(user)
    return [_serialize(d, include_cost) for d in docs]


@router.get("/lookup")
async def lookup_by_barcode(
    request: Request,
    code: str = Query(..., description="Barcode / SKU / FNSKU"),
    user: dict = Depends(get_current_user),
):
    db = request.app.state.db
    doc = await db.products.find_one({"$or": [{"barcode": code}, {"sku": code}]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Product not found for code")
    return _serialize(doc, can_see_cost(user))


@router.get("/{product_id}")
async def get_product(product_id: str, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    doc = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Product not found")
    return _serialize(doc, can_see_cost(user))


@router.post("")
async def create_product(
    body: ProductCreate,
    request: Request,
    actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER)),
):
    db = request.app.state.db
    sku = body.sku.strip()
    if not sku: raise HTTPException(400, "SKU required")
    if await db.products.find_one({"sku": sku}):
        raise HTTPException(409, "SKU already exists")

    barcode = body.barcode.strip() if body.barcode else None
    barcode_type = body.barcode_type
    if body.channel_scope == "online_offline":
        if not barcode:
            raise HTTPException(400, "FNSKU barcode required for online+offline products")
        barcode_type = "FNSKU"
    else:
        if not barcode:
            barcode = _gen_internal_barcode()
        barcode_type = "CODE128"

    if await db.products.find_one({"barcode": barcode}):
        raise HTTPException(409, "Barcode already in use")

    pr = compute_pricing(body.buy_price, body.gst_rate, body.sell_price or None)
    sell_price = body.sell_price if body.sell_price and body.sell_price > 0 else pr["recommended_sell_price"]

    doc = body.model_dump()
    doc.update({
        "id": gen_id(),
        "sku": sku, "barcode": barcode, "barcode_type": barcode_type,
        "sell_price": sell_price,
        "created_at": now_iso(), "updated_at": now_iso(),
    })
    await db.products.insert_one(doc)
    await audit(db, actor, "product.create", "product", doc["id"], {"sku": sku, "barcode": barcode})
    return _serialize(doc, can_see_cost(actor))


@router.patch("/{product_id}")
async def update_product(
    product_id: str, body: ProductUpdate, request: Request,
    actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER)),
):
    db = request.app.state.db
    existing = await db.products.find_one({"id": product_id})
    if not existing: raise HTTPException(404, "Product not found")

    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "barcode" in updates and updates["barcode"] != existing.get("barcode"):
        if await db.products.find_one({"barcode": updates["barcode"], "id": {"$ne": product_id}}):
            raise HTTPException(409, "Barcode already in use")

    if "buy_price" in updates or "gst_rate" in updates:
        buy = updates.get("buy_price", existing.get("buy_price", 0))
        gst = updates.get("gst_rate", existing.get("gst_rate", 18))
        sp = updates.get("sell_price", existing.get("sell_price"))
        if not sp or sp <= 0:
            pr = compute_pricing(buy, gst, None)
            updates["sell_price"] = pr["recommended_sell_price"]

    # Auto-clear the placeholder-pricing flag once real pricing is set
    if existing.get("placeholder_pricing"):
        new_sell = updates.get("sell_price", existing.get("sell_price"))
        new_buy = updates.get("buy_price", existing.get("buy_price"))
        if (new_sell and new_sell > 0) or (new_buy and new_buy > 0):
            updates["placeholder_pricing"] = False

    updates["updated_at"] = now_iso()
    await db.products.update_one({"id": product_id}, {"$set": updates})
    await audit(db, actor, "product.update", "product", product_id, updates)
    doc = await db.products.find_one({"id": product_id}, {"_id": 0})
    return _serialize(doc, can_see_cost(actor))


@router.delete("/{product_id}")
async def delete_product(product_id: str, request: Request,
                         actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    res = await db.products.delete_one({"id": product_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Product not found")
    await db.inventory.delete_many({"product_id": product_id})
    await audit(db, actor, "product.delete", "product", product_id)
    return {"ok": True}


@router.post("/preview-pricing")
async def preview_pricing(body: dict,
                          user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER))):
    return compute_pricing(
        float(body.get("buy_price") or 0),
        float(body.get("gst_rate") or 18),
        float(body.get("sell_price")) if body.get("sell_price") else None,
    )


@router.post("/import-csv")
async def import_csv(request: Request, file: UploadFile = File(...),
                     actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER))):
    db = request.app.state.db
    content = (await file.read()).decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    created, updated, errors = 0, 0, []
    # Only set columns that are actually present & non-blank in the CSV — never wipe fields on update.
    STR = {"name", "brand", "category", "variant", "hsn", "channel_scope", "status", "barcode"}
    FLOAT = {"mrp", "gst_rate", "buy_price", "sell_price", "unit_weight_g"}
    INT = {"units_per_carton"}
    def _present(row, k):
        v = row.get(k)
        return v is not None and str(v).strip() != ""

    for i, row in enumerate(reader, start=2):
        try:
            sku = (row.get("sku") or "").strip()
            if not sku:
                errors.append({"row": i, "error": "Missing SKU"}); continue
            provided: dict = {}
            for k in STR:
                if _present(row, k): provided[k] = str(row[k]).strip()
            for k in FLOAT:
                if _present(row, k): provided[k] = float(row[k])
            for k in INT:
                if _present(row, k): provided[k] = int(float(row[k]))

            existing = await db.products.find_one({"sku": sku})
            if existing:
                provided["updated_at"] = now_iso()
                # If channel_scope flipped to online_offline and no barcode was supplied, keep existing.
                if provided.get("channel_scope") == "online_offline" and not provided.get("barcode") and not existing.get("barcode"):
                    errors.append({"row": i, "error": "online_offline requires a barcode (FNSKU)"}); continue
                await db.products.update_one({"sku": sku}, {"$set": provided})
                updated += 1
            else:
                # New product — defaults
                channel = provided.get("channel_scope", "offline_only")
                barcode = provided.get("barcode")
                if channel == "online_offline" and not barcode:
                    errors.append({"row": i, "error": "online_offline requires FNSKU barcode"}); continue
                gst_rate = provided.get("gst_rate", 18)
                buy_price = provided.get("buy_price", 0)
                sell = provided.get("sell_price")
                if not sell or sell <= 0:
                    pr = compute_pricing(buy_price, gst_rate, None)
                    provided["sell_price"] = pr["recommended_sell_price"]
                provided.setdefault("name", sku)
                provided["barcode"] = barcode or _gen_internal_barcode()
                provided["barcode_type"] = "FNSKU" if barcode and channel == "online_offline" else "CODE128"
                provided.setdefault("channel_scope", channel)
                provided.setdefault("status", "active")
                provided["sku"] = sku
                provided["id"] = gen_id()
                provided["created_at"] = now_iso()
                provided["updated_at"] = now_iso()
                provided["images"] = []
                await db.products.insert_one(provided)
                created += 1
        except Exception as e:
            errors.append({"row": i, "error": str(e)})
    await audit(db, actor, "product.csv_import", "product", None,
                {"created": created, "updated": updated, "errors": len(errors)})
    return {"created": created, "updated": updated, "errors": errors[:20]}


@router.get("/export/csv")
async def export_csv(request: Request,
                     user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER))):
    db = request.app.state.db
    docs = await db.products.find({}, {"_id": 0}).to_list(10000)
    output = io.StringIO()
    fieldnames = ["sku", "name", "brand", "category", "variant", "mrp", "gst_rate", "hsn",
                  "channel_scope", "status", "barcode", "barcode_type", "buy_price",
                  "sell_price", "unit_weight_g", "units_per_carton"]
    w = csv.DictWriter(output, fieldnames=fieldnames)
    w.writeheader()
    for d in docs:
        w.writerow({k: d.get(k, "") for k in fieldnames})
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=products.csv"})
