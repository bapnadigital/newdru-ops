"""Barcode label PDF generation."""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse
import io

from auth import require_roles, audit
from models import ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER, ROLE_WH_STAFF
from services.labels import build_labels_pdf

router = APIRouter(prefix="/labels", tags=["labels"])


@router.post("/pdf")
async def labels_pdf(body: dict, request: Request,
                     actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER, ROLE_WH_STAFF))):
    """body: {items: [{product_id, count}], label_w_mm, label_h_mm}"""
    db = request.app.state.db
    items = body.get("items") or []
    if not items: raise HTTPException(400, "No items provided")
    labels = []
    for it in items:
        p = await db.products.find_one({"id": it.get("product_id")}, {"_id": 0})
        if not p: continue
        labels.append({
            "name": p["name"], "mrp": p.get("mrp"), "sell_price": p.get("sell_price"),
            "barcode": p.get("barcode"), "sku": p.get("sku"),
            "count": int(it.get("count") or 1),
        })
    pdf_bytes = build_labels_pdf(
        labels,
        label_width_mm=float(body.get("label_w_mm") or body.get("label_width_mm") or 50),
        label_height_mm=float(body.get("label_h_mm") or body.get("label_height_mm") or 30),
    )
    await audit(db, actor, "label.print", "label", None, {"items": len(labels)})
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf",
                             headers={"Content-Disposition": "attachment; filename=labels.pdf"})
