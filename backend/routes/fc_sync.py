"""Unicommerce FC sync — CSV upload now + live-API stub for later.

Amazon FC (AMAZON_FC) and Flipkart FC (FLIPKART_FC) inventory is read-only in
this app; when Unicommerce creds arrive, `UnicommerceClient.pull_inventory()`
will fill the same collection.
"""
from __future__ import annotations
import io
import csv
import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException, Depends

from models import (
    gen_id, now_iso, LOC_AMAZON_FC, LOC_FLIPKART_FC,
    ROLE_OWNER, ROLE_WH_MANAGER,
)
from auth import require_roles, get_current_user, audit
from security import secret_matches
from services import unicommerce as uc
from services import unicommerce_sync as ucs

router = APIRouter(prefix="/fc-sync", tags=["fc-sync"])

VALID_FC_CODES = {LOC_AMAZON_FC, LOC_FLIPKART_FC}


def _cred(k: str, default: str = "") -> str:
    return os.environ.get(k, default) or ""


def _unicommerce_mode() -> str:
    return uc.mode()


@router.get("/config")
async def config(request: Request, user: dict = Depends(require_roles(ROLE_OWNER, ROLE_WH_MANAGER))):
    db = request.app.state.db
    last = await db.sync_runs.find(
        {"source": "unicommerce"}, {"_id": 0}).sort("finished_at", -1).limit(5).to_list(5)
    return {
        "mode": _unicommerce_mode(),
        "tenant_set": bool(_cred("UNICOMMERCE_TENANT")),
        "api_user_set": bool(_cred("UNICOMMERCE_USER")),
        "password_set": bool(_cred("UNICOMMERCE_PASSWORD")),
        "facilities": uc.facility_map(),
        "inventory_every_minutes": ucs.INVENTORY_EVERY_MIN,
        "orders_every_minutes": ucs.ORDERS_EVERY_MIN,
        "supported_locations": sorted(VALID_FC_CODES),
        "recent_runs": last,
        "note": "CSV upload is always available. Live sync runs automatically when UNICOMMERCE_MODE=live.",
    }


@router.post("/csv")
async def upload_csv(
    request: Request,
    location_code: str = Form(...),
    file: UploadFile = File(...),
    actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_WH_MANAGER)),
):
    """Accept CSV with columns: sku,quantity (extra columns ignored).

    - Matches SKU to product; unknown SKUs are reported in `unknown_skus`.
    - Sets the AMAZON_FC / FLIPKART_FC quantity ABSOLUTELY (not delta).
    - Sets `last_synced_at` on the row.
    """
    if location_code not in VALID_FC_CODES:
        raise HTTPException(400, f"location_code must be one of {sorted(VALID_FC_CODES)}")
    db = request.app.state.db
    raw = (await file.read()).decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "sku" not in [f.lower() for f in reader.fieldnames]:
        raise HTTPException(400, "CSV must have a 'sku' column")

    # Normalise header case
    field_map = {f.lower(): f for f in reader.fieldnames}
    sku_key = field_map["sku"]
    qty_key = field_map.get("quantity") or field_map.get("qty") or field_map.get("stock") or "quantity"

    now = now_iso()
    updated = 0
    unknown = []
    zeroed = []
    for row in reader:
        sku = (row.get(sku_key) or "").strip()
        if not sku: continue
        try: qty = int(float(row.get(qty_key) or 0))
        except Exception: qty = 0
        product = await db.products.find_one({"sku": sku})
        if not product:
            unknown.append(sku); continue
        r = await db.inventory.update_one(
            {"product_id": product["id"], "location_code": location_code},
            {"$set": {"quantity": qty, "last_synced_at": now, "updated_at": now}},
            upsert=True,
        )
        # Write a movement so history is complete (delta unknown → 'sync')
        await db.stock_movements.insert_one({
            "id": gen_id(),
            "product_id": product["id"], "sku": product["sku"],
            "location_code": location_code,
            "movement_type": "fc_sync",
            "quantity_delta": qty, "quantity_after": qty,
            "reason": f"CSV sync from Unicommerce ({file.filename})",
            "user_id": actor["id"], "user_name": actor.get("name"),
            "created_at": now,
        })
        updated += 1
        if qty == 0: zeroed.append(sku)

    await audit(db, actor, "fc_sync.csv", "fc_sync", None,
                {"location_code": location_code, "filename": file.filename,
                 "updated": updated, "unknown": len(unknown), "zeroed": len(zeroed)})

    return {
        "location_code": location_code,
        "filename": file.filename,
        "updated": updated,
        "unknown_skus": unknown[:50],
        "unknown_count": len(unknown),
        "zeroed": len(zeroed),
        "synced_at": now,
    }


