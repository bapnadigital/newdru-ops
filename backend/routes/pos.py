"""POS / sales endpoints with GST-compliant invoicing."""
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Depends
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from models import (
    SaleCreate, LOC_STORE, ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER,
    gen_id, now_iso,
)
from auth import get_current_user, require_roles, audit
from routes.inventory import _apply_delta, _write_movement

router = APIRouter(prefix="/pos", tags=["pos"])


async def _release_ptrs(db, ptrs):
    if ptrs:
        await db.pinelabs_txns.update_many({"ptr_id": {"$in": ptrs}, "sale_id": {"$regex": "^pending:"}},
                                           {"$set": {"sale_id": None}})


async def _next_invoice_no(db) -> str:
    prefix = os.environ.get("INVOICE_PREFIX", "NW")
    year = datetime.now(timezone.utc).strftime("%y")
    counter = await db.counters.find_one_and_update(
        {"_id": f"invoice_{year}"},
        {"$inc": {"seq": 1}},
        upsert=True, return_document=True,
    )
    if not counter:
        counter = await db.counters.find_one({"_id": f"invoice_{year}"})
    seq = counter.get("seq", 1) if counter else 1
    return f"{prefix}-{year}-{seq:05d}"


def _compute_lines(items, cart_discount: float):
    subtotal = 0.0; tax_total = 0.0
    gst_breakup: dict = {}
    processed = []
    for it in items:
        qty = int(it.quantity)
        gross = (float(it.unit_price) * qty) - float(it.discount or 0)
        gross = max(gross, 0.0)
        rate = float(it.gst_rate or 0)
        base = gross / (1 + rate / 100) if (1 + rate / 100) > 0 else gross
        tax = gross - base
        rate_key = f"{rate:.2f}"
        gst_breakup.setdefault(rate_key, {"taxable": 0.0, "tax": 0.0})
        gst_breakup[rate_key]["taxable"] += round(base, 2)
        gst_breakup[rate_key]["tax"] += round(tax, 2)
        processed.append({
            **it.model_dump(),
            "line_subtotal": round(base, 2),
            "tax_amount": round(tax, 2),
            "line_total": round(gross, 2),
        })
        subtotal += base; tax_total += tax

    total_gross = subtotal + tax_total
    cart_discount = float(cart_discount or 0)
    if cart_discount > total_gross: cart_discount = total_gross
    total_after = total_gross - cart_discount
    if total_gross > 0 and cart_discount > 0:
        ratio = total_after / total_gross
        subtotal *= ratio; tax_total *= ratio
        for k in gst_breakup:
            gst_breakup[k]["taxable"] = round(gst_breakup[k]["taxable"] * ratio, 2)
            gst_breakup[k]["tax"] = round(gst_breakup[k]["tax"] * ratio, 2)

    return {
        "items": processed,
        "subtotal": round(subtotal, 2),
        "tax_total": round(tax_total, 2),
        "cart_discount": round(cart_discount, 2),
        "total": round(total_after, 2),
        "gst_breakup": gst_breakup,
    }


async def _upsert_customer(db, customer_id: Optional[str], customer_dict: Optional[dict],
                           sale_total: float, now: str) -> Optional[dict]:
    if customer_id:
        cust = await db.customers.find_one({"id": customer_id})
        if cust:
            await db.customers.update_one(
                {"id": customer_id},
                {"$set": {"last_seen": now},
                 "$inc": {"total_spend": sale_total, "order_count": 1}},
            )
            cust = await db.customers.find_one({"id": customer_id}, {"_id": 0})
            aov = round(cust["total_spend"] / max(cust["order_count"], 1), 2)
            await db.customers.update_one({"id": customer_id}, {"$set": {"avg_order_value": aov}})
            cust["avg_order_value"] = aov
            return cust

    if customer_dict:
        query = []
        if customer_dict.get("phone"): query.append({"phone": customer_dict["phone"]})
        if customer_dict.get("email"): query.append({"email": customer_dict["email"]})
        existing = None
        if query:
            existing = await db.customers.find_one({"$or": query})
        if existing:
            await db.customers.update_one(
                {"id": existing["id"]},
                {"$set": {"last_seen": now,
                          "name": customer_dict.get("name") or existing.get("name")},
                 "$inc": {"total_spend": sale_total, "order_count": 1}},
            )
            cust = await db.customers.find_one({"id": existing["id"]}, {"_id": 0})
            aov = round(cust["total_spend"] / max(cust["order_count"], 1), 2)
            await db.customers.update_one({"id": existing["id"]}, {"$set": {"avg_order_value": aov}})
            cust["avg_order_value"] = aov
            return cust
        doc = {
            "id": gen_id(),
            "name": customer_dict.get("name") or "Walk-in",
            "phone": customer_dict.get("phone"),
            "email": customer_dict.get("email"),
            "channel": customer_dict.get("channel", "store"),
            "tags": customer_dict.get("tags", []),
            "first_seen": now, "last_seen": now,
            "total_spend": sale_total, "order_count": 1,
            "avg_order_value": sale_total,
        }
        await db.customers.insert_one(doc)
        doc.pop("_id", None)
        return doc
    return None


