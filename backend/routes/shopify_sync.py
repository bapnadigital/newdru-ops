"""Shopify sync routes — orders pull + inventory push + settings."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel

from auth import require_roles, audit
from models import ROLE_OWNER, gen_id, now_iso, LOC_STORE
from services.shopify import get_config, save_settings, fetch_orders, push_inventory

router = APIRouter(prefix="/shopify", tags=["shopify"])


class SettingsIn(BaseModel):
    shop_domain: Optional[str] = None      # e.g. newdru.myshopify.com
    access_token: Optional[str] = None
    location_id: Optional[str] = None
    mode: Optional[str] = None             # disabled | pull_only | full
    webhook_secret: Optional[str] = None


@router.get("/config")
async def config(request: Request, user: dict = Depends(require_roles(ROLE_OWNER))):
    return await get_config(request.app.state.db)


@router.post("/settings")
async def settings(body: SettingsIn, request: Request,
                    actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    patch = body.model_dump(exclude_none=True)
    result = await save_settings(db, patch)
    await audit(db, actor, "shopify.settings.update", "settings", "shopify",
                {"fields": list(patch)})
    return result


@router.post("/sync/orders")
async def sync_orders(request: Request, since_hours: int = 24, limit: int = 50,
                       actor: dict = Depends(require_roles(ROLE_OWNER))):
    """Manual pull of recent orders. Creates warranty 'purchased' activity events
    per line item so admins can see purchases in the User Activities feed.
    """
    return await pull_orders(request.app.state.db, since_hours, limit, actor)


async def pull_orders(db, since_hours: int = 24, limit: int = 50, actor: dict | None = None) -> dict:
    """Shared by the button and the hourly scheduler."""
    since = (datetime.now(timezone.utc) - timedelta(hours=int(since_hours))).isoformat()
    res = await fetch_orders(db, since_iso=since, limit=limit)
    if not res.get("ok"):
        return res
    orders = res["orders"]
    matched, unknown = 0, 0
    now = now_iso()
    for o in orders:
        # de-dup by shopify order id
        order_key = f"shopify:{o.get('id')}"
        if await db.warranty_activity.find_one({"tracking_id": order_key, "event": "purchased"}):
            continue
        customer = o.get("customer") or {}
        email = (customer.get("email") or o.get("email") or "").lower() or None
        phone = customer.get("phone") or o.get("phone")
        for li in o.get("line_items") or []:
            sku = li.get("sku")
            if not sku: unknown += 1; continue
            p = await db.products.find_one({"sku": sku}, {"_id": 0})
            if not p:
                unknown += 1
                await db.warranty_activity.insert_one({
                    "id": gen_id(), "warranty_id": None, "product_id": None,
                    "sku": sku, "product_name": li.get("title"),
                    "event": "purchased", "tracking_id": order_key,
                    "source": "shopify",
                    "customer_email": email, "customer_phone": phone,
                    "created_at": o.get("created_at") or now,
                })
                continue
            matched += 1
            await db.warranty_activity.insert_one({
                "id": gen_id(), "warranty_id": None, "product_id": p["id"],
                "sku": p["sku"], "product_name": p["name"],
                "event": "purchased", "tracking_id": order_key,
                "source": "shopify",
                "customer_email": email, "customer_phone": phone,
                "created_at": o.get("created_at") or now,
            })
    await db.sync_runs.insert_one({"id": gen_id(), "source": "shopify", "kind": "orders", "ok": True,
                                   "started_at": now, "finished_at": now_iso(),
                                   "by": (actor or {}).get("email") or "scheduler",
                                   "result": {"orders": len(orders), "matched": matched, "unknown": unknown}})
    await audit(db, actor, "shopify.sync.orders", "shopify", None,
                {"since_hours": since_hours, "matched": matched, "unknown": unknown,
                 "count": len(orders)})
    return {"ok": True, "orders": len(orders), "matched_line_items": matched,
            "unknown_skus": unknown}


@router.post("/sync/inventory")
async def sync_inventory(request: Request,
                          actor: dict = Depends(require_roles(ROLE_OWNER))):
    """Push STORE stock levels for every product to the configured Shopify location."""
    db = request.app.state.db
    cfg = await get_config(db)
    if not cfg.get("ready") or cfg["mode"] != "full":
        raise HTTPException(400, "Shopify not in `full` mode or not configured.")
    ok, failed = [], []
    # Pull store inventory rows
    rows = await db.inventory.find({"location_code": LOC_STORE}, {"_id": 0}).to_list(5000)
    for row in rows:
        p = await db.products.find_one({"id": row["product_id"]}, {"_id": 0, "sku": 1})
        if not p: continue
        qty = int(row.get("quantity") or 0)
        res = await push_inventory(db, p["sku"], qty)
        (ok if res.get("ok") else failed).append({"sku": p["sku"], "qty": qty, **res})
    await audit(db, actor, "shopify.sync.inventory", "shopify", None,
                {"pushed": len(ok), "failed": len(failed)})
    return {"pushed": len(ok), "failed": len(failed), "failures": failed[:20]}
