"""Dashboards & reports (Owner-focused, exportable to CSV)."""
import csv, io
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse
from typing import Optional

from models import LOCATIONS, ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER
from auth import get_current_user, require_roles, can_see_cost, log_export
from security import safe_csv_writer, SafeDictWriter

router = APIRouter(prefix="/reports", tags=["reports"])


def _iso_day_start() -> str:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


@router.get("/dashboard")
async def dashboard(request: Request, user: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    day_start = _iso_day_start()
    sales_today = await db.sales.find({"created_at": {"$gte": day_start}}, {"_id": 0}).to_list(5000)
    total_sales = sum(float(s.get("total", 0)) for s in sales_today)
    order_count = len(sales_today)
    by_method: dict = {"cash": 0.0, "card": 0.0, "upi": 0.0}
    top_skus: dict = {}
    for s in sales_today:
        for p in s.get("payments", []):
            by_method[p["method"]] = by_method.get(p["method"], 0) + float(p["amount"])
        for it in s.get("items", []):
            top_skus.setdefault(it["sku"], {"name": it["name"], "qty": 0, "revenue": 0.0})
            top_skus[it["sku"]]["qty"] += int(it["quantity"])
            top_skus[it["sku"]]["revenue"] += float(it.get("line_total") or 0)
    top_list = sorted(
        [{"sku": k, **v} for k, v in top_skus.items()],
        key=lambda x: x["revenue"], reverse=True,
    )[:8]

    refunds_today = await db.sales_returns.find({"created_at": {"$gte": day_start}},
                                                {"_id": 0, "refund_total": 1}).to_list(5000)
    refunds_total = round(sum(float(r.get("refund_total", 0)) for r in refunds_today), 2)

    last_close = await db.cash_closings.find_one({}, {"_id": 0, "created_at": 1, "difference": 1, "by_name": 1,
                                                      "expected": 1, "counted_cash": 1}, sort=[("created_at", -1)])
    pending_counts = await db.stock_counts.count_documents({"status": "pending"})

    new_customers = await db.customers.count_documents({"first_seen": {"$gte": day_start}})

    inv = await db.inventory.find({}, {"_id": 0}).to_list(20000)
    low_stock_count = sum(
        1 for r in inv
        if int(r.get("quantity", 0)) <= int(r.get("low_stock_threshold", 5))
    )

    include_cost = can_see_cost(user)
    inv_value_by_loc: dict = {l["code"]: {"name": l["name"], "value": 0.0, "units": 0} for l in LOCATIONS}
    if include_cost:
        products = {p["id"]: p for p in await db.products.find({}, {"_id": 0}).to_list(5000)}
        for r in inv:
            p = products.get(r["product_id"])
            if not p: continue
            qty = int(r.get("quantity", 0))
            inv_value_by_loc[r["location_code"]]["units"] += qty
            inv_value_by_loc[r["location_code"]]["value"] += qty * float(p.get("buy_price") or 0)
        for k in inv_value_by_loc:
            inv_value_by_loc[k]["value"] = round(inv_value_by_loc[k]["value"], 2)
    else:
        for r in inv:
            inv_value_by_loc[r["location_code"]]["units"] += int(r.get("quantity", 0))

    return {
        "today_sales_total": round(total_sales, 2),
        "today_order_count": order_count,
        "today_refunds_total": refunds_total,
        "today_refund_count": len(refunds_today),
        "today_net_sales": round(total_sales - refunds_total, 2),
        "last_cash_close": last_close,
        "pending_stock_counts": pending_counts,
        "by_method": {k: round(v, 2) for k, v in by_method.items()},
        "top_skus": top_list,
        "new_customers_today": new_customers,
        "low_stock_count": low_stock_count,
        "inventory_value_by_location": inv_value_by_loc,
        "cost_visible": include_cost,
    }


@router.get("/sales")
async def sales_report(
    request: Request,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER)),
):
    db = request.app.state.db
    q: dict = {}
    if from_date or to_date:
        q["created_at"] = {}
        if from_date: q["created_at"]["$gte"] = from_date
        if to_date: q["created_at"]["$lte"] = to_date
    sales = await db.sales.find(q, {"_id": 0}).sort("created_at", -1).to_list(5000)
    subtotal = sum(s.get("subtotal", 0) for s in sales)
    tax_total = sum(s.get("tax_total", 0) for s in sales)
    total = sum(s.get("total", 0) for s in sales)
    gst_breakup: dict = {}
    for s in sales:
        for k, v in (s.get("gst_breakup") or {}).items():
            gst_breakup.setdefault(k, {"taxable": 0.0, "tax": 0.0})
            gst_breakup[k]["taxable"] += float(v.get("taxable", 0))
            gst_breakup[k]["tax"] += float(v.get("tax", 0))
    for k in gst_breakup:
        gst_breakup[k]["taxable"] = round(gst_breakup[k]["taxable"], 2)
        gst_breakup[k]["tax"] = round(gst_breakup[k]["tax"], 2)
    # Credit notes (returns) in the same period, so GST can be filed net.
    notes = await db.sales_returns.find(q, {"_id": 0, "refund_total": 1, "gst_breakup": 1}).to_list(5000)
    cn_total = round(sum(float(n.get("refund_total") or 0) for n in notes), 2)
    cn_tax = round(sum(float(g.get("tax") or 0) for n in notes for g in (n.get("gst_breakup") or {}).values()), 2)
    return {
        "credit_notes": {"count": len(notes), "total": cn_total, "tax": cn_tax},
        "net_total": round(total - cn_total, 2),
        "net_tax": round(tax_total - cn_tax, 2),
        "count": len(sales),
        "subtotal": round(subtotal, 2),
        "tax_total": round(tax_total, 2),
        "total": round(total, 2),
        "gst_breakup": gst_breakup,
        "sales": sales[:1000],
    }