@router.post("/sales")
async def create_sale(body: SaleCreate, request: Request,
                      actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER))):
    db = request.app.state.db
    if not body.items: raise HTTPException(400, "Cart is empty")

    if body.client_ref:
        dup = await db.sales.find_one({"client_ref": body.client_ref}, {"_id": 0})
        if dup: return dup

    # Prices come from the product list, never from the browser, so nobody can
    # bill an item cheaper by editing the request. GST rate and name too.
    for it in body.items:
        prod = await db.products.find_one({"id": it.product_id},
                                          {"_id": 0, "sell_price": 1, "gst_rate": 1, "sku": 1, "name": 1})
        if not prod:
            raise HTTPException(400, f"'{it.name}' is not in the product list")
        if prod.get("sell_price") and float(prod["sell_price"]) > 0:
            it.unit_price = float(prod["sell_price"])
        if prod.get("gst_rate") is not None:
            it.gst_rate = float(prod["gst_rate"])
        it.sku, it.name = prod.get("sku") or it.sku, prod.get("name") or it.name

    # Only the owner and store manager may give discounts (same rule as the screen).
    if actor.get("role") not in (ROLE_OWNER, ROLE_STORE_MANAGER):
        if float(body.cart_discount or 0) > 0 or any(float(i.discount or 0) > 0 for i in body.items):
            raise HTTPException(403, "Only the owner or store manager can give a discount")
    if float(body.cart_discount or 0) < 0 or any(float(i.discount or 0) < 0 for i in body.items):
        raise HTTPException(400, "Discount cannot be negative")

    # Reject any line with a zero / negative price — protects against corrupted product data.
    for it in body.items:
        if float(it.unit_price or 0) <= 0:
            raise HTTPException(400, f"Line '{it.name}' has invalid unit_price. Check the product's sell price.")
        if int(it.quantity or 0) <= 0:
            raise HTTPException(400, f"Line '{it.name}' has invalid quantity.")

    # -------- Below-COGS guard ---------------------------------------------
    below_cogs_lines = []
    for it in body.items:
        prod = await db.products.find_one({"id": it.product_id}, {"_id": 0, "cogs_per_unit": 1, "sku": 1, "name": 1})
        cogs = float((prod or {}).get("cogs_per_unit") or 0)
        if cogs <= 0:
            continue
        qty = int(it.quantity)
        line_disc = float(it.discount or 0)
        effective_unit_price = ((float(it.unit_price) * qty) - line_disc) / qty
        if effective_unit_price < cogs - 0.005:
            below_cogs_lines.append({
                "sku": it.sku, "name": it.name,
                "effective_unit_price": round(effective_unit_price, 2),
                "cogs_per_unit": round(cogs, 2),
                "quantity": qty,
            })

    admin_override_info = None
    if below_cogs_lines:
        if actor.get("role") == "owner":
            admin_override_info = {
                "admin_id": actor["id"], "admin_email": actor["email"],
                "admin_name": actor["name"], "reason": body.admin_override_reason or "owner-authorized",
                "self_authorized": True, "lines": below_cogs_lines,
            }
        else:
            if not body.admin_override_email or not body.admin_override_password:
                raise HTTPException(status_code=403, detail={
                    "code": "BELOW_COGS_BLOCKED",
                    "message": "One or more lines are priced below COGS — admin permission required.",
                    "below_cogs_lines": below_cogs_lines,
                })
            admin = await db.users.find_one({"email": body.admin_override_email.lower().strip()})
            from auth import verify_password as _vp
            if (not admin or admin.get("role") != "owner" or not admin.get("active", True)
                    or not _vp(body.admin_override_password, admin["password_hash"])):
                raise HTTPException(status_code=401, detail="Admin override rejected")
            admin_override_info = {
                "admin_id": admin["id"], "admin_email": admin["email"],
                "admin_name": admin["name"], "reason": body.admin_override_reason or None,
                "self_authorized": False, "lines": below_cogs_lines,
            }

    calc = _compute_lines(body.items, body.cart_discount)
    if calc["total"] <= 0:
        raise HTTPException(400, "Sale total must be greater than zero.")
    payment_total = round(sum(p.amount for p in body.payments), 2)
    if abs(payment_total - calc["total"]) > 0.05:
        raise HTTPException(400, f"Payment total {payment_total} does not match sale total {calc['total']}")

    now = now_iso()
    invoice_no = await _next_invoice_no(db)
    customer = await _upsert_customer(
        db, body.customer_id, body.customer.model_dump() if body.customer else None,
        calc["total"], now,
    )

    # Card/UPI must come from an APPROVED Pine Labs terminal transaction when the
    # terminal is live, so nobody can record a card payment that never happened.
    from services.pinelabs import _mode as _pl_mode
    pl_live = _pl_mode() in ("uat", "production")
    used_ptrs = []
    for p in body.payments:
        if p.method not in ("card", "upi") or p.amount <= 0:
            continue
        if not p.ptr_id:
            if pl_live:
                raise HTTPException(400, f"{p.method.upper()} payment must be taken on the Pine Labs terminal from this screen.")
            continue
        txn = await db.pinelabs_txns.find_one({"ptr_id": str(p.ptr_id)}, {"_id": 0})
        if not txn or txn.get("status") != "APPROVED":
            await _release_ptrs(db, used_ptrs)
            raise HTTPException(400, "Terminal payment is not approved yet.")
        txn_amount = (txn["amount_paise"] / 100.0) if txn.get("amount_paise") is not None else float(txn.get("amount") or 0)
        if abs(txn_amount - float(p.amount)) > 0.05:
            await _release_ptrs(db, used_ptrs)
            raise HTTPException(400, "Terminal amount does not match the payment amount.")
        # Claim it atomically: two tills can never attach the same payment.
        claimed = await db.pinelabs_txns.find_one_and_update(
            {"ptr_id": str(p.ptr_id), "sale_id": None}, {"$set": {"sale_id": "pending:" + invoice_no}})
        if not claimed:
            await _release_ptrs(db, used_ptrs)
            raise HTTPException(400, "This terminal payment is already attached to another bill.")
        p.rrn, p.approval_code = txn.get("rrn"), txn.get("approval_code")
        p.masked_pan, p.acquirer = txn.get("masked_pan"), txn.get("acquirer")
        used_ptrs.append(str(p.ptr_id))

    payment_summary = body.payments[0].method if len(body.payments) == 1 else "split"

    sale = {
        "id": gen_id(),
        "invoice_no": invoice_no,
        "cashier_id": actor["id"], "cashier_name": actor["name"],
        "customer_id": customer["id"] if customer else None,
        "customer_name": customer["name"] if customer else None,
        "items": calc["items"],
        "subtotal": calc["subtotal"],
        "cart_discount": calc["cart_discount"],
        "tax_total": calc["tax_total"],
        "total": calc["total"],
        "gst_breakup": calc["gst_breakup"],
        "payments": [p.model_dump() for p in body.payments],
        "payment_method_summary": payment_summary,
        "location_code": LOC_STORE,
        "notes": body.notes,
        "client_ref": body.client_ref,
        # Phase-3 revenue attribution hooks (safe to be None in Phase 1)
        "campaign_tag": (body.campaign_tag or None),
        "discount_code": (body.discount_code or None),
        # Below-COGS admin override (None when no line was below cost)
        "admin_override": admin_override_info,
        "created_at": now,
    }
    await db.sales.insert_one(sale)
    if used_ptrs:
        await db.pinelabs_txns.update_many({"ptr_id": {"$in": used_ptrs}},
                                           {"$set": {"sale_id": sale["id"], "invoice_no": invoice_no}})

    if admin_override_info:
        await audit(db, actor, "sale.below_cogs_override", "sale", sale["id"], {
            "invoice_no": invoice_no,
            "approved_by": admin_override_info.get("admin_email"),
            "self_authorized": admin_override_info.get("self_authorized"),
            "lines": admin_override_info.get("lines"),
        })

    for it in calc["items"]:
        qty = int(it["quantity"])
        product = await db.products.find_one({"id": it["product_id"]})
        if not product: continue
        await _apply_delta(db, it["product_id"], LOC_STORE, -qty)
        await _write_movement(db, actor, product, LOC_STORE, -qty, "sale", reference_id=sale["id"])

    await audit(db, actor, "sale.create", "sale", sale["id"],
                {"invoice_no": invoice_no, "total": calc["total"]})
    sale.pop("_id", None)
    return sale


