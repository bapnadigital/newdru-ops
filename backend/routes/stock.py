"""Stock movements ledger + transfer workflow (Bhiwandi <-> Store)."""
from fastapi import APIRouter, Request, HTTPException, Depends
from typing import Optional

from models import (
    TransferCreate, ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER, ROLE_WH_STAFF,
    LOC_STORE, LOC_BHIWANDI, gen_id, now_iso,
)
from auth import get_current_user, require_roles, audit
from routes.inventory import _apply_delta, _write_movement

router = APIRouter(prefix="/stock", tags=["stock"])


@router.get("/movements")
async def list_movements(
    request: Request,
    product_id: Optional[str] = None,
    location_code: Optional[str] = None,
    movement_type: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(get_current_user),
):
    db = request.app.state.db
    query: dict = {}
    if product_id: query["product_id"] = product_id
    if location_code: query["location_code"] = location_code
    if movement_type: query["movement_type"] = movement_type
    docs = await db.stock_movements.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return docs


@router.get("/transfers")
async def list_transfers(request: Request, status: Optional[str] = None,
                         user: dict = Depends(get_current_user)):
    db = request.app.state.db
    q: dict = {}
    if status: q["status"] = status
    docs = await db.transfers.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs


@router.post("/transfers")
async def create_transfer(body: TransferCreate, request: Request,
                          actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER))):
    db = request.app.state.db
    if body.from_location not in [LOC_STORE, LOC_BHIWANDI] or body.to_location not in [LOC_STORE, LOC_BHIWANDI]:
        raise HTTPException(400, "Transfers allowed only between Store and Bhiwandi")
    if body.from_location == body.to_location:
        raise HTTPException(400, "from and to locations must differ")
    if not body.items: raise HTTPException(400, "At least one item required")

    now = now_iso()
    doc = {
        "id": gen_id(),
        "from_location": body.from_location, "to_location": body.to_location,
        "items": [it.model_dump() for it in body.items],
        "notes": body.notes, "status": "requested",
        "created_by": actor["id"], "created_by_name": actor["name"],
        "approved_by": None, "dispatched_by": None, "received_by": None,
        "created_at": now, "updated_at": now,
    }
    await db.transfers.insert_one(doc)
    await audit(db, actor, "transfer.create", "transfer", doc["id"],
                {"from": body.from_location, "to": body.to_location, "items": len(body.items)})
    doc.pop("_id", None)
    return doc


@router.post("/transfers/{tid}/approve")
async def approve_transfer(tid: str, request: Request,
                           actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_WH_MANAGER, ROLE_STORE_MANAGER))):
    db = request.app.state.db
    t = await db.transfers.find_one({"id": tid})
    if not t: raise HTTPException(404, "Transfer not found")
    if t["status"] != "requested":
        raise HTTPException(400, f"Cannot approve from status {t['status']}")
    await db.transfers.update_one(
        {"id": tid},
        {"$set": {"status": "approved", "approved_by": actor["id"],
                  "approved_by_name": actor["name"], "updated_at": now_iso()}},
    )
    await audit(db, actor, "transfer.approve", "transfer", tid)
    return {"ok": True}


def _qty(v) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise HTTPException(400, "Quantities must be whole numbers")
    if n < 0 or n > 1_000_000:
        raise HTTPException(400, "Quantity out of range")
    return n


