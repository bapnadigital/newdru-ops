"""B2B / wholesale orders + collections dashboard.

- Wholesale customers have credit_limit, payment_terms_days, gstin, outstanding.
- Orders lifecycle: draft -> confirmed -> dispatched -> invoiced -> partially_paid | paid | cancelled
- Payments logged against invoices; outstanding is recomputed.
- Collections dashboard: aging buckets 0-30 / 31-60 / 61-90 / 90+.
"""
from __future__ import annotations
import re
import io
import csv
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Literal
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field, field_validator

from models import (
    gen_id, now_iso, ROLE_OWNER, ROLE_STORE_MANAGER, LOC_BHIWANDI, LOC_STORE,
    _blank_to_none,
)
from auth import get_current_user, require_roles, audit
from security import safe_csv_writer, SafeDictWriter
from routes.inventory import _apply_delta, _write_movement

router = APIRouter(prefix="/b2b", tags=["b2b"],
                   dependencies=[Depends(require_roles(ROLE_OWNER))])  # owner-only, matches the UI


# ============================================================
# Wholesale customer
# ============================================================
class B2BCustomerCreate(BaseModel):
    name: str
    company: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    gstin: Optional[str] = None
    address: Optional[str] = None
    credit_limit: float = 0.0
    payment_terms_days: int = 30
    tags: List[str] = []

    _norm_blanks = field_validator(
        "company", "phone", "email", "gstin", "address", mode="before"
    )(lambda cls, v: _blank_to_none(v))


