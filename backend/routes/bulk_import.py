"""Bulk warehouse ingest endpoints.

- POST /api/inventory/bulk-import  → owner-only, seeds/overwrites stock for
  a target location and returns a capacity report.
- POST /api/inventory/capacity-estimate → cost-free planning helper that
  computes cubic + floor-area needs for a hypothetical list (no DB writes).
"""
from __future__ import annotations
from typing import List, Optional, Literal, Dict, Any
from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from models import ROLE_OWNER, LOC_BHIWANDI, _blank_to_none
from auth import require_roles, audit
from services.bulk_import import apply_bulk_import, compute_capacity


router = APIRouter(prefix="/inventory", tags=["inventory"])


class CartonDims(BaseModel):
    length_cm: Optional[float] = None
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None


class BulkImportItem(BaseModel):
    sku: Optional[str] = None
    name: Optional[str] = None
    shipping_mark: Optional[str] = None
    quantity: int = 0
    units_per_carton: int = 1
    carton_dimensions: Optional[CartonDims] = None
    carton_weight_g: Optional[float] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    variant: Optional[str] = None
    buy_price: Optional[float] = None
    sell_price: Optional[float] = None
    mrp: Optional[float] = None
    hsn: Optional[str] = None
    reference: Optional[str] = None

    _norm = field_validator(
        "sku", "name", "shipping_mark", "brand", "category",
        "variant", "hsn", "reference", mode="before"
    )(lambda cls, v: _blank_to_none(v))


class BulkImportBody(BaseModel):
    target_location: str = LOC_BHIWANDI
    mode: Literal["set", "add"] = "set"
    auto_create_products: bool = True
    stack_height_m: float = 2.4
    aisle_factor: float = 1.6
    items: List[BulkImportItem] = Field(default_factory=list)


@router.post("/bulk-import")
async def bulk_import(
    body: BulkImportBody, request: Request,
    actor: dict = Depends(require_roles(ROLE_OWNER)),
):
    if not body.items:
        raise HTTPException(400, "No items to import.")
    db = request.app.state.db
    payload = [i.model_dump() for i in body.items]
    try:
        result = await apply_bulk_import(
            db, actor, payload,
            target_location=body.target_location,
            mode=body.mode,
            auto_create_products=body.auto_create_products,
        )
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    # Recompute capacity with the caller-provided stacking assumptions
    result["capacity_analysis"] = compute_capacity(
        payload,
        stack_height_m=body.stack_height_m,
        aisle_factor=body.aisle_factor,
    )
    await audit(db, actor, "inventory.bulk_import", "inventory", None, {
        "target": body.target_location,
        "mode": body.mode,
        "sku_count": len(payload),
        "created": len(result["created_products"]),
        "updated": len(result["updated_products"]),
    })
    return result


@router.post("/capacity-estimate")
async def capacity_estimate(
    body: BulkImportBody, request: Request,
    actor: dict = Depends(require_roles(ROLE_OWNER)),
):
    """No-DB-write planning helper: cubic + floor-area estimate only."""
    payload = [i.model_dump() for i in body.items]
    return compute_capacity(
        payload,
        stack_height_m=body.stack_height_m,
        aisle_factor=body.aisle_factor,
    )
