"""Ship wholesale orders and store home-deliveries with Shiprocket.

Marketplace (Amazon/Flipkart) and newdru.com orders are NOT shipped from here —
they keep going through Unicommerce / Shiprocket's own Shopify app, so nothing is
shipped twice.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from auth import audit, require_roles
from models import ROLE_OWNER, ROLE_STORE_MANAGER, gen_id, now_iso
from security import secret_matches
from services import shiprocket as sr

router = APIRouter(prefix="/shipping", tags=["shipping"])
hook = APIRouter(tags=["shipping"])  # webhook path must not contain "sr"/"shiprocket"

ACTIVE = {"created", "awb_assigned", "pickup_scheduled", "in_transit", "out_for_delivery"}


def _require_live():
    if sr.mode() != "live":
        raise HTTPException(503, "Shiprocket is switched off (SHIPROCKET_MODE). Ask the owner to connect it.")
    if not sr.configured():
        raise HTTPException(503, "Shiprocket API user is not set up yet.")


class Address(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=10, max_length=15)
    email: Optional[str] = Field(default=None, max_length=120)
    line1: str = Field(min_length=3, max_length=190)
    line2: Optional[str] = Field(default=None, max_length=190)
    city: str = Field(min_length=2, max_length=60)
    state: str = Field(min_length=2, max_length=60)
    pincode: str

    @field_validator("pincode")
    @classmethod
    def _pin(cls, v):
        v = str(v).strip()
        if not re.fullmatch(r"[1-9][0-9]{5}", v):
            raise ValueError("Pincode must be 6 digits")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        digits = re.sub(r"\D", "", v)
        if len(digits) < 10:
            raise ValueError("Phone must have 10 digits")
        return digits[-10:]


class RatesIn(BaseModel):
    delivery_pincode: str = Field(pattern=r"^[1-9][0-9]{5}$")
    weight_kg: float = Field(gt=0, le=500)
    cod: bool = False
    ship_from: Literal["BHIWANDI", "STORE"] = "BHIWANDI"


class ShipIn(BaseModel):
    kind: Literal["b2b", "sale"]
    ref_id: str = Field(max_length=64)
    address: Address
    weight_kg: float = Field(gt=0, le=500)
    length_cm: float = Field(default=20, gt=0, le=300)
    breadth_cm: float = Field(default=15, gt=0, le=300)
    height_cm: float = Field(default=10, gt=0, le=300)
    cod: bool = False
    cod_amount: Optional[float] = Field(default=None, ge=0)
    courier_id: Optional[int] = None
    ship_from: Optional[Literal["BHIWANDI", "STORE"]] = None


@router.get("/config")
async def config(actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER))):
    return {"mode": sr.mode(), "configured": sr.configured(),
            "pickup": sr.pickup("BHIWANDI"), "store_pickup": sr.pickup("STORE"),
            "webhook_secret_set": bool(os.environ.get("SHIPROCKET_WEBHOOK_SECRET"))}


@router.post("/rates")
async def rates(body: RatesIn, actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER))):
    _require_live()
    pk = sr.pickup(body.ship_from)
    if not pk["pincode"]:
        raise HTTPException(503, "Pickup pincode is not set (SHIPROCKET_PICKUP_PINCODE).")
    try:
        return await sr.ShiprocketClient().rates(pk["pincode"], body.delivery_pincode, body.weight_kg, body.cod)
    except sr.ShiprocketError as e:
        raise HTTPException(502, str(e))


def _item(i: dict) -> dict:
    qty = max(1, int(i.get("quantity") or 1))
    price = (float(i["line_total"]) / qty) if i.get("line_total") is not None else float(i.get("unit_price") or 0)
    return {"name": i.get("name") or i.get("sku"), "sku": i["sku"], "quantity": qty,
            "unit_price": round(price, 2), "hsn": i.get("hsn")}


async def _load_ref(db, kind: str, ref_id: str, actor: dict) -> dict:
    if kind == "b2b":
        if actor["role"] != ROLE_OWNER:
            raise HTTPException(403, "Only the owner can ship wholesale orders")
        doc = await db.b2b_orders.find_one({"id": ref_id}, {"_id": 0})
        if not doc:
            raise HTTPException(404, "Order not found")
        if doc.get("status") == "cancelled":
            raise HTTPException(400, "Order is cancelled")
        items = [_item(i) for i in doc["items"]]
        return {"ref": doc["order_no"], "items": items, "total": doc["total"],
                "ship_from": doc.get("ship_from") or "BHIWANDI", "date": doc["created_at"]}
    doc = await db.sales.find_one({"id": ref_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Bill not found")
    items = [_item(i) for i in doc["items"]]
    return {"ref": doc["invoice_no"], "items": items, "total": doc["total"],
            "ship_from": "STORE", "date": doc["created_at"]}


@router.post("/ship")
async def ship(body: ShipIn, request: Request,
               actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER))):
    """Create the Shiprocket order, assign the cheapest/recommended courier (or the one
    chosen), schedule pickup and fetch the label — in one go."""
    _require_live()
    db = request.app.state.db
    src = await _load_ref(db, body.kind, body.ref_id, actor)
    existing = await db.shipments.find_one({"kind": body.kind, "ref_id": body.ref_id,
                                            "status": {"$in": list(ACTIVE)}}, {"_id": 0})
    if existing:
        raise HTTPException(409, f"Already shipped (AWB {existing.get('awb') or 'pending'}).")
    ship_from = body.ship_from or src["ship_from"]
    pk = sr.pickup(ship_from)
    if not pk["location"]:
        raise HTTPException(503, "Pickup location is not set (SHIPROCKET_PICKUP_LOCATION).")
    if body.cod and (body.cod_amount or src["total"]) > src["total"] + 0.05:
        raise HTTPException(400, "Cash-on-delivery amount can't be more than the bill")

    client = sr.ShiprocketClient()
    attempt_no = await db.shipments.count_documents({"kind": body.kind, "ref_id": body.ref_id})
    sr_ref = src["ref"] if attempt_no == 0 else f"{src['ref']}-R{attempt_no}"
    shipment = {"id": gen_id(), "kind": body.kind, "ref_id": body.ref_id, "ref_no": src["ref"],
                "sr_ref": sr_ref, "ship_from": ship_from, "pickup_location": pk["location"],
                "to_city": body.address.city, "to_pincode": body.address.pincode,
                "to_name": body.address.name, "cod": body.cod,
                "weight_kg": body.weight_kg, "status": "creating", "events": [],
                "created_by": actor["id"], "created_by_name": actor.get("name"), "created_at": now_iso()}
    await db.shipments.insert_one(dict(shipment))
    try:
        payload = sr.build_order_payload(
            ref=sr_ref, date_iso=src["date"], pickup_location=pk["location"],
            address=body.address.model_dump(), items=src["items"],
            sub_total=(body.cod_amount if body.cod and body.cod_amount else src["total"]),
            cod=body.cod, weight_kg=body.weight_kg, length_cm=body.length_cm,
            breadth_cm=body.breadth_cm, height_cm=body.height_cm)
        created = await client.create_order(payload)
        upd = {"sr_order_id": created["sr_order_id"], "shipment_id": created["shipment_id"], "status": "created"}
        await db.shipments.update_one({"id": shipment["id"]}, {"$set": upd})
        awb = await client.assign_awb(created["shipment_id"], body.courier_id)
        upd.update({"awb": awb["awb"], "courier": awb["courier"], "courier_id": awb["courier_id"],
                    "status": "awb_assigned"})
        await db.shipments.update_one({"id": shipment["id"]}, {"$set": upd})
        try:
            pick = await client.request_pickup(created["shipment_id"])
            upd.update({"pickup_date": pick["pickup_date"], "status": "pickup_scheduled"})
        except sr.ShiprocketError as e:  # label still useful; pickup can be retried in Shiprocket
            upd["pickup_error"] = str(e)
        try:
            upd["label_url"] = await client.label(created["shipment_id"])
        except sr.ShiprocketError as e:
            upd["label_error"] = str(e)
        upd["updated_at"] = now_iso()
        await db.shipments.update_one({"id": shipment["id"]}, {"$set": upd})
    except sr.ShiprocketError as e:
        await db.shipments.update_one({"id": shipment["id"]}, {"$set": {"status": "failed", "error": str(e)}})
        raise HTTPException(502, str(e))
    coll = db.b2b_orders if body.kind == "b2b" else db.sales
    await coll.update_one({"id": body.ref_id}, {"$set": {
        "shipment": {"id": shipment["id"], "awb": upd.get("awb"), "courier": upd.get("courier"),
                     "status": upd["status"], "label_url": upd.get("label_url")}}})
    await audit(db, actor, "shipping.create", body.kind, body.ref_id,
                {"awb": upd.get("awb"), "courier": upd.get("courier"), "cod": body.cod})
    return {**shipment, **upd}


@router.get("/shipments")
async def list_shipments(request: Request, kind: Optional[str] = None, ref_id: Optional[str] = None,
                         limit: int = 50, actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER))):
    db = request.app.state.db
    q: dict = {}
    if kind in ("b2b", "sale"):
        q["kind"] = kind
    if ref_id:
        q["ref_id"] = ref_id[:64]
    if actor["role"] != ROLE_OWNER:
        q["kind"] = "sale"
    return await db.shipments.find(q, {"_id": 0}).sort("created_at", -1).limit(max(1, min(int(limit), 200))).to_list(200)


_STATUS_MAP = {"delivered": "delivered", "out for delivery": "out_for_delivery", "rto": "returned",
               "cancel": "cancelled", "in transit": "in_transit", "picked up": "in_transit",
               "shipped": "in_transit", "pickup scheduled": "pickup_scheduled"}


def _norm(status: Optional[str]) -> Optional[str]:
    s = (status or "").lower()
    for k, v in _STATUS_MAP.items():
        if k in s:
            return v
    return None


async def _apply_status(db, shp: dict, raw_status: Optional[str], extra: dict):
    norm = _norm(raw_status) or shp.get("status")
    upd = {"status": norm, "courier_status": raw_status, "updated_at": now_iso(), **extra}
    await db.shipments.update_one({"id": shp["id"]}, {"$set": upd,
        "$push": {"events": {"at": now_iso(), "status": raw_status}}})
    coll = db.b2b_orders if shp["kind"] == "b2b" else db.sales
    await coll.update_one({"id": shp["ref_id"]}, {"$set": {"shipment.status": norm}})
    if norm == "delivered" and shp["kind"] == "b2b":
        await db.b2b_orders.update_one({"id": shp["ref_id"], "delivered_at": None},
                                       {"$set": {"delivered_at": now_iso()}})


@router.post("/shipments/{sid}/refresh")
async def refresh(sid: str, request: Request,
                  actor: dict = Depends(require_roles(ROLE_OWNER, ROLE_STORE_MANAGER))):
    _require_live()
    db = request.app.state.db
    shp = await db.shipments.find_one({"id": sid[:64]}, {"_id": 0})
    if not shp or not shp.get("awb"):
        raise HTTPException(404, "Shipment not found or has no AWB yet")
    try:
        t = await sr.ShiprocketClient().track(shp["awb"])
    except sr.ShiprocketError as e:
        raise HTTPException(502, str(e))
    await _apply_status(db, shp, t["status"], {"edd": t.get("edd"), "track_url": t.get("track_url")})
    return await db.shipments.find_one({"id": shp["id"]}, {"_id": 0})


async def refresh_active(db, max_items: int = 50) -> dict:
    """Scheduler: update tracking for shipments still on the way (hourly)."""
    if sr.mode() != "live" or not sr.configured():
        return {"skipped": "shiprocket not live"}
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=55)).isoformat()
    rows = await db.shipments.find({"status": {"$in": list(ACTIVE)}, "awb": {"$ne": None},
                                    "$or": [{"updated_at": {"$lt": cutoff}}, {"updated_at": None}]},
                                   {"_id": 0}).limit(max_items).to_list(max_items)
    client, done, errors = sr.ShiprocketClient(), 0, 0
    for shp in rows:
        try:
            t = await client.track(shp["awb"])
            await _apply_status(db, shp, t["status"], {"edd": t.get("edd")})
            done += 1
        except sr.ShiprocketError:
            errors += 1
    return {"checked": done, "errors": errors}


@hook.post("/courier-updates")
async def courier_webhook(request: Request):
    """Shiprocket tracking webhook. Configure in Shiprocket: Settings > API > Webhooks,
    URL https://mynewdru.in/api/courier-updates, token = SHIPROCKET_WEBHOOK_SECRET.
    Always answers 200 for valid calls, as Shiprocket requires."""
    if not secret_matches(request.headers.get("x-api-key"), os.environ.get("SHIPROCKET_WEBHOOK_SECRET")):
        raise HTTPException(401, "Unauthorized")
    body = await request.json()
    awb = str(body.get("awb") or body.get("awb_code") or "")[:40]
    if not awb:
        return {"ok": True}
    db = request.app.state.db
    shp = await db.shipments.find_one({"awb": awb}, {"_id": 0})
    if shp:
        await _apply_status(db, shp, body.get("current_status") or body.get("shipment_status"),
                            {"edd": body.get("etd")})
    return {"ok": True}