def _live_client() -> uc.UnicommerceClient:
    if _unicommerce_mode() != "live":
        raise HTTPException(503, "Unicommerce live mode is off. Use CSV upload, or set UNICOMMERCE_MODE=live with the login details.")
    try:
        return uc.UnicommerceClient.from_env()
    except uc.UnicommerceError as e:
        raise HTTPException(503, str(e))


@router.post("/pull")
async def pull_live(request: Request, location_code: Optional[str] = None,
                    actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_WH_MANAGER))):
    """Pull stock now from Unicommerce for one mapped location (or all mapped)."""
    client = _live_client()
    locations = [location_code.upper()] if location_code else None
    try:
        result = await ucs.sync_inventory(request.app.state.db, client, locations, actor)
    except uc.UnicommerceError as e:
        raise HTTPException(502, str(e))
    await audit(request.app.state.db, actor, "fc_sync.unicommerce_pull", "fc_sync", None,
                {k: {"changed": v["changed"], "unknown": v["unknown_count"]} for k, v in result["locations"].items()})
    return result


@router.post("/orders/pull")
async def pull_orders(request: Request, since_minutes: int = 1440,
                      actor: dict = Depends(require_roles(ROLE_OWNER))):
    """Pull marketplace orders updated in the last N minutes (max 1440)."""
    client = _live_client()
    try:
        return await ucs.sync_orders(request.app.state.db, client, since_minutes, actor)
    except uc.UnicommerceError as e:
        raise HTTPException(502, str(e))


@router.get("/orders/summary")
async def orders_summary(request: Request, days: int = 7,
                         actor: dict = Depends(require_roles(ROLE_OWNER))):
    """Orders by channel and status for the last N days (from synced Unicommerce data)."""
    db = request.app.state.db
    days = max(1, min(int(days), 90))
    since = (datetime.now(timezone.utc).timestamp() - days * 86400) * 1000
    rows = await db.unicommerce_orders.find({}, {"_id": 0, "channel": 1, "status": 1, "uc_created": 1}).to_list(200_000)
    out: dict = {}
    for r in rows:
        created = r.get("uc_created")
        if isinstance(created, (int, float)) and created < since:
            continue
        ch = r.get("channel") or "UNKNOWN"
        st = r.get("status") or "UNKNOWN"
        out.setdefault(ch, {}).setdefault(st, 0)
        out[ch][st] += 1
    return {"days": days, "by_channel": out, "total": sum(sum(v.values()) for v in out.values())}


@router.get("/runs")
async def sync_runs(request: Request, limit: int = 20,
                    actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_WH_MANAGER))):
    db = request.app.state.db
    return await db.sync_runs.find({"source": "unicommerce"}, {"_id": 0}).sort(
        "finished_at", -1).limit(max(1, min(int(limit), 100))).to_list(100)


# ---- Scheduler hook (called every 5 minutes by the Cloudflare Worker cron) ----
internal = APIRouter(prefix="/internal", tags=["internal"])


@internal.post("/cron")
async def cron(request: Request):
    expected = os.environ.get("CRON_SECRET")
    if not secret_matches(request.headers.get("x-cron-token"), expected):
        raise HTTPException(401, "Unauthorized")
    return {"unicommerce": await ucs.run_due(request.app.state.db)}
