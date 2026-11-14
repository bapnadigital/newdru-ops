"""Unified inventory grid & adjustments."""
import re
from fastapi import APIRouter, Request, HTTPException, Depends, Query
from typing import Optional

from models import (
    InventoryAdjust, LowStockThresholdSet, LOCATIONS, LOC_STORE, LOC_BHIWANDI,
    ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER, STORE_ROLES,
    gen_id, now_iso,
)
from auth import get_current_user, require_roles, audit, can_see_cost

router = APIRouter(prefix="/inventory", tags=["inventory"])


async def _apply_delta(db, product_id: str, location_code: str, delta: int) -> int:
    now = now_iso()
    doc = await db.inventory.find_one_and_update(
        {"product_id": product_id, "location_code": location_code},
        {"$inc": {"quantity": delta},
         "$set": {"last_synced_at": now},
         "$setOnInsert": {"low_stock_threshold": 5, "id": gen_id()}},
        upsert=True, return_document=True,
    )
    if doc is None:
        doc = await db.inventory.find_one({"product_id": product_id, "location_code": location_code})
    return int(doc.get("quantity", 0))


async def _write_movement(db, user: dict, product: dict, location_code: str,
                          delta: int, mtype: str, reason: str | None = None,
                          reference_id: str | None = None):
    mv = {
        "id": gen_id(),
        "product_id": product["id"], "sku": product.get("sku", ""),
        "location_code": location_code, "movement_type": mtype,
        "quantity_delta": delta, "reason": reason, "reference_id": reference_id,
        "user_id": user.get("id") if user else None,
        "user_name": user.get("name") if user else None,
        "created_at": now_iso(),
    }
    await db.stock_movements.insert_one(mv)


@router.get("/locations")
async def locations():
    return LOCATIONS


@router.get("/grid")
async def inventory_grid(
    request: Request,
    q: Optional[str] = None,
    category: Optional[str] = None,
    filter: Optional[str] = Query(None, description="low_stock | out_of_stock"),
    user: dict = Depends(get_current_user),
):
    db = request.app.state.db
    pquery: dict = {}
    if q:
        pquery["$or"] = [
            {"sku": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"name": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"barcode": {"$regex": re.escape(q[:64]), "$options": "i"}},
        ]
    if category: pquery["category"] = category

    products = await db.products.find(pquery, {"_id": 0}).sort("name", 1).to_list(2000)
    if not products:
        return {"rows": [], "locations": LOCATIONS}

    # Role scoping: STORE users only see Newdru Store stock.
    role = (user or {}).get("role")
    if role in STORE_ROLES:
        visible_locations = [l for l in LOCATIONS if l["code"] == LOC_STORE]
    else:
        visible_locations = LOCATIONS

    pids = [p["id"] for p in products]
    inv = await db.inventory.find({"product_id": {"$in": pids}}, {"_id": 0}).to_list(20000)
    inv_map: dict = {}
    for row in inv:
        inv_map.setdefault(row["product_id"], {})[row["location_code"]] = row

    include_cost = can_see_cost(user)
    rows = []
    for p in products:
        pinv = inv_map.get(p["id"], {})
        location_qty = {}
        total = 0
        low_flag = False
        for loc in visible_locations:
            code = loc["code"]
            r = pinv.get(code, {})
            qty = int(r.get("quantity", 0))
            thr = int(r.get("low_stock_threshold", 5))
            last = r.get("last_synced_at")
            location_qty[code] = {"quantity": qty, "threshold": thr,
                                  "last_synced_at": last, "editable": loc["editable"]}
            total += qty
            if qty <= thr: low_flag = True
        row = {
            "product_id": p["id"], "sku": p["sku"], "name": p["name"],
            "brand": p.get("brand"), "category": p.get("category"),
            "barcode": p.get("barcode"), "mrp": p.get("mrp"),
            "sell_price": p.get("sell_price"),
            "channel_scope": p.get("channel_scope"),
            "total": total, "low_stock": low_flag,
            "out_of_stock": (total == 0),
            "locations": location_qty,
        }
        if include_cost:
            row["buy_price"] = p.get("buy_price")
        rows.append(row)

    if filter == "low_stock":
        rows = [r for r in rows if r["low_stock"]]
    elif filter == "out_of_stock":
        rows = [r for r in rows if r["out_of_stock"]]

    return {"rows": rows, "locations": visible_locations}


