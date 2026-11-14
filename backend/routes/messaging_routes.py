"""Messaging routes: send receipt / reminder, check config."""
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel
from typing import Literal, Optional

from auth import get_current_user, require_roles, audit
from models import gen_id, now_iso, ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER
from services.messaging import (
    send_whatsapp, send_sms, send_receipt, config_summary,
)

router = APIRouter(prefix="/messaging", tags=["messaging"])


class SendReceiptRequest(BaseModel):
    sale_id: str
    channel: Literal["whatsapp", "sms"] = "whatsapp"


class DirectMessage(BaseModel):
    to: str
    body: str
    channel: Literal["whatsapp", "sms"] = "whatsapp"


@router.get("/config")
async def config(user: dict = Depends(get_current_user)):
    return config_summary()


@router.post("/send-receipt")
async def send_receipt_endpoint(body: SendReceiptRequest, request: Request,
                                 actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER, ROLE_CASHIER))):
    db = request.app.state.db
    sale = await db.sales.find_one({"id": body.sale_id}, {"_id": 0})
    if not sale: raise HTTPException(404, "Sale not found")
    if not sale.get("customer_id"):
        raise HTTPException(400, "Sale has no customer attached")
    cust = await db.customers.find_one({"id": sale["customer_id"]}, {"_id": 0})
    if not cust or not cust.get("phone"):
        raise HTTPException(400, "Customer has no phone on file")
    result = await send_receipt(cust, sale, channel=body.channel)
    await db.messages.insert_one({
        "id": gen_id(),
        "kind": "receipt", "channel": body.channel,
        "sale_id": sale["id"], "customer_id": cust["id"],
        "to": cust.get("phone"),
        "sent_at": now_iso(), "sent_by": actor["id"], "result": result,
    })
    await audit(db, actor, "messaging.send_receipt", "sale", sale["id"],
                {"channel": body.channel, "customer_id": cust["id"]})
    return {"ok": True, "result": result}


@router.post("/send")
async def send_direct(body: DirectMessage, request: Request,
                      actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    fn = send_whatsapp if body.channel == "whatsapp" else send_sms
    result = await fn(body.to, body.body)
    await db.messages.insert_one({
        "id": gen_id(),
        "kind": "direct", "channel": body.channel,
        "to": body.to, "body": body.body[:400],
        "sent_at": now_iso(), "sent_by": actor["id"], "result": result,
    })
    return {"ok": True, "result": result}


@router.get("/log")
async def message_log(request: Request, limit: int = 100,
                       user: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    return await db.messages.find({}, {"_id": 0}).sort("sent_at", -1).to_list(limit)
