"""Pine Labs terminal payment routes.

Flow:
  1. POS calls  POST /api/pinelabs/pay      -> creates a txn, gets ptr_id
  2. POS polls  GET  /api/pinelabs/status/{ptr_id}
  3. On APPROVED, POS finalises the sale via /api/pos/sales including the ptr_id in the payment.
  4. In simulator mode: POST /api/pinelabs/simulate/{ptr_id}/approve (dev only)
  5. Pine Labs webhook: POST /api/pinelabs/webhook (idempotent by ptr_id)
"""
from __future__ import annotations
import os
import secrets
from typing import Optional, Literal
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel, Field
from datetime import datetime, timezone

from models import gen_id, now_iso, ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER
from auth import get_current_user, require_roles, audit
from security import secret_matches
from services.pinelabs import pinelabs, normalize_status, config_summary, _mode, save_db_settings, load_db_settings

router = APIRouter(prefix="/pinelabs", tags=["pinelabs"])


class PineLabsSettingsBody(BaseModel):
    merchant_id: Optional[str] = None
    security_token: Optional[str] = None
    store_id: Optional[str] = None
    terminal_id: Optional[str] = None
    user_id: Optional[str] = None
    mode: Optional[Literal["simulator", "uat", "production"]] = None


@router.get("/settings")
async def get_settings(request: Request, actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    doc = await db.settings.find_one({"_id": "pinelabs"}, {"_id": 0}) or {}
    def _mask(v):
        if not v: return None
        s = str(v)
        return (s[:2] + "•" * max(0, len(s) - 4) + s[-2:]) if len(s) > 4 else "•" * len(s)
    return {
        "merchant_id": doc.get("merchant_id") or None,
        "security_token_masked": _mask(doc.get("security_token")),
        "store_id": doc.get("store_id") or None,
        "terminal_id": doc.get("terminal_id") or None,
        "user_id": doc.get("user_id") or None,
        "mode": (doc.get("mode") or _mode()),
        "config_summary": config_summary(),
    }


@router.post("/settings")
async def update_settings(body: PineLabsSettingsBody, request: Request,
                          actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    patch = body.model_dump(exclude_unset=True)
    if "mode" in patch and patch["mode"]:
        os.environ["PINELABS_MODE"] = patch["mode"]
    saved = await save_db_settings(db, patch)
    await audit(db, actor, "pinelabs.settings.update", "settings", "pinelabs",
                {"fields": list(patch.keys())})
    return {"ok": True, "saved_keys": list(patch.keys()), "config_summary": config_summary()}


class PayRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Amount in INR (rupees). Converted to paise server-side.")
    mode: Literal["card", "upi"] = "card"
    terminal_id: Optional[str] = None  # override env terminal for this txn
    client_ref: Optional[str] = None   # idempotency key from POS


class SimulateApproveRequest(BaseModel):
    outcome: Literal["approved", "declined", "cancelled", "timeout"] = "approved"
    masked_pan: Optional[str] = "**** **** **** 4242"
    acquirer: Optional[str] = "HDFC"


@router.get("/config")
async def config(user: dict = Depends(get_current_user)):
    return config_summary()


@router.post("/pay")
async def pay(body: PayRequest, request: Request,
              actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER))):
    if _mode() == "disabled":
        raise HTTPException(503, "Pine Labs is disabled. Set PINELABS_MODE=simulator or provide UAT/production credentials.")
    db = request.app.state.db

    txn_no = body.client_ref or f"NDR{secrets.token_hex(6).upper()}"

    # Idempotency
    existing = await db.pinelabs_txns.find_one({"transaction_number": txn_no}, {"_id": 0})
    if existing:
        return {
            "ptr_id": existing["ptr_id"],
            "transaction_number": existing["transaction_number"],
            "status": existing["status"],
            "amount": existing["amount_paise"] / 100.0,
        }

    amount_paise = int(round(body.amount * 100))
    resp = await pinelabs.upload_billed_transaction(
        transaction_number=txn_no,
        amount_paise=amount_paise,
        mode=body.mode,
        terminal_id=body.terminal_id,
    )
    if int(resp.get("ResponseCode", 1)) != 0:
        raise HTTPException(502, resp.get("ResponseMessage", "Pine Labs upload failed"))

    ptr_id = str(resp["PlutusTransactionReferenceID"])
    doc = {
        "id": gen_id(),
        "ptr_id": ptr_id,
        "transaction_number": txn_no,
        "amount_paise": amount_paise,
        "mode": body.mode,
        "terminal_id": body.terminal_id,
        "status": "OPEN",
        "created_by": actor["id"],
        "created_at": now_iso(),
        "raw_upload_response": resp,
    }
    await db.pinelabs_txns.insert_one(doc)
    await audit(db, actor, "pinelabs.pay.initiate", "pinelabs_txn", doc["id"],
                {"ptr_id": ptr_id, "amount_paise": amount_paise, "mode": body.mode})
    doc.pop("_id", None)
    return {"ptr_id": ptr_id, "transaction_number": txn_no, "status": "OPEN", "amount": body.amount}