@router.get("/alerts")
async def low_stock_alerts(request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    inv = await db.inventory.find({}, {"_id": 0}).to_list(20000)
    alerts = []
    products = {p["id"]: p for p in await db.products.find({}, {"_id": 0}).to_list(5000)}
    for r in inv:
        p = products.get(r["product_id"])
        if not p: continue
        if int(r.get("quantity", 0)) <= int(r.get("low_stock_threshold", 5)):
            alerts.append({
                "sku": p["sku"], "name": p["name"],
                "location_code": r["location_code"],
                "quantity": r["quantity"], "threshold": r["low_stock_threshold"],
            })
    alerts.sort(key=lambda a: (a["quantity"], a["name"]))
    return alerts


@router.post("/adjust")
async def adjust(body: InventoryAdjust, request: Request,
                 actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER))):
    db = request.app.state.db
    if not body.reason.strip():
        raise HTTPException(400, "Reason is required for adjustments")
    loc = next((l for l in LOCATIONS if l["code"] == body.location_code), None)
    if not loc or not loc["editable"]:
        raise HTTPException(400, "Location not editable")
    product = await db.products.find_one({"id": body.product_id}, {"_id": 0})
    if not product: raise HTTPException(404, "Product not found")

    if actor["role"] == "store_manager" and body.location_code != LOC_STORE:
        raise HTTPException(403, "Store Manager can only adjust Store stock")
    if actor["role"] == "warehouse_manager" and body.location_code != LOC_BHIWANDI:
        raise HTTPException(403, "Warehouse Manager can only adjust Bhiwandi stock")

    new_qty = await _apply_delta(db, body.product_id, body.location_code, body.quantity_delta)
    await _write_movement(db, actor, product, body.location_code, body.quantity_delta,
                          "adjustment", reason=body.reason)
    await audit(db, actor, "inventory.adjust", "inventory", body.product_id,
                {"location": body.location_code, "delta": body.quantity_delta,
                 "reason": body.reason, "new_qty": new_qty})
    return {"product_id": body.product_id, "location_code": body.location_code, "quantity": new_qty}


@router.post("/receive")
async def receive(body: dict, request: Request,
                  actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER, "warehouse_staff"))):
    """Barcode-driven goods receipt.
    body: {location_code, reference, notes, lines: [{barcode/sku/product_id, cartons, units}]}"""
    db = request.app.state.db
    loc_code = body.get("location_code")
    loc = next((l for l in LOCATIONS if l["code"] == loc_code), None)
    if not loc or not loc["editable"]:
        raise HTTPException(400, "Location not editable")

    results = []
    for line in body.get("lines", []):
        code = line.get("barcode") or line.get("sku") or line.get("product_id")
        product = await db.products.find_one(
            {"$or": [{"barcode": code}, {"sku": code}, {"id": code}]}, {"_id": 0}
        )
        if not product:
            results.append({"code": code, "error": "unknown"}); continue
        try:
            cartons = int(line.get("cartons") or 0)
            units_extra = int(line.get("units") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "Cartons and units must be whole numbers")
        # Goods-in only adds stock; removals go through Adjust (with a reason) or Stock Count.
        if cartons < 0 or units_extra < 0 or cartons > 100_000 or units_extra > 1_000_000:
            raise HTTPException(400, "Goods-in quantities must be between 0 and 100,000 cartons")
        upc = int(product.get("units_per_carton") or 1)
        delta = cartons * upc + units_extra
        if delta == 0: continue
        new_qty = await _apply_delta(db, product["id"], loc_code, delta)
        await _write_movement(db, actor, product, loc_code, delta,
                              "goods_receipt", reason=body.get("notes"),
                              reference_id=body.get("reference"))
        results.append({"sku": product["sku"], "name": product["name"],
                        "delta": delta, "quantity": new_qty})

    await audit(db, actor, "inventory.receive", "inventory", None,
                {"location": loc_code, "lines": len(results), "reference": body.get("reference")})
    return {"received": results}


@router.post("/threshold")
async def set_threshold(body: LowStockThresholdSet, request: Request,
                        actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER))):
    db = request.app.state.db
    await db.inventory.update_one(
        {"product_id": body.product_id, "location_code": body.location_code},
        {"$set": {"low_stock_threshold": body.low_stock_threshold, "last_synced_at": now_iso()},
         "$setOnInsert": {"id": gen_id(), "quantity": 0}},
        upsert=True,
    )
    await audit(db, actor, "inventory.threshold", "inventory", body.product_id,
                {"location": body.location_code, "threshold": body.low_stock_threshold})
    return {"ok": True}


