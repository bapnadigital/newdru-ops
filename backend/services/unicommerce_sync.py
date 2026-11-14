"""Pull stock and marketplace orders from Unicommerce into NEWDRU Ops."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from models import gen_id, now_iso
from services import unicommerce as uc

log = logging.getLogger("unicommerce.sync")

INVENTORY_EVERY_MIN = int(os.environ.get("UNICOMMERCE_SYNC_MINUTES", "30"))
ORDERS_EVERY_MIN = int(os.environ.get("UNICOMMERCE_ORDERS_MINUTES", "60"))


async def _record_run(db, kind: str, started: str, result: dict, ok: bool, actor: Optional[dict]):
    await db.sync_runs.insert_one({
        "id": gen_id(), "source": "unicommerce", "kind": kind, "ok": ok,
        "started_at": started, "finished_at": now_iso(),
        "by": (actor or {}).get("email") or "scheduler",
        "result": result,
    })


async def sync_inventory(db, client: uc.UnicommerceClient, locations: Optional[List[str]] = None,
                         actor: Optional[dict] = None) -> dict:
    fmap = uc.facility_map()
    targets = {loc: fac for loc, fac in fmap.items() if not locations or loc in locations}
    if not targets:
        raise uc.UnicommerceError("No Unicommerce facility is mapped. Set UNICOMMERCE_FACILITIES, e.g. AMAZON_FC=AMZFBA01.")
    started = now_iso()
    products = await db.products.find({}, {"_id": 0, "id": 1, "sku": 1}).to_list(50_000)
    by_sku: Dict[str, dict] = {p["sku"]: p for p in products if p.get("sku")}
    summary: Dict[str, dict] = {}
    try:
        for loc, facility in targets.items():
            snaps = await client.inventory_snapshot(facility, list(by_sku.keys()))
            changed = unchanged = 0
            unknown: List[str] = []
            now = now_iso()
            for s in snaps:
                sku = s.get("itemTypeSKU")
                p = by_sku.get(sku)
                if not p:
                    unknown.append(str(sku)); continue
                qty = int(s.get("inventory") or 0)
                cur = await db.inventory.find_one({"product_id": p["id"], "location_code": loc}, {"_id": 0, "quantity": 1})
                before = int((cur or {}).get("quantity") or 0)
                await db.inventory.update_one(
                    {"product_id": p["id"], "location_code": loc},
                    {"$set": {"quantity": qty, "last_synced_at": now, "updated_at": now,
                              "unicommerce": {
                                  "facility": facility,
                                  "open_sale": int(s.get("openSale") or 0),
                                  "blocked": int(s.get("inventoryBlocked") or 0),
                                  "putaway_pending": int(s.get("putawayPending") or 0),
                                  "pending_transfer": int(s.get("pendingStockTransfer") or 0),
                              }}},
                    upsert=True,
                )
                if qty != before:
                    changed += 1
                    await db.stock_movements.insert_one({
                        "id": gen_id(), "product_id": p["id"], "sku": sku,
                        "location_code": loc, "movement_type": "fc_sync",
                        "quantity_delta": qty - before, "quantity_after": qty,
                        "reason": f"Unicommerce sync ({facility})",
                        "user_id": (actor or {}).get("id"), "user_name": (actor or {}).get("name") or "Unicommerce sync",
                        "created_at": now,
                    })
                else:
                    unchanged += 1
            summary[loc] = {"facility": facility, "received": len(snaps), "changed": changed,
                            "unchanged": unchanged, "unknown_count": len(unknown), "unknown_skus": unknown[:50]}
    except uc.UnicommerceError as e:
        await _record_run(db, "inventory", started, {"error": str(e), "partial": summary}, False, actor)
        raise
    await _record_run(db, "inventory", started, summary, True, actor)
    return {"synced_at": now_iso(), "locations": summary}


def _order_doc(o: dict) -> dict:
    """Keep what the business needs for reports; no customer phone/email/address."""
    return {
        "code": o.get("code"),
        "display_order_code": o.get("displayOrderCode"),
        "channel": o.get("channel"),
        "status": o.get("status"),
        "order_date": o.get("displayOrderDateTime") or o.get("created"),
        "uc_created": o.get("created"),
        "uc_updated": o.get("updated"),
    }


async def sync_orders(db, client: uc.UnicommerceClient, since_minutes: int = 180,
                      actor: Optional[dict] = None) -> dict:
    started = now_iso()
    try:
        rows = await client.search_orders(updated_since_minutes=min(int(since_minutes), 1440))
    except uc.UnicommerceError as e:
        await _record_run(db, "orders", started, {"error": str(e)}, False, actor)
        raise
    now = now_iso()
    new = updated = 0
    for o in rows:
        doc = _order_doc(o)
        if not doc["code"]:
            continue
        res = await db.unicommerce_orders.update_one(
            {"code": doc["code"]},
            {"$set": {**doc, "synced_at": now}, "$setOnInsert": {"id": gen_id(), "first_seen_at": now}},
            upsert=True,
        )
        if res.upserted_id is not None:
            new += 1
        else:
            updated += 1
    result = {"received": len(rows), "new": new, "updated": updated}
    await _record_run(db, "orders", started, result, True, actor)
    return result


async def _last_ok(db, kind: str) -> Optional[datetime]:
    doc = await db.sync_runs.find_one({"source": "unicommerce", "kind": kind, "ok": True},
                                      {"_id": 0, "finished_at": 1}, sort=[("finished_at", -1)])
    if not doc:
        return None
    return datetime.fromisoformat(doc["finished_at"])


async def run_due(db, client_factory=uc.UnicommerceClient.from_env) -> dict:
    """Called by the 5-minute scheduler. Runs each job only when it is due."""
    if uc.mode() != "live" or not uc.configured():
        return {"skipped": "unicommerce not live"}
    now = datetime.now(timezone.utc)
    out: dict = {}
    client = client_factory()
    last_inv = await _last_ok(db, "inventory")
    if not last_inv or now - last_inv >= timedelta(minutes=INVENTORY_EVERY_MIN):
        try:
            out["inventory"] = await sync_inventory(db, client)
        except uc.UnicommerceError as e:
            log.warning("scheduled inventory sync failed: %s", e)
            out["inventory_error"] = str(e)
    last_ord = await _last_ok(db, "orders")
    if not last_ord or now - last_ord >= timedelta(minutes=ORDERS_EVERY_MIN):
        try:
            out["orders"] = await sync_orders(db, client, since_minutes=ORDERS_EVERY_MIN * 3)
        except uc.UnicommerceError as e:
            log.warning("scheduled order sync failed: %s", e)
            out["orders_error"] = str(e)
    return out
