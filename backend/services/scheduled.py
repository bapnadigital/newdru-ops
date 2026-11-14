"""Jobs run by the 5-minute Cloudflare scheduler (via /api/internal/cron)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger("scheduled")
SHOPIFY_EVERY_MIN = int(os.environ.get("SHOPIFY_SYNC_MINUTES", "60"))


async def shopify_orders_if_due(db) -> dict:
    from services import shopify
    cfg = await shopify.get_config(db)
    if not cfg.get("ready"):
        return {"skipped": "shopify not connected"}
    last = await db.sync_runs.find_one({"source": "shopify", "kind": "orders", "ok": True},
                                       {"_id": 0, "finished_at": 1}, sort=[("finished_at", -1)])
    now = datetime.now(timezone.utc)
    if last and now - datetime.fromisoformat(last["finished_at"]) < timedelta(minutes=SHOPIFY_EVERY_MIN):
        return {"skipped": "not due"}
    from routes.shopify_sync import pull_orders
    try:
        # look back 3 sync periods so nothing is missed if a run fails
        return await pull_orders(db, since_hours=max(1, SHOPIFY_EVERY_MIN * 3 // 60), limit=250)
    except Exception as e:  # never break the scheduler
        log.warning("scheduled shopify sync failed: %s", e)
        return {"error": str(e)}