class B2BCustomerUpdate(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    gstin: Optional[str] = None
    address: Optional[str] = None
    credit_limit: Optional[float] = None
    payment_terms_days: Optional[int] = None
    active: Optional[bool] = None
    tags: Optional[List[str]] = None

    _norm_blanks = field_validator(
        "name", "company", "phone", "email", "gstin", "address", mode="before"
    )(lambda cls, v: _blank_to_none(v))


@router.get("/customers")
async def list_b2b_customers(request: Request, q: Optional[str] = None,
                             user: dict = Depends(get_current_user)):
    db = request.app.state.db
    query: dict = {"customer_type": "wholesale"}
    if q:
        query["$or"] = [
            {"name": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"company": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"phone": {"$regex": re.escape(q[:64]), "$options": "i"}},
            {"gstin": {"$regex": re.escape(q[:64]), "$options": "i"}},
        ]
    return await db.customers.find(query, {"_id": 0}).sort("name", 1).to_list(1000)


@router.post("/customers")
async def create_b2b_customer(body: B2BCustomerCreate, request: Request,
                              actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    if body.phone:
        existing = await db.customers.find_one({"phone": body.phone, "customer_type": "wholesale"})
        if existing:
            raise HTTPException(400, "Wholesale customer with this phone already exists.")
    doc = {
        "id": gen_id(),
        "customer_type": "wholesale",
        "channel": "wholesale",
        **body.model_dump(),
        "active": True,
        "outstanding": 0.0,
        "total_spend": 0.0, "order_count": 0, "avg_order_value": 0.0,
        "first_seen": now_iso(), "last_seen": now_iso(),
    }
    await db.customers.insert_one(doc)
    await audit(db, actor, "b2b.customer.create", "customer", doc["id"], {"name": body.name})
    doc.pop("_id", None)
    return doc


@router.patch("/customers/{cid}")
async def update_b2b_customer(cid: str, body: B2BCustomerUpdate, request: Request,
                              actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    updates = body.model_dump(exclude_none=True)
    if not updates: raise HTTPException(400, "Nothing to update")
    r = await db.customers.update_one({"id": cid, "customer_type": "wholesale"}, {"$set": updates})
    if r.matched_count == 0: raise HTTPException(404, "Not found")
    await audit(db, actor, "b2b.customer.update", "customer", cid, {"fields": list(updates)})
    return await db.customers.find_one({"id": cid}, {"_id": 0})


# ============================================================
# Orders
# ============================================================
OrderStatus = Literal["draft", "confirmed", "dispatched", "invoiced", "partially_paid", "paid", "cancelled"]


class B2BOrderLine(BaseModel):
    product_id: str
    sku: str
    name: str
    hsn: Optional[str] = None
    gst_rate: float = 18.0
    quantity: int
    unit_price: float           # GST-INCLUSIVE
    discount: float = 0.0       # amount (INCLUSIVE)


class B2BPayment(BaseModel):
    method: Literal["cash", "card", "upi", "bank_transfer", "cheque"] = "bank_transfer"
    amount: float
    reference: Optional[str] = None
    received_at: Optional[str] = None


class B2BOrderCreate(BaseModel):
    customer_id: str
    po_reference: Optional[str] = None
    lines: List[B2BOrderLine]
    cart_discount: float = 0.0
    ship_from: Literal["STORE", "BHIWANDI"] = "BHIWANDI"
    payment_terms_days: Optional[int] = None
    notes: Optional[str] = None


def _compute_totals(lines: List[B2BOrderLine], cart_discount: float):
    subtotal_ex = 0.0
    tax_total = 0.0
    breakup: dict = {}
    processed = []
    for it in lines:
        gross = max(0.0, it.unit_price * it.quantity - it.discount)
        rate = it.gst_rate or 0
        ex = gross / (1 + rate / 100) if (1 + rate / 100) > 0 else gross
        tax = gross - ex
        processed.append({**it.model_dump(),
                          "line_subtotal": round(ex, 2),
                          "tax_amount": round(tax, 2),
                          "line_total": round(gross, 2)})
        subtotal_ex += ex; tax_total += tax
        k = f"{rate:.2f}"
        breakup.setdefault(k, {"taxable": 0.0, "tax": 0.0})
        breakup[k]["taxable"] += ex; breakup[k]["tax"] += tax
    total_gross = subtotal_ex + tax_total
    cart_disc = min(max(0.0, cart_discount), total_gross)
    total = total_gross - cart_disc
    if total_gross > 0 and cart_disc > 0:
        ratio = total / total_gross
        subtotal_ex *= ratio; tax_total *= ratio
        for k in breakup:
            breakup[k]["taxable"] = round(breakup[k]["taxable"] * ratio, 2)
            breakup[k]["tax"] = round(breakup[k]["tax"] * ratio, 2)
    return {
        "items": processed,
        "subtotal": round(subtotal_ex, 2),
        "tax_total": round(tax_total, 2),
        "cart_discount": round(cart_disc, 2),
        "total": round(total, 2),
        "gst_breakup": breakup,
    }


async def _next_order_no(db) -> str:
    yr = datetime.now(timezone.utc).strftime("%y")
    c = await db.counters.find_one_and_update(
        {"_id": f"b2b_order_{yr}"}, {"$inc": {"seq": 1}},
        upsert=True, return_document=True,
    )
    seq = (c or {}).get("seq", 1)
    return f"WO-{yr}-{seq:05d}"


async def _next_invoice_no(db) -> str:
    yr = datetime.now(timezone.utc).strftime("%y")
    c = await db.counters.find_one_and_update(
        {"_id": f"b2b_invoice_{yr}"}, {"$inc": {"seq": 1}},
        upsert=True, return_document=True,
    )
    seq = (c or {}).get("seq", 1)
    return f"WI-{yr}-{seq:05d}"


@router.get("/orders")
async def list_orders(request: Request, status: Optional[str] = None,
                      customer_id: Optional[str] = None, limit: int = 200,
                      user: dict = Depends(get_current_user)):
    db = request.app.state.db
    q: dict = {}
    if status: q["status"] = status
    if customer_id: q["customer_id"] = customer_id
    return await db.b2b_orders.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)


@router.post("/orders")
async def create_order(body: B2BOrderCreate, request: Request,
                       actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    cust = await db.customers.find_one({"id": body.customer_id, "customer_type": "wholesale"})
    if not cust: raise HTTPException(404, "Wholesale customer not found")
    if not cust.get("active", True): raise HTTPException(400, "Customer is disabled")

    calc = _compute_totals(body.lines, body.cart_discount)
    # Credit-limit guard
    projected_outstanding = float(cust.get("outstanding", 0.0)) + calc["total"]
    if cust.get("credit_limit", 0) and projected_outstanding > cust["credit_limit"]:
        raise HTTPException(400,
            f"Order exceeds credit limit. Outstanding after order would be ₹{projected_outstanding:.2f} "
            f"vs limit ₹{cust['credit_limit']:.2f}")

    terms = int(body.payment_terms_days or cust.get("payment_terms_days") or 30)
    now = now_iso()
    order_no = await _next_order_no(db)
    doc = {
        "id": gen_id(),
        "order_no": order_no,
        "customer_id": cust["id"],
        "customer_name": cust.get("company") or cust.get("name"),
        "customer_gstin": cust.get("gstin"),
        "po_reference": body.po_reference,
        "ship_from": body.ship_from,
        "items": calc["items"],
        "subtotal": calc["subtotal"], "tax_total": calc["tax_total"],
        "cart_discount": calc["cart_discount"], "total": calc["total"],
        "gst_breakup": calc["gst_breakup"],
        "payment_terms_days": terms,
        "status": "confirmed",
        "notes": body.notes,
        "invoice_no": None, "invoice_date": None, "due_date": None,
        "dispatched_at": None, "delivered_at": None,
        "paid_amount": 0.0, "outstanding": 0.0,
        "payments": [],
        "created_by": actor["id"],
        "created_at": now, "updated_at": now,
    }
    await db.b2b_orders.insert_one(doc)
    await audit(db, actor, "b2b.order.create", "b2b_order", doc["id"],
                {"order_no": order_no, "customer_id": cust["id"], "total": calc["total"]})
    doc.pop("_id", None)
    return doc


@router.post("/orders/{oid}/dispatch")
async def dispatch_order(oid: str, request: Request,
                          actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    o = await db.b2b_orders.find_one({"id": oid})
    if not o: raise HTTPException(404, "Not found")
    if o["status"] not in ("confirmed", "draft"):
        raise HTTPException(400, f"Cannot dispatch in status {o['status']}")

    # Decrement stock at ship_from
    ship_loc = o.get("ship_from", LOC_BHIWANDI)
    for it in o["items"]:
        product = await db.products.find_one({"id": it["product_id"]})
        if not product: continue
        qty = int(it["quantity"])
        await _apply_delta(db, it["product_id"], ship_loc, -qty)
        await _write_movement(db, actor, product, ship_loc, -qty, "b2b_dispatch",
                              reference_id=o["id"])

    dispatch_no = f"DN-{o['order_no']}"
    now = now_iso()
    await db.b2b_orders.update_one({"id": oid}, {"$set": {
        "status": "dispatched", "dispatched_at": now, "dispatch_no": dispatch_no, "updated_at": now,
    }})
    await audit(db, actor, "b2b.order.dispatch", "b2b_order", oid, {"dispatch_no": dispatch_no})
    return {"id": oid, "status": "dispatched", "dispatch_no": dispatch_no}


@router.post("/orders/{oid}/invoice")
async def raise_invoice(oid: str, request: Request,
                        actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    o = await db.b2b_orders.find_one({"id": oid})
    if not o: raise HTTPException(404, "Not found")
    if o["status"] not in ("dispatched", "confirmed"):
        raise HTTPException(400, f"Cannot invoice in status {o['status']}")
    if o.get("invoice_no"):
        return {"invoice_no": o["invoice_no"], "already_invoiced": True}

    inv = await _next_invoice_no(db)
    now = datetime.now(timezone.utc)
    due = now + timedelta(days=int(o.get("payment_terms_days") or 30))
    outstanding = float(o["total"]) - float(o.get("paid_amount") or 0)
    await db.b2b_orders.update_one({"id": oid}, {"$set": {
        "status": "invoiced" if outstanding > 0 else "paid",
        "invoice_no": inv, "invoice_date": now.isoformat(),
        "due_date": due.isoformat(),
        "outstanding": round(outstanding, 2), "updated_at": now.isoformat(),
    }})
    # Reflect outstanding on the customer
    await db.customers.update_one(
        {"id": o["customer_id"]},
        {"$inc": {"outstanding": round(outstanding, 2)}},
    )
    await audit(db, actor, "b2b.invoice.raise", "b2b_order", oid,
                {"invoice_no": inv, "outstanding": outstanding})
    return {"id": oid, "invoice_no": inv, "due_date": due.isoformat(), "outstanding": outstanding}


@router.post("/orders/{oid}/payments")
async def record_payment(oid: str, body: B2BPayment, request: Request,
                          actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    o = await db.b2b_orders.find_one({"id": oid})
    if not o: raise HTTPException(404, "Not found")
    if o["status"] not in ("invoiced", "partially_paid", "dispatched"):
        raise HTTPException(400, f"Cannot record payment in status {o['status']}")
    amt = round(float(body.amount), 2)
    if amt <= 0: raise HTTPException(400, "Amount must be > 0")
    outstanding_before = float(o.get("outstanding") or (o["total"] - (o.get("paid_amount") or 0)))
    if amt > outstanding_before + 0.05:
        raise HTTPException(400, f"Payment ({amt}) exceeds outstanding ({outstanding_before}).")

    now = now_iso()
    pmt = {
        "id": gen_id(),
        "method": body.method,
        "amount": amt,
        "reference": body.reference,
        "received_at": body.received_at or now,
        "recorded_by": actor["email"],
    }
    paid = round(float(o.get("paid_amount") or 0) + amt, 2)
    outstanding = round(float(o["total"]) - paid, 2)
    status = "paid" if outstanding <= 0.05 else "partially_paid"
    await db.b2b_orders.update_one({"id": oid}, {
        "$push": {"payments": pmt},
        "$set": {"paid_amount": paid, "outstanding": max(0.0, outstanding),
                 "status": status, "updated_at": now},
    })
    await db.customers.update_one({"id": o["customer_id"]}, {"$inc": {"outstanding": -amt}})
    await audit(db, actor, "b2b.payment.record", "b2b_order", oid,
                {"amount": amt, "method": body.method, "outstanding_after": outstanding})
    return {"id": oid, "paid_amount": paid, "outstanding": max(0.0, outstanding), "status": status}


@router.post("/orders/{oid}/cancel")
async def cancel_order(oid: str, request: Request,
                       actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    o = await db.b2b_orders.find_one({"id": oid})
    if not o: raise HTTPException(404, "Not found")
    if o["status"] in ("dispatched", "invoiced", "partially_paid", "paid"):
        raise HTTPException(400, "Cannot cancel once dispatched / invoiced. Raise a return instead.")
    await db.b2b_orders.update_one({"id": oid}, {"$set": {"status": "cancelled", "updated_at": now_iso()}})
    return {"id": oid, "status": "cancelled"}


# ============================================================
# Collections dashboard + reminders
# ============================================================
def _bucket_days(days: int) -> str:
    if days <= 30: return "0-30"
    if days <= 60: return "31-60"
    if days <= 90: return "61-90"
    return "90+"


@router.get("/collections/dashboard")
async def collections_dashboard(request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    open_orders = await db.b2b_orders.find(
        {"status": {"$in": ["invoiced", "partially_paid"]}, "outstanding": {"$gt": 0}},
        {"_id": 0},
    ).to_list(5000)
    now = datetime.now(timezone.utc)
    buckets = {"0-30": 0.0, "31-60": 0.0, "61-90": 0.0, "90+": 0.0}
    by_customer: dict = {}
    total_outstanding = 0.0
    overdue_orders = []
    for o in open_orders:
        due = o.get("due_date")
        days_overdue = 0
        if due:
            try:
                dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
                days_overdue = max(0, (now - dt).days)
            except Exception:
                days_overdue = 0
        o["days_overdue"] = days_overdue
        b = _bucket_days(days_overdue) if days_overdue > 0 else "0-30"
        buckets[b] += o["outstanding"]
        total_outstanding += o["outstanding"]
        cust = by_customer.setdefault(o["customer_id"], {
            "customer_id": o["customer_id"],
            "customer_name": o.get("customer_name"),
            "outstanding": 0.0, "orders": 0, "oldest_days_overdue": 0,
        })
        cust["outstanding"] += o["outstanding"]
        cust["orders"] += 1
        cust["oldest_days_overdue"] = max(cust["oldest_days_overdue"], days_overdue)
        if days_overdue > 0:
            overdue_orders.append(o)
    for k in buckets: buckets[k] = round(buckets[k], 2)
    top = sorted(by_customer.values(), key=lambda x: -x["outstanding"])[:20]
    return {
        "total_outstanding": round(total_outstanding, 2),
        "orders_open": len(open_orders),
        "buckets": buckets,
        "top_debtors": top,
        "overdue_orders": sorted(overdue_orders, key=lambda x: -x["days_overdue"])[:50],
    }


@router.get("/collections/receivables.csv")
async def receivables_csv(request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    orders = await db.b2b_orders.find(
        {"status": {"$in": ["invoiced", "partially_paid"]}, "outstanding": {"$gt": 0}}, {"_id": 0}
    ).to_list(5000)
    now = datetime.now(timezone.utc)
    out = io.StringIO()
    w = safe_csv_writer(out)
    w.writerow(["Order No", "Invoice No", "Customer", "GSTIN", "Total", "Paid", "Outstanding",
                "Invoice Date", "Due Date", "Days Overdue", "Bucket"])
    for o in orders:
        days = 0
        if o.get("due_date"):
            try:
                dt = datetime.fromisoformat(o["due_date"].replace("Z", "+00:00"))
                days = max(0, (now - dt).days)
            except Exception:
                pass
        w.writerow([o["order_no"], o.get("invoice_no"), o.get("customer_name"),
                    o.get("customer_gstin"), o["total"], o.get("paid_amount", 0),
                    o["outstanding"], o.get("invoice_date"), o.get("due_date"),
                    days, _bucket_days(days) if days > 0 else "0-30"])
    out.seek(0)
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="receivables.csv"'})


@router.post("/orders/{oid}/remind")
async def send_reminder(oid: str, request: Request, channel: str = "whatsapp",
                        actor: dict = Depends(require_roles(ROLE_OWNER))):
    from services.messaging import send_payment_reminder
    db = request.app.state.db
    o = await db.b2b_orders.find_one({"id": oid})
    if not o: raise HTTPException(404, "Not found")
    cust = await db.customers.find_one({"id": o["customer_id"]})
    if not cust: raise HTTPException(404, "Customer not found")
    result = await send_payment_reminder(cust, o, channel=channel)
    await db.b2b_reminders.insert_one({
        "id": gen_id(), "order_id": oid, "channel": channel,
        "sent_at": now_iso(), "sent_by": actor["id"], "result": result,
    })
    await audit(db, actor, "b2b.reminder.send", "b2b_order", oid, {"channel": channel})
    return {"ok": True, "result": result}