# ================= Stock count (physical count by staff) =================
from pydantic import BaseModel as _BM, Field as _F


class CountLine(_BM):
    sku: str = _F(max_length=120)
    counted: int = _F(ge=0, le=1_000_000)


class StockCountIn(_BM):
    location_code: str
    lines: list[CountLine] = _F(min_length=1, max_length=2000)
    note: str | None = _F(default=None, max_length=500)


_COUNT_ROLES = {
    LOC_STORE: {ROLE_OWNER, ROLE_STORE_MANAGER, "cashier"},
    LOC_BHIWANDI: {ROLE_OWNER, ROLE_WH_MANAGER, "warehouse_staff"},
}


@router.get("/count-sheet")
async def count_sheet(request: Request, location_code: str,
                      actor: dict = Depends(get_current_user)):
    """Products to count at a location. Blind: staff don't see the system quantity."""
    if actor["role"] not in _COUNT_ROLES.get(location_code, set()):
        raise HTTPException(403, "You can't count stock at this location")
    db = request.app.state.db
    prods = await db.products.find({"active": {"$ne": False}},
                                   {"_id": 0, "id": 1, "sku": 1, "name": 1, "barcode": 1}).sort("name", 1).to_list(5000)
    return {"location_code": location_code, "products": prods}


@router.post("/count")
async def submit_count(body: StockCountIn, request: Request,
                       actor: dict = Depends(get_current_user)):
    """Save a physical count. Every difference becomes a 'count' movement, so the
    ledger shows who counted what and how much stock was missing or extra."""
    if actor["role"] not in _COUNT_ROLES.get(body.location_code, set()):
        raise HTTPException(403, "You can't count stock at this location")
    db = request.app.state.db
    now = now_iso()
    lines_out, unknown = [], []
    for ln in body.lines:
        product = await db.products.find_one({"$or": [{"sku": ln.sku}, {"barcode": ln.sku}]}, {"_id": 0})
        if not product:
            unknown.append(ln.sku); continue
        inv = await db.inventory.find_one({"product_id": product["id"], "location_code": body.location_code},
                                          {"_id": 0, "quantity": 1})
        system = int((inv or {}).get("quantity") or 0)
        delta = int(ln.counted) - system
        if delta:
            await _apply_delta(db, product["id"], body.location_code, delta)
            await _write_movement(db, actor, product, body.location_code, delta, "count",
                                  reason=f"Stock count{': ' + body.note if body.note else ''}")
        lines_out.append({"sku": product["sku"], "name": product["name"], "system": system,
                          "counted": int(ln.counted), "difference": delta})
    doc = {
        "id": gen_id(), "location_code": body.location_code, "note": body.note,
        "counted_by": actor.get("name"), "counted_by_id": actor["id"], "created_at": now,
        "lines": lines_out, "unknown_skus": unknown,
        "items_counted": len(lines_out),
        "items_with_difference": sum(1 for l in lines_out if l["difference"]),
        "units_missing": -sum(l["difference"] for l in lines_out if l["difference"] < 0),
        "units_extra": sum(l["difference"] for l in lines_out if l["difference"] > 0),
    }
    await db.stock_counts.insert_one(dict(doc))
    await audit(db, actor, "inventory.count", "stock_count", doc["id"],
                {"location": body.location_code, "differences": doc["items_with_difference"]})
    # Staff only learn how many lines differed; the owner sees the details.
    if actor["role"] == ROLE_OWNER:
        return doc
    return {"id": doc["id"], "items_counted": doc["items_counted"],
            "items_with_difference": doc["items_with_difference"], "unknown_skus": unknown}


@router.get("/counts")
async def list_counts(request: Request, location_code: str | None = None, limit: int = 30,
                      actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER))):
    db = request.app.state.db
    q = {"location_code": location_code} if location_code else {}
    if actor["role"] == ROLE_STORE_MANAGER:
        q["location_code"] = LOC_STORE
    if actor["role"] == ROLE_WH_MANAGER:
        q["location_code"] = LOC_BHIWANDI
    rows = await db.stock_counts.find(q, {"_id": 0}).sort("created_at", -1).limit(max(1, min(int(limit), 200))).to_list(200)
    if actor["role"] != ROLE_OWNER:
        for r in rows:  # managers see who counted and how many differences, not costs
            r.pop("lines", None)
    return rows