@router.get("/sales")
async def list_sales(
    request: Request,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    cashier_id: Optional[str] = None,
    invoice_no: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER)),
):
    db = request.app.state.db
    q: dict = {}
    if from_date or to_date:
        q["created_at"] = {}
        if from_date: q["created_at"]["$gte"] = from_date
        if to_date: q["created_at"]["$lte"] = to_date
    if cashier_id: q["cashier_id"] = cashier_id
    if invoice_no: q["invoice_no"] = str(invoice_no).strip().upper()[:40]
    if user["role"] == ROLE_CASHIER:
        q["cashier_id"] = user["id"]
    limit = max(1, min(int(limit), 1000))
    docs = await db.sales.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return docs


@router.get("/sales/{sale_id}")
async def get_sale(sale_id: str, request: Request, user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER))):
    db = request.app.state.db
    doc = await db.sales.find_one({"id": sale_id}, {"_id": 0})
    if not doc: raise HTTPException(404, "Sale not found")
    if user["role"] == ROLE_CASHIER and doc.get("cashier_id") != user["id"]:
        raise HTTPException(403, "Cashiers can only view own sales")
    return doc


@router.get("/shift/report")
async def shift_report(request: Request, cashier_id: Optional[str] = None,
                       user: dict = Depends(get_current_user)):
    db = request.app.state.db
    target_id = cashier_id or user["id"]
    if user["role"] == ROLE_CASHIER and target_id != user["id"]:
        raise HTTPException(403, "Cashiers can only view own shift report")

    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    sales = await db.sales.find({"cashier_id": target_id, "created_at": {"$gte": start_of_day}},
                                {"_id": 0}).to_list(1000)
    by_method: dict = {"cash": 0.0, "card": 0.0, "upi": 0.0}
    total = 0.0
    for s in sales:
        for p in s.get("payments", []):
            by_method[p["method"]] = by_method.get(p["method"], 0) + float(p["amount"])
        total += float(s.get("total", 0))
    refunds = await db.sales_returns.find({"by_id": target_id, "created_at": {"$gte": start_of_day}},
                                          {"_id": 0, "refund_total": 1, "refund_method": 1}).to_list(1000)
    refund_by_method: dict = {}
    for r in refunds:
        refund_by_method[r["refund_method"]] = round(refund_by_method.get(r["refund_method"], 0) + float(r["refund_total"]), 2)
    return {
        "refunds": refund_by_method,
        "cash_in_drawer": round(by_method.get("cash", 0) - refund_by_method.get("cash", 0), 2),
        "cashier_id": target_id, "date": start_of_day,
        "sale_count": len(sales), "order_count": len(sales),
        "shift_start": start_of_day,
        "total": round(total, 2),
        "by_method": {k: round(v, 2) for k, v in by_method.items()},
        "sales": sales[:100],
    }


