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

router = APIRouter(prefix="/fc-sync", tags=["fc-sync"])

VALID_FC_CODES = {LOC_AMAZON_FC, LOC_FLIPKART_FC}


def _cred(k: str, default: str = "") -> str:
    return os.environ.get(k, default) or ""


def _unicommerce_mode() -> str:
    m = (os.environ.get("UNICOMMERCE_MODE") or "disabled").lower()
    return m if m in ("disabled", "csv_only", "live") else "disabled"


@router.get("/config")
async def config(user: dict = Depends(get_current_user)):
    return {
        "mode": _unicommerce_mode(),
        "base_url": _cred("UNICOMMERCE_BASE_URL") or None,
        "tenant_set": bool(_cred("UNICOMMERCE_TENANT")),
        "api_user_set": bool(_cred("UNICOMMERCE_USER")),
        "supported_locations": sorted(VALID_FC_CODES),
        "note": "CSV upload is always available. Set UNICOMMERCE_MODE=live with credentials to enable API pull.",
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


@router.post("/pull")
async def pull_live(request: Request, location_code: str,
                    actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_WH_MANAGER))):
    """Live Unicommerce pull. Stub — enables when UNICOMMERCE_MODE=live and creds are set."""
    if location_code not in VALID_FC_CODES:
        raise HTTPException(400, "Invalid location_code")
    if _unicommerce_mode() != "live":
        raise HTTPException(503, "Unicommerce live mode is disabled. Use /fc-sync/csv or set UNICOMMERCE_MODE=live with credentials.")
    # TODO: real client — will map to Unicommerce inventory endpoint here.
    return {"status": "not_implemented", "location_code": location_code,
            "note": "Unicommerce API client will be added when creds are provided."}