@router.get("/status/{ptr_id}")
async def status(ptr_id: str, request: Request, actor: dict = Depends(get_current_user)):
    db = request.app.state.db
    doc = await db.pinelabs_txns.find_one({"ptr_id": ptr_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Unknown PTR")
    # If still OPEN, poll Pine Labs
    if doc["status"] == "OPEN":
        resp = await pinelabs.get_status(ptr_id, doc["transaction_number"], db=db)
        new_status = normalize_status(resp.get("ResponseMessage") or resp.get("Status") or "OPEN")
        update = {
            "status": new_status,
            "last_polled_at": now_iso(),
            "last_poll_response": resp,
        }
        if new_status == "APPROVED":
            update.update({
                "rrn": resp.get("RRN"),
                "approval_code": resp.get("ApprovalCode"),
                "masked_pan": resp.get("MaskedPAN"),
                "acquirer": resp.get("Acquirer"),
                "settled_at": now_iso(),
            })
        await db.pinelabs_txns.update_one({"ptr_id": ptr_id}, {"$set": update})
        doc.update(update)
    # Trim raw responses in the API response for the client
    return {
        "ptr_id": doc["ptr_id"],
        "transaction_number": doc["transaction_number"],
        "status": doc["status"],
        "amount": doc["amount_paise"] / 100.0,
        "mode": doc["mode"],
        "rrn": doc.get("rrn"),
        "approval_code": doc.get("approval_code"),
        "masked_pan": doc.get("masked_pan"),
        "acquirer": doc.get("acquirer"),
        "settled_at": doc.get("settled_at"),
    }


@router.post("/cancel/{ptr_id}")
async def cancel(ptr_id: str, request: Request,
                 actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER))):
    db = request.app.state.db
    doc = await db.pinelabs_txns.find_one({"ptr_id": ptr_id})
    if not doc: raise HTTPException(404, "Unknown PTR")
    if doc["status"] in ("APPROVED", "CANCELLED", "DECLINED"):
        raise HTTPException(400, f"Cannot cancel in status {doc['status']}")
    resp = await pinelabs.cancel(ptr_id)
    await db.pinelabs_txns.update_one({"ptr_id": ptr_id},
                                      {"$set": {"status": "CANCELLED", "cancelled_at": now_iso(),
                                                "cancel_response": resp}})
    await audit(db, actor, "pinelabs.pay.cancel", "pinelabs_txn", doc["id"], {"ptr_id": ptr_id})
    return {"ptr_id": ptr_id, "status": "CANCELLED"}


@router.post("/simulate/{ptr_id}/approve")
async def simulate_approve(ptr_id: str, body: SimulateApproveRequest, request: Request,
                            actor: dict = Depends(require_roles(ROLE_OWNER))):
    """DEV / test endpoint — only meaningful in simulator mode."""
    if _mode() != "simulator":
        raise HTTPException(400, "Only available in simulator mode.")
    db = request.app.state.db
    doc = await db.pinelabs_txns.find_one({"ptr_id": ptr_id})
    if not doc: raise HTTPException(404, "Unknown PTR")
    outcome_map = {"approved": "APPROVED", "declined": "DECLINED",
                   "cancelled": "CANCELLED", "timeout": "TIMEOUT"}
    new_status = outcome_map[body.outcome]
    update = {"status": new_status, "simulated_at": now_iso()}
    if new_status == "APPROVED":
        update.update({
            "rrn": secrets.token_hex(6).upper(),
            "approval_code": secrets.token_hex(3).upper(),
            "masked_pan": body.masked_pan,
            "acquirer": body.acquirer,
            "settled_at": now_iso(),
        })
    await db.pinelabs_txns.update_one({"ptr_id": ptr_id}, {"$set": update})
    return {"ptr_id": ptr_id, "status": new_status}


@router.post("/webhook")
async def webhook(request: Request):
    """Pine Labs callback receiver. Idempotent by ptr_id + terminal status.

    Security: without a shared secret anyone on the internet could mark a card
    payment as APPROVED. Pine Labs must call
    /api/pinelabs/webhook?token=<PINELABS_WEBHOOK_SECRET> (or send header
    X-Webhook-Token). If the secret is not configured, the webhook is closed.
    """
    expected = os.environ.get("PINELABS_WEBHOOK_SECRET")
    provided = request.headers.get("x-webhook-token") or request.query_params.get("token")
    if not secret_matches(provided, expected):
        raise HTTPException(401, "Unauthorized")
    body = await request.json()
    ptr_id = str(body.get("PlutusTransactionReferenceID") or body.get("ptr_id") or "")
    if not ptr_id:
        raise HTTPException(400, "Missing PlutusTransactionReferenceID")
    db = request.app.state.db
    doc = await db.pinelabs_txns.find_one({"ptr_id": ptr_id})
    if not doc:
        # Store orphan callbacks for reconciliation
        await db.pinelabs_callbacks.insert_one(
            {"id": gen_id(), "ptr_id": ptr_id, "received_at": now_iso(),
             "orphan": True, "body": body}
        )
        return {"status": "orphan"}
    new_status = normalize_status(body.get("ResponseMessage") or body.get("Status") or "OPEN")
    if doc.get("status") == new_status and doc.get("status") != "OPEN":
        return {"status": "duplicate_ignored"}
    update = {"status": new_status, "webhook_received_at": now_iso(), "webhook_body": body}
    if new_status == "APPROVED":
        update.update({
            "rrn": body.get("RRN"),
            "approval_code": body.get("ApprovalCode"),
            "masked_pan": body.get("MaskedPAN"),
            "acquirer": body.get("Acquirer"),
            "settled_at": now_iso(),
        })
    await db.pinelabs_txns.update_one({"ptr_id": ptr_id}, {"$set": update})
    return {"status": "ok"}
