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


async def sku_map(db) -> Dict[str, dict]:
    """Uniware SKU -> {"product": {...}, "units": n}.

    A product can list its Uniware SKUs in `unicommerce_skus` ([{"sku", "units"}]);
    `units` is how many app units one Uniware unit contains (a pack of 4 = 4).
    Products without a mapping are matched on their own SKU.
    """
    products = await db.products.find({}, {"_id": 0, "id": 1, "sku": 1, "name": 1, "unicommerce_skus": 1}).to_list(50_000)
    out: Dict[str, dict] = {}
    for p in products:
        maps = p.get("unicommerce_skus") or []
        if maps:
            for m in maps:
                if m.get("sku"):
                    out[m["sku"]] = {"product": p, "units": max(1, int(m.get("units") or 1))}
        elif p.get("sku"):
            out.setdefault(p["sku"], {"product": p, "units": 1})
    return out


async def sync_inventory(db, client: uc.UnicommerceClient, locations: Optional[List[str]] = None,
                         actor: Optional[dict] = None) -> dict:
    fmap = uc.facility_map()
    targets = {loc: fac for loc, fac in fmap.items() if not locations or loc in locations}
    if not targets:
        raise uc.UnicommerceError("No Unicommerce facility is mapped. Set UNICOMMERCE_FACILITIES, e.g. AMAZON_FC=AMZFBA01.")
    started = now_iso()
    push_loc = uc.push_settings()["location"]
    if push_loc and push_loc in targets:
        raise uc.UnicommerceError(f"{push_loc} is the location we push to Unicommerce; it cannot also be pulled.")
    smap = await sku_map(db)
    summary: Dict[str, dict] = {}
    try:
        for loc, facility in targets.items():
            snaps = await client.inventory_snapshot(facility, list(smap.keys()))
            totals: Dict[str, int] = {}
            unknown: List[str] = []
            details: Dict[str, dict] = {}
            for s_ in snaps:
                sku = s_.get("itemTypeSKU")
                m = smap.get(sku)
                if not m:
                    unknown.append(str(sku)); continue
                pid = m["product"]["id"]
                totals[pid] = totals.get(pid, 0) + int(s_.get("inventory") or 0) * m["units"]
                d = details.setdefault(pid, {"facility": facility, "open_sale": 0, "blocked": 0,
                                              "putaway_pending": 0, "pending_transfer": 0})
                d["open_sale"] += int(s_.get("openSale") or 0) * m["units"]
                d["blocked"] += int(s_.get("inventoryBlocked") or 0) * m["units"]
                d["putaway_pending"] += int(s_.get("putawayPending") or 0) * m["units"]
                d["pending_transfer"] += int(s_.get("pendingStockTransfer") or 0) * m["units"]
            changed = unchanged = 0
            now = now_iso()
            sku_of = {v["product"]["id"]: v["product"]["sku"] for v in smap.values()}
            for pid, qty in totals.items():
                cur = await db.inventory.find_one({"product_id": pid, "location_code": loc}, {"_id": 0, "quantity": 1})
                before = int((cur or {}).get("quantity") or 0)
                await db.inventory.update_one(
                    {"product_id": pid, "location_code": loc},
                    {"$set": {"quantity": qty, "last_synced_at": now, "updated_at": now,
                              "unicommerce": details.get(pid)}},
                    upsert=True,
                )
                if qty != before:
                    changed += 1
                    await db.stock_movements.insert_one({
                        "id": gen_id(), "product_id": pid, "sku": sku_of.get(pid),
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


async def push_plan(db, client: uc.UnicommerceClient) -> dict:
    """Preview: what sending the push location's stock to Unicommerce would change."""
    cfg = uc.push_settings()
    if not cfg["location"] or not cfg["facility"]:
        raise uc.UnicommerceError("Set UNICOMMERCE_PUSH_LOCATION and UNICOMMERCE_PUSH_FACILITY first.")
    smap = await sku_map(db)
    by_product: Dict[str, List[str]] = {}
    for usku, m in smap.items():
        by_product.setdefault(m["product"]["id"], []).append(usku)
    current = {s_["itemTypeSKU"]: int(s_.get("inventory") or 0)
               for s_ in await client.inventory_snapshot(cfg["facility"], list(smap.keys()))}
    lines, skipped = [], []
    for pid, uskus in by_product.items():
        inv = await db.inventory.find_one({"product_id": pid, "location_code": cfg["location"]}, {"_id": 0, "quantity": 1})
        qty = max(0, int((inv or {}).get("quantity") or 0))
        if len(uskus) > 1 and len({smap[u]["units"] for u in uskus}) == 1:
            # Same product listed as several Uniware SKUs (e.g. colours) - can't split stock safely.
            skipped.append({"product_sku": smap[uskus[0]]["product"]["sku"], "unicommerce_skus": uskus,
                            "reason": "One app product maps to several Unicommerce SKUs with the same pack size. Split the product in the app (one per colour) or keep one mapping."})
            continue
        for u in uskus:
            target = qty // smap[u]["units"]
            if u not in current:
                skipped.append({"product_sku": smap[u]["product"]["sku"], "unicommerce_skus": [u],
                                "reason": "SKU not found in Unicommerce"})
                continue
            lines.append({"product_sku": smap[u]["product"]["sku"], "unicommerce_sku": u,
                          "units_per_pack": smap[u]["units"], "app_stock": qty,
                          "unicommerce_now": current[u], "will_set_to": target,
                          "change": target - current[u]})
    return {"location": cfg["location"], "facility": cfg["facility"], "shelf": cfg["shelf"],
            "lines": sorted(lines, key=lambda l: -abs(l["change"])),
            "changes": sum(1 for l in lines if l["change"]), "skipped": skipped,
            "push_enabled": cfg["enabled"]}


async def push_inventory(db, client: uc.UnicommerceClient, actor: Optional[dict] = None) -> dict:
    cfg = uc.push_settings()
    if not cfg["enabled"]:
        raise uc.UnicommerceError("Pushing stock to Unicommerce is switched off (UNICOMMERCE_PUSH_ENABLED).")
    started = now_iso()
    plan = await push_plan(db, client)
    items = [{"sku": l["unicommerce_sku"], "quantity": l["will_set_to"]} for l in plan["lines"] if l["change"]]
    try:
        results = await client.replace_inventory(cfg["facility"], items, cfg["shelf"]) if items else []
    except uc.UnicommerceError as e:
        await _record_run(db, "push", started, {"error": str(e)}, False, actor)
        raise
    result = {"sent": len(items), "ok": sum(1 for r in results if r["ok"]),
              "failed": [r for r in results if not r["ok"]][:50], "skipped": plan["skipped"]}
    await _record_run(db, "push", started, result, not result["failed"], actor)
    return result


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
    if uc.facility_map() and (not last_inv or now - last_inv >= timedelta(minutes=INVENTORY_EVERY_MIN)):
        try:
            out["inventory"] = await sync_inventory(db, client)
        except uc.UnicommerceError as e:
            log.warning("scheduled inventory sync failed: %s", e)
            out["inventory_error"] = str(e)
    pcfg = uc.push_settings()
    if pcfg["enabled"] and pcfg["auto"]:
        last_push = await _last_ok(db, "push")
        if not last_push or now - last_push >= timedelta(minutes=INVENTORY_EVERY_MIN):
            try:
                out["push"] = await push_inventory(db, client)
            except uc.UnicommerceError as e:
                log.warning("scheduled push failed: %s", e)
                out["push_error"] = str(e)
    last_ord = await _last_ok(db, "orders")
    if not last_ord or now - last_ord >= timedelta(minutes=ORDERS_EVERY_MIN):
        try:
            out["orders"] = await sync_orders(db, client, since_minutes=ORDERS_EVERY_MIN * 3)
        except uc.UnicommerceError as e:
            log.warning("scheduled order sync failed: %s", e)
            out["orders_error"] = str(e)
    return out