@router.post("/transfers/{tid}/dispatch")
async def dispatch_transfer(tid: str, body: dict, request: Request,
                            actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_WH_MANAGER, ROLE_STORE_MANAGER, ROLE_WH_STAFF))):
    db = request.app.state.db
    t = await db.transfers.find_one({"id": tid})
    if not t: raise HTTPException(404, "Transfer not found")
    if t["status"] not in ("approved", "requested"):
        raise HTTPException(400, f"Cannot dispatch from status {t['status']}")

    dispatch_map = {i["product_id"]: _qty(i.get("dispatched_qty", 0)) for i in body.get("items", [])}
    updated_items = []
    for it in t["items"]:
        asked = int(it.get("requested_qty", 0))
        d = dispatch_map.get(it["product_id"], asked)
        it["dispatched_qty"] = max(0, min(d, asked))   # can send less than asked, never more
        updated_items.append(it)
    # Claim the step atomically so a double-click can't move stock twice.
    if not await db.transfers.find_one_and_update(
            {"id": tid, "status": t["status"]}, {"$set": {"status": "dispatching", "updated_at": now_iso()}}):
        raise HTTPException(409, "This transfer is already being dispatched")

    for it in updated_items:
        d = int(it["dispatched_qty"])
        if d <= 0: continue
        product = await db.products.find_one({"id": it["product_id"]})
        if not product: continue
        await _apply_delta(db, it["product_id"], t["from_location"], -d)
        await _write_movement(db, actor, product, t["from_location"], -d,
                              "transfer_out", reference_id=tid)

    await db.transfers.update_one(
        {"id": tid},
        {"$set": {"status": "dispatched", "items": updated_items,
                  "dispatched_by": actor["id"], "dispatched_by_name": actor["name"],
                  "updated_at": now_iso()}},
    )
    await audit(db, actor, "transfer.dispatch", "transfer", tid, {"items": len(updated_items)})
    return {"ok": True}


@router.post("/transfers/{tid}/receive")
async def receive_transfer(tid: str, body: dict, request: Request,
                           actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER, ROLE_WH_STAFF))):
    db = request.app.state.db
    t = await db.transfers.find_one({"id": tid})
    if not t: raise HTTPException(404, "Transfer not found")
    if t["status"] != "dispatched":
        raise HTTPException(400, f"Cannot receive from status {t['status']}")

    rmap = {i["product_id"]: _qty(i.get("received_qty", 0)) for i in body.get("items", [])}
    updated_items = []
    for it in t["items"]:
        sent = int(it.get("dispatched_qty", 0))
        r = rmap.get(it["product_id"], sent)
        it["received_qty"] = max(0, min(r, sent))      # can't receive more than was sent
        it["short_qty"] = sent - it["received_qty"]
        updated_items.append(it)
    if not await db.transfers.find_one_and_update(
            {"id": tid, "status": "dispatched"}, {"$set": {"status": "receiving", "updated_at": now_iso()}}):
        raise HTTPException(409, "This transfer is already being received")

    for it in updated_items:
        r = int(it["received_qty"])
        if r <= 0: continue
        product = await db.products.find_one({"id": it["product_id"]})
        if not product: continue
        await _apply_delta(db, it["product_id"], t["to_location"], r)
        await _write_movement(db, actor, product, t["to_location"], r,
                              "transfer_in", reference_id=tid)

    await db.transfers.update_one(
        {"id": tid},
        {"$set": {"status": "received", "items": updated_items,
                  "received_by": actor["id"], "received_by_name": actor["name"],
                  "updated_at": now_iso()}},
    )
    short = sum(int(i.get("short_qty", 0)) for i in updated_items)
    await audit(db, actor, "transfer.receive", "transfer", tid, {"items": len(updated_items), "units_short": short})
    return {"ok": True}


@router.post("/transfers/{tid}/cancel")
async def cancel_transfer(tid: str, request: Request,
                          actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER))):
    db = request.app.state.db
    t = await db.transfers.find_one({"id": tid})
    if not t: raise HTTPException(404, "Transfer not found")
    if t["status"] not in ("requested", "approved", "dispatched"):
        raise HTTPException(400, f"Cannot cancel from status {t['status']}")
    if not await db.transfers.find_one_and_update(
            {"id": tid, "status": t["status"]}, {"$set": {"status": "cancelled", "updated_at": now_iso()}}):
        raise HTTPException(409, "This transfer changed meanwhile; refresh and try again")
    if t["status"] == "dispatched":
        # Goods already left: put them back where they came from, so nothing vanishes.
        for it in t["items"]:
            d = int(it.get("dispatched_qty", 0))
            if d <= 0: continue
            product = await db.products.find_one({"id": it["product_id"]})
            if not product: continue
            await _apply_delta(db, it["product_id"], t["from_location"], d)
            await _write_movement(db, actor, product, t["from_location"], d,
                                  "transfer_cancel_return", reference_id=tid)
    await audit(db, actor, "transfer.cancel", "transfer", tid)
    return {"ok": True}
