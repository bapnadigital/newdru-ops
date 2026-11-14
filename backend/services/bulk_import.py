"""Bulk-import helper for warehouse ingest + capacity analysis.

Used by POST /api/inventory/bulk-import (owner-only) to seed / overwrite
Bhiwandi (or any editable location) stock in one shot from a structured
payload — e.g. an Excel-derived inventory list.

Also exposes ``compute_capacity`` which turns the ingested rows into
a floor-area estimate so we can answer "does this fit in 1000 sqft?".
"""
from __future__ import annotations
import re
import unicodedata
from typing import Optional, List, Dict, Any

from models import gen_id, now_iso, LOCATIONS


# ---------- helpers ---------------------------------------------------------

_SKU_STRIP_RE = re.compile(r"[^A-Z0-9]+")


def slug_sku(name: str, prefix: Optional[str] = None) -> str:
    """Turn a product name into a stable SKU. Uppercase alnum + dashes,
    optionally prefixed with a shipping-mark to keep families together."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.upper()
    s = re.sub(r"[^A-Z0-9]+", "-", s).strip("-")
    if prefix:
        p = prefix.upper().strip()
        p = re.sub(r"[^A-Z0-9]+", "", p)
        if not s.startswith(p):
            s = f"{p}-{s}" if s else p
    return s[:60] or "ITEM"


def carton_volume_cm3(dims: Optional[Dict[str, Any]]) -> float:
    if not dims:
        return 0.0
    L = float(dims.get("length_cm") or 0)
    W = float(dims.get("width_cm") or 0)
    H = float(dims.get("height_cm") or 0)
    return L * W * H


def compute_capacity(items: List[Dict[str, Any]],
                     stack_height_m: float = 2.4,
                     aisle_factor: float = 1.6) -> Dict[str, Any]:
    """Given the ingest lines, compute cubic + floor-area requirements.

    - stack_height_m: how tall we can stack cartons safely (default 8 ft).
    - aisle_factor:   multiplier for aisles / turning space (default 60% overhead).

    A 1000 sqft = 92.9 m² warehouse footprint reference is included in the
    output for the user to see how close they are.
    """
    per_sku = []
    total_units = 0
    total_cartons = 0.0
    total_carton_vol_cm3 = 0.0
    unpriced_dim_skus: List[str] = []

    for it in items:
        qty = int(it.get("quantity") or 0)
        upc = int(it.get("units_per_carton") or 1) or 1
        cartons = qty / upc  # fractional cartons OK for planning
        dims = it.get("carton_dimensions") or {}
        vol_cm3 = carton_volume_cm3(dims)
        line_vol_cm3 = vol_cm3 * cartons
        if vol_cm3 == 0 and qty > 0:
            unpriced_dim_skus.append(it.get("sku") or it.get("name") or "?")
        total_units += qty
        total_cartons += cartons
        total_carton_vol_cm3 += line_vol_cm3
        per_sku.append({
            "sku": it.get("sku"),
            "name": it.get("name"),
            "quantity": qty,
            "units_per_carton": upc,
            "cartons": round(cartons, 2),
            "carton_dims_cm": {
                "length": dims.get("length_cm"),
                "width": dims.get("width_cm"),
                "height": dims.get("height_cm"),
            },
            "carton_volume_m3": round(vol_cm3 / 1_000_000, 4),
            "line_volume_m3": round(line_vol_cm3 / 1_000_000, 4),
        })

    total_vol_m3 = total_carton_vol_cm3 / 1_000_000
    # Floor area needed at given stack height (m²)
    floor_m2_bare = (total_vol_m3 / stack_height_m) if stack_height_m else 0.0
    floor_m2_with_aisle = floor_m2_bare * aisle_factor
    floor_sqft = floor_m2_with_aisle * 10.7639

    warehouse_1000sqft_m2 = 1000 / 10.7639  # 92.903 m²
    fits = floor_m2_with_aisle <= warehouse_1000sqft_m2
    utilization_pct = (floor_m2_with_aisle / warehouse_1000sqft_m2) * 100

    return {
        "assumptions": {
            "stack_height_m": stack_height_m,
            "aisle_factor": aisle_factor,
            "warehouse_ref_sqft": 1000,
            "warehouse_ref_m2": round(warehouse_1000sqft_m2, 2),
        },
        "totals": {
            "sku_count": len(items),
            "total_units": total_units,
            "total_cartons": round(total_cartons, 2),
            "total_volume_m3": round(total_vol_m3, 3),
            "floor_area_bare_m2": round(floor_m2_bare, 2),
            "floor_area_with_aisle_m2": round(floor_m2_with_aisle, 2),
            "floor_area_with_aisle_sqft": round(floor_sqft, 0),
            "utilization_of_1000sqft_pct": round(utilization_pct, 1),
            "fits_in_1000sqft": bool(fits),
        },
        "skus_missing_carton_dims": unpriced_dim_skus,
        "per_sku": per_sku,
    }


# ---------- DB writer -------------------------------------------------------

async def apply_bulk_import(
    db, actor: dict,
    items: List[Dict[str, Any]],
    target_location: str,
    mode: str = "set",  # 'set' (overwrite absolute qty) | 'add' (increment)
    auto_create_products: bool = True,
) -> Dict[str, Any]:
    """Ingest items into the given editable location.

    Each item shape:
    {
      "sku": "...",            # required (auto-generated if missing but name given)
      "name": "...",           # required for auto-create
      "quantity": 100,         # absolute qty for 'set' mode, delta for 'add'
      "units_per_carton": 24,
      "carton_dimensions": {"length_cm":..,"width_cm":..,"height_cm":..},
      "carton_weight_g": 20000,
      "brand": "Newdru",
      "category": "...",
      "shipping_mark": "BAPNA",
      "buy_price": 0, "sell_price": 0, "mrp": 0
    }
    """
    loc = next((l for l in LOCATIONS if l["code"] == target_location), None)
    if not loc or not loc["editable"]:
        raise ValueError(f"Location {target_location} is not editable")

    created_products: List[Dict[str, str]] = []
    updated_products: List[Dict[str, str]] = []
    stock_updates: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    now = now_iso()

    for raw in items:
        try:
            name = (raw.get("name") or "").strip()
            sku = (raw.get("sku") or "").strip()
            if not sku and name:
                sku = slug_sku(name, prefix=raw.get("shipping_mark"))
            if not sku:
                errors.append({"item": str(raw)[:120], "error": "missing sku/name"})
                continue

            product = await db.products.find_one({"sku": sku}, {"_id": 0})
            if product is None:
                if not auto_create_products:
                    errors.append({"sku": sku, "error": "unknown SKU, auto-create disabled"})
                    continue
                if not name:
                    name = sku
                doc = {
                    "id": gen_id(),
                    "sku": sku,
                    "name": name,
                    "brand": raw.get("brand") or "Newdru",
                    "category": raw.get("category"),
                    "variant": raw.get("variant"),
                    "mrp": float(raw.get("mrp") or 0.0),
                    "gst_rate": float(raw.get("gst_rate") or 18.0),
                    "hsn": raw.get("hsn"),
                    "images": [],
                    "channel_scope": "offline_only",
                    "status": "active",
                    "barcode": sku,
                    "barcode_type": "CODE128",
                    "buy_price": float(raw.get("buy_price") or 0.0),
                    "sell_price": float(raw.get("sell_price") or 0.0),
                    "units_per_carton": int(raw.get("units_per_carton") or 1),
                    "carton_weight_g": raw.get("carton_weight_g"),
                    "carton_dimensions": raw.get("carton_dimensions"),
                    "shipping_mark": raw.get("shipping_mark"),
                    "created_at": now, "updated_at": now,
                    "placeholder_pricing": True,   # flag so UI can highlight
                }
                await db.products.insert_one(doc)
                product = doc
                created_products.append({"sku": sku, "name": name})
            else:
                # Update packaging + shipping-mark info if provided,
                # but do NOT overwrite existing pricing.
                patch: Dict[str, Any] = {"updated_at": now}
                for k in ("units_per_carton", "carton_weight_g",
                          "carton_dimensions", "shipping_mark",
                          "brand", "category", "variant", "hsn"):
                    if raw.get(k) is not None:
                        patch[k] = raw[k]
                if len(patch) > 1:
                    await db.products.update_one({"id": product["id"]}, {"$set": patch})
                updated_products.append({"sku": sku, "name": product.get("name")})

            # ---- stock write ----
            qty = int(raw.get("quantity") or 0)
            existing_inv = await db.inventory.find_one(
                {"product_id": product["id"], "location_code": target_location}
            )
            current_qty = int((existing_inv or {}).get("quantity", 0))

            if mode == "set":
                new_qty = qty
                delta = qty - current_qty
            else:  # 'add'
                delta = qty
                new_qty = current_qty + qty

            await db.inventory.update_one(
                {"product_id": product["id"], "location_code": target_location},
                {"$set": {"quantity": new_qty, "last_synced_at": now},
                 "$setOnInsert": {"id": gen_id(), "low_stock_threshold": 5}},
                upsert=True,
            )
            if delta != 0:
                await db.stock_movements.insert_one({
                    "id": gen_id(),
                    "product_id": product["id"],
                    "sku": product["sku"],
                    "location_code": target_location,
                    "movement_type": "bulk_import",
                    "quantity_delta": delta,
                    "reason": "bulk warehouse ingest",
                    "reference_id": raw.get("reference"),
                    "user_id": (actor or {}).get("id"),
                    "user_name": (actor or {}).get("name"),
                    "created_at": now,
                })
            stock_updates.append({
                "sku": product["sku"],
                "name": product["name"],
                "previous_qty": current_qty,
                "new_qty": new_qty,
                "delta": delta,
            })
        except Exception as ex:  # keep the batch resilient
            errors.append({"item": raw.get("sku") or raw.get("name") or "?",
                           "error": str(ex)[:200]})

    capacity = compute_capacity(items)

    return {
        "target_location": target_location,
        "mode": mode,
        "created_products": created_products,
        "updated_products": updated_products,
        "stock_updates": stock_updates,
        "errors": errors,
        "capacity_analysis": capacity,
    }