@router.get("/sales/csv", dependencies=[Depends(log_export("sales"))])
async def sales_csv(
    request: Request,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER)),
):
    db = request.app.state.db
    q: dict = {}
    if from_date or to_date:
        q["created_at"] = {}
        if from_date: q["created_at"]["$gte"] = from_date
        if to_date: q["created_at"]["$lte"] = to_date
    sales = await db.sales.find(q, {"_id": 0}).sort("created_at", -1).to_list(20000)
    output = io.StringIO()
    w = safe_csv_writer(output)
    w.writerow(["Invoice", "Date", "Cashier", "Customer", "Payment", "Subtotal", "Tax", "Discount", "Total"])
    for s in sales:
        w.writerow([s.get("invoice_no"), s.get("created_at"), s.get("cashier_name"),
                    s.get("customer_name") or "", s.get("payment_method_summary"),
                    s.get("subtotal"), s.get("tax_total"), s.get("cart_discount"),
                    s.get("total")])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=sales_report.csv"})


@router.get("/returns/csv", dependencies=[Depends(log_export("credit_notes"))])
async def returns_csv(request: Request, from_date: Optional[str] = None, to_date: Optional[str] = None,
                      user: dict = Depends(require_roles(ROLE_OWNER))):
    """Credit notes for GST returns: one row per GST rate per credit note."""
    db = request.app.state.db
    q: dict = {}
    if from_date or to_date:
        q["created_at"] = {}
        if from_date: q["created_at"]["$gte"] = from_date
        if to_date: q["created_at"]["$lte"] = to_date
    notes = await db.sales_returns.find(q, {"_id": 0}).sort("created_at", 1).to_list(20000)
    output = io.StringIO()
    w = safe_csv_writer(output)
    w.writerow(["Credit note", "Date", "Against invoice", "Customer", "GST rate %", "Taxable value",
                "GST", "Refund total (note)", "Refund method", "Reason", "By"])
    for n in notes:
        for rate, g in sorted((n.get("gst_breakup") or {"0": {"taxable": n.get("refund_total"), "tax": 0}}).items()):
            w.writerow([n.get("credit_note_no"), n.get("created_at"), n.get("invoice_no"), n.get("customer_name") or "",
                        rate, g.get("taxable"), g.get("tax"), n.get("refund_total"), n.get("refund_method"),
                        n.get("reason"), n.get("by_name")])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=credit_notes.csv"})


@router.get("/inventory/csv", dependencies=[Depends(log_export("inventory"))])
async def inventory_csv(
    request: Request,
    user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_WH_MANAGER)),
):
    db = request.app.state.db
    products = await db.products.find({}, {"_id": 0}).to_list(20000)
    inv = await db.inventory.find({}, {"_id": 0}).to_list(50000)
    inv_map: dict = {}
    for r in inv:
        inv_map.setdefault(r["product_id"], {})[r["location_code"]] = r
    output = io.StringIO()
    w = safe_csv_writer(output)
    header = ["SKU", "Name", "Brand", "Category", "Barcode"] + [l["name"] for l in LOCATIONS] + ["Total"]
    w.writerow(header)
    for p in products:
        pinv = inv_map.get(p["id"], {})
        row = [p.get("sku"), p.get("name"), p.get("brand", ""), p.get("category", ""), p.get("barcode", "")]
        total = 0
        for l in LOCATIONS:
            q = int(pinv.get(l["code"], {}).get("quantity", 0))
            row.append(q); total += q
        row.append(total)
        w.writerow(row)
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=inventory_report.csv"})


@router.get("/audit")
async def audit_log(request: Request, limit: int = 200, area: Optional[str] = None,
                    user_name: Optional[str] = None, from_date: Optional[str] = None,
                    to_date: Optional[str] = None,
                    user: dict = Depends(require_roles(ROLE_OWNER))):
    """Owner's activity log. area = export | sale | inventory | transfer | product | user | login | ..."""
    import re as _re
    db = request.app.state.db
    q: dict = {}
    if area:
        a = _re.sub(r"[^a-z_]", "", area.lower())[:30]
        if a == "login":
            q["action"] = {"$in": ["login", "logout", "admin.override_verify"]}
        elif a:
            q["action"] = {"$regex": f"^{a}\\."}
    if user_name:
        q["user_name"] = {"$regex": _re.escape(user_name.strip()[:60]), "$options": "i"}
    if from_date or to_date:
        q["created_at"] = {}
        if from_date: q["created_at"]["$gte"] = from_date
        if to_date: q["created_at"]["$lte"] = to_date
    limit = max(1, min(int(limit), 1000))
    docs = await db.audit_logs.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return docs
