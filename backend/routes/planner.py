"""Box-Fit / Shipment planner — EXACT formulas per Newdru spec.

Let U = units_per_carton, W = carton_weight_kg, dims L×B×H cm, Q = quantity to ship.

  units_per_box      = U
  total_boxes        = ceil(Q / U)
  full_boxes         = floor(Q / U)
  loose_units        = Q - full_boxes * U
  unit_weight_kg     = W / U
  weight_per_box_kg  = W
  total_weight_kg    = round(Q * unit_weight_kg, 2)          ← Q × unit weight, NOT total_boxes × W
  carton_volume_cft  = (L·B·H) / 28316.8
  carton_volume_cbm  = (L·B·H) / 1_000_000
  total_volume_cft   = round(total_boxes * carton_volume_cft, 2)  ← whole boxes are shipped
  total_volume_cbm   = round(total_boxes * carton_volume_cbm, 3)

  stock check = warehouse (Bhiwandi) available vs Q → "YES" or "SHORT by N"

Guard when U == 0 / missing packaging.
"""
from __future__ import annotations
import math
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Depends, Query

from models import ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER, LOC_BHIWANDI
from auth import require_roles


router = APIRouter(prefix="/planner", tags=["planner"])

CM3_PER_CFT = 28316.8
CM3_PER_CBM = 1_000_000


@router.get("/box-fit")
async def box_fit(
    request: Request,
    product_id: str = Query(..., description="Product ID or SKU"),
    quantity: int = Query(..., gt=0, description="Units to ship"),
    location_code: str = Query(LOC_BHIWANDI, description="Stock location to check"),
    actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER, "warehouse_staff")),
):
    db = request.app.state.db
    prod = await db.products.find_one(
        {"$or": [{"id": product_id}, {"sku": product_id}]}, {"_id": 0}
    )
    if not prod:
        raise HTTPException(404, "Product not found")

    U = int(prod.get("units_per_carton") or 0)
    dims = prod.get("carton_dimensions") or {}
    L = float(dims.get("length_cm") or 0)
    B = float(dims.get("width_cm") or 0)
    H = float(dims.get("height_cm") or 0)
    W_g = prod.get("carton_weight_g")
    W_kg: Optional[float] = round(W_g / 1000, 4) if W_g else None
    fnsku = prod.get("amazon_fnsku") or (
        prod.get("barcode") if prod.get("barcode_type") == "FNSKU" else None
    )

    warnings = []
    if U <= 0:
        warnings.append("Packaging not set — please add units per carton on the Products screen.")
    if not (L and B and H):
        warnings.append("Carton dimensions missing — volume totals cannot be computed.")
    if W_kg is None:
        warnings.append("Carton weight missing — weight totals cannot be computed.")
    if not fnsku:
        warnings.append("No FNSKU set on this product — required for Amazon shipments.")

    Q = int(quantity)
    computation: dict = {"quantity_requested": Q}

    if U > 0:
        total_boxes = math.ceil(Q / U)
        full_boxes  = Q // U
        loose_units = Q - full_boxes * U
        computation.update({
            "units_per_box": U,
            "full_boxes":   full_boxes,
            "loose_units":  loose_units,
            "total_boxes":  total_boxes,
        })
        if W_kg is not None:
            unit_weight_kg = W_kg / U
            total_weight_kg = round(Q * unit_weight_kg, 2)
            computation.update({
                "unit_weight_kg":     round(unit_weight_kg, 4),
                "weight_per_box_kg":  round(W_kg, 3),
                "gross_weight_per_box_kg": round(W_kg, 3),  # legacy field name (kept)
                "total_weight_kg":    total_weight_kg,
                "total_gross_weight_kg": total_weight_kg,   # legacy field name (kept)
            })
        if L and B and H:
            carton_vol_cm3 = L * B * H
            carton_volume_cft = carton_vol_cm3 / CM3_PER_CFT
            carton_volume_cbm = carton_vol_cm3 / CM3_PER_CBM
            total_volume_cft = round(total_boxes * carton_volume_cft, 2)
            total_volume_cbm = round(total_boxes * carton_volume_cbm, 3)
            computation.update({
                "carton_volume_cft":   round(carton_volume_cft, 4),
                "carton_volume_cbm":   round(carton_volume_cbm, 5),
                "volume_per_box_cft":  round(carton_volume_cft, 3),   # legacy
                "volume_per_box_cbm":  round(carton_volume_cbm, 4),   # legacy
                "total_volume_cft":    total_volume_cft,
                "total_volume_cbm":    total_volume_cbm,
            })

    inv = await db.inventory.find_one(
        {"product_id": prod["id"], "location_code": location_code}, {"_id": 0}
    )
    available = int((inv or {}).get("quantity", 0))
    shortage = max(0, Q - available)
    stock = {
        "location_code": location_code,
        "available": available,
        "requested": Q,
        "has_enough": shortage == 0,
        "shortage": shortage,
        "verdict": "YES" if shortage == 0 else f"SHORT by {shortage}",
    }

    return {
        "product": {
            "id": prod["id"],
            "sku": prod["sku"],
            "name": prod.get("name"),
            "variant": prod.get("variant"),
            "shipping_mark": prod.get("shipping_mark"),
            "fnsku": fnsku,
            "amazon_asin": prod.get("amazon_asin"),
            "amazon_msku": prod.get("amazon_msku"),
            "barcode": prod.get("barcode"),
            "barcode_type": prod.get("barcode_type"),
            "notes": prod.get("notes"),
        },
        "packaging": {
            "units_per_carton":   U if U > 0 else None,
            "carton_length_cm":   L or None,
            "carton_width_cm":    B or None,
            "carton_height_cm":   H or None,
            "carton_weight_kg":   W_kg,
            "unit_weight_g":      prod.get("unit_weight_g"),
        },
        "computation": computation,
        "stock":       stock,
        "warnings":    warnings,
    }