# ============================================================
# Returns / exchanges -> GST credit note, stock back to the store
# ============================================================
class ReturnLine(BaseModel):
    product_id: str
    quantity: int = Field(gt=0, le=10000)


class SaleReturn(BaseModel):
    sale_id: str
    items: List[ReturnLine] = Field(min_length=1, max_length=200)
    refund_method: Literal["cash", "card", "upi", "credit_note"] = "cash"
    reason: str = Field(min_length=3, max_length=300)


async def _next_credit_note_no(db) -> str:
    prefix = os.environ.get("INVOICE_PREFIX", "NW")
    year = datetime.now(timezone.utc).strftime("%y")
    c = await db.counters.find_one_and_update({"_id": f"credit_note_{year}"}, {"$inc": {"seq": 1}},
                                              upsert=True, return_document=True)
    return f"{prefix}-CN-{year}-{(c or {}).get('seq', 1):05d}"


@router.post("/returns")
async def create_return(body: SaleReturn, request: Request,
                        actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER))):
    """Customer brings items back. Only owner / store manager (not cashiers)."""
    db = request.app.state.db
    sale = await db.sales.find_one({"id": body.sale_id}, {"_id": 0})
    if not sale:
        raise HTTPException(404, "Bill not found")
    days = int(os.environ.get("RETURN_WINDOW_DAYS", "30"))
    try:
        sold_at = datetime.fromisoformat(sale["created_at"].replace("Z", "+00:00"))
        if sold_at.tzinfo is None:
            sold_at = sold_at.replace(tzinfo=timezone.utc)
        too_old = (datetime.now(timezone.utc) - sold_at).days > days
    except (KeyError, ValueError):
        too_old = False
    if too_old and actor["role"] != ROLE_OWNER:
        raise HTTPException(403, f"Bill is older than {days} days — only the owner can accept this return")

    lines = {it["product_id"]: it for it in sale["items"]}
    gross_lines = sum(float(it.get("line_total") or 0) for it in sale["items"]) or 1.0
    ratio = float(sale.get("total") or 0) / gross_lines          # share of any bill discount
    want: dict = {}
    for r in body.items:
        want[r.product_id] = want.get(r.product_id, 0) + r.quantity
    out_items, refund, gst = [], 0.0, {}
    for pid, q in want.items():
        it = lines.get(pid)
        if not it:
            raise HTTPException(400, "An item is not on this bill")
        left = int(it["quantity"]) - int(it.get("returned_qty") or 0)
        if q > left:
            raise HTTPException(400, f"Only {left} of '{it['name']}' can still be returned on this bill")
        per_unit = float(it.get("line_total") or 0) / int(it["quantity"]) * ratio
        per_tax = float(it.get("tax_amount") or 0) / int(it["quantity"]) * ratio
        amt, tax = round(per_unit * q, 2), round(per_tax * q, 2)
        refund += amt
        k = f"{float(it.get('gst_rate') or 0):.2f}"
        gst.setdefault(k, {"taxable": 0.0, "tax": 0.0})
        gst[k]["taxable"] = round(gst[k]["taxable"] + amt - tax, 2)
        gst[k]["tax"] = round(gst[k]["tax"] + tax, 2)
        out_items.append({"product_id": pid, "sku": it.get("sku"), "name": it.get("name"),
                          "quantity": q, "refund": amt, "tax_amount": tax})

    # Claim atomically against the bill's current state so two returns can't over-return.
    ver = int(sale.get("returns_version") or 0)
    new_items = []
    for it in sale["items"]:
        n = dict(it)
        if it["product_id"] in want:
            n["returned_qty"] = int(it.get("returned_qty") or 0) + want[it["product_id"]]
            want[it["product_id"]] = 0   # only the first matching line takes it
        new_items.append(n)
    ok = await db.sales.find_one_and_update(
        {"id": sale["id"], "$or": [{"returns_version": ver}, {"returns_version": {"$exists": False}}] if ver == 0
         else [{"returns_version": ver}]},
        {"$set": {"items": new_items, "returns_version": ver + 1},
         "$inc": {"refunded_total": round(refund, 2)}})
    if not ok:
        raise HTTPException(409, "This bill was just changed; open it again and retry")

    now = now_iso()
    cn = {
        "id": gen_id(), "credit_note_no": await _next_credit_note_no(db),
        "sale_id": sale["id"], "invoice_no": sale["invoice_no"],
        "customer_id": sale.get("customer_id"), "customer_name": sale.get("customer_name"),
        "items": out_items, "refund_total": round(refund, 2), "gst_breakup": gst,
        "refund_method": body.refund_method, "reason": body.reason.strip(),
        "by_id": actor["id"], "by_name": actor["name"], "location_code": LOC_STORE,
        "created_at": now,
    }
    await db.sales_returns.insert_one(cn)
    for it in out_items:
        product = await db.products.find_one({"id": it["product_id"]})
        if not product: continue
        await _apply_delta(db, it["product_id"], LOC_STORE, it["quantity"])
        await _write_movement(db, actor, product, LOC_STORE, it["quantity"], "sale_return",
                              reason=body.reason.strip(), reference_id=cn["id"])
    await audit(db, actor, "sale.return", "sale", sale["id"],
                {"credit_note_no": cn["credit_note_no"], "refund": cn["refund_total"],
                 "method": body.refund_method})
    cn.pop("_id", None)
    return cn


@router.get("/returns")
async def list_returns(request: Request, sale_id: Optional[str] = None, limit: int = 100,
                       user: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER))):
    db = request.app.state.db
    q = {"sale_id": sale_id} if sale_id else {}
    return await db.sales_returns.find(q, {"_id": 0}).sort("created_at", -1).to_list(max(1, min(int(limit), 500)))


@router.get("/business-info")
async def business_info(user: dict = Depends(get_current_user)):
    return {
        "name": os.environ.get("BUSINESS_NAME", "Newdru"),
        "gstin": os.environ.get("BUSINESS_GSTIN", ""),
        "invoice_prefix": os.environ.get("INVOICE_PREFIX", "NW"),
    }
