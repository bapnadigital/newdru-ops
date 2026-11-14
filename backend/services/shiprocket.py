"""Shiprocket courier client (apiv2.shiprocket.in).

Settings (Cloudflare secrets — never in code):
    SHIPROCKET_MODE              disabled | live
    SHIPROCKET_EMAIL             the Shiprocket *API user* email (Settings > API > Create API user)
    SHIPROCKET_PASSWORD          that API user's password
    SHIPROCKET_PICKUP_LOCATION   pickup location nickname exactly as in Shiprocket (e.g. "Bhiwandi")
    SHIPROCKET_PICKUP_PINCODE    pincode of that pickup location (for rate checks)
    SHIPROCKET_STORE_PICKUP_LOCATION / _PINCODE   optional second pickup for the store
    SHIPROCKET_WEBHOOK_SECRET    token Shiprocket sends as x-api-key on tracking webhooks

Never raises raw HTTP errors to callers; raises ShiprocketError with a plain message.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger("shiprocket")
BASE = "https://apiv2.shiprocket.in/v1/external"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
TOKEN_TTL = 9 * 24 * 3600  # Shiprocket tokens last 10 days; renew a day early


class ShiprocketError(Exception):
    pass


def mode() -> str:
    m = (os.environ.get("SHIPROCKET_MODE") or "disabled").lower()
    return m if m in ("disabled", "live") else "disabled"


def configured() -> bool:
    return bool(os.environ.get("SHIPROCKET_EMAIL") and os.environ.get("SHIPROCKET_PASSWORD"))


def pickup(ship_from: str = "BHIWANDI") -> Dict[str, Optional[str]]:
    if ship_from == "STORE" and os.environ.get("SHIPROCKET_STORE_PICKUP_LOCATION"):
        return {"location": os.environ.get("SHIPROCKET_STORE_PICKUP_LOCATION"),
                "pincode": os.environ.get("SHIPROCKET_STORE_PICKUP_PINCODE")}
    return {"location": os.environ.get("SHIPROCKET_PICKUP_LOCATION"),
            "pincode": os.environ.get("SHIPROCKET_PICKUP_PINCODE")}


class ShiprocketClient:
    _token: Optional[str] = None
    _token_at: float = 0.0
    _lock = asyncio.Lock()

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport)

    async def _auth(self) -> str:
        cls = type(self)
        async with cls._lock:
            if cls._token and time.time() - cls._token_at < TOKEN_TTL:
                return cls._token
            if not configured():
                raise ShiprocketError("Shiprocket API user is not set (SHIPROCKET_EMAIL / SHIPROCKET_PASSWORD).")
            async with self._client() as c:
                r = await c.post(f"{BASE}/auth/login", json={
                    "email": os.environ["SHIPROCKET_EMAIL"], "password": os.environ["SHIPROCKET_PASSWORD"]})
            if r.status_code != 200 or not r.json().get("token"):
                raise ShiprocketError(f"Shiprocket login failed (HTTP {r.status_code}). Check the API user email/password.")
            cls._token, cls._token_at = r.json()["token"], time.time()
            return cls._token

    async def _call(self, method: str, path: str, **kw) -> Any:
        for attempt in (1, 2):
            token = await self._auth()
            async with self._client() as c:
                r = await c.request(method, f"{BASE}{path}",
                                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, **kw)
            if r.status_code == 401 and attempt == 1:
                type(self)._token = None
                continue
            try:
                data = r.json()
            except ValueError:
                data = {}
            if r.status_code >= 400:
                msg = data.get("message") if isinstance(data, dict) else None
                if isinstance(data, dict) and data.get("errors"):
                    msg = f"{msg or ''} {data['errors']}".strip()
                raise ShiprocketError(f"Shiprocket: {msg or f'HTTP {r.status_code}'}")
            return data
        raise ShiprocketError("Shiprocket authentication failed.")

    # ---------- API ----------
    async def rates(self, pickup_pincode: str, delivery_pincode: str, weight_kg: float, cod: bool) -> dict:
        data = await self._call("GET", "/courier/serviceability/", params={
            "pickup_postcode": pickup_pincode, "delivery_postcode": delivery_pincode,
            "weight": max(0.05, float(weight_kg)), "cod": 1 if cod else 0})
        d = (data or {}).get("data") or {}
        couriers = [{
            "courier_id": c.get("courier_company_id"), "name": c.get("courier_name"),
            "rate": c.get("rate") or c.get("freight_charge"), "etd": c.get("etd"),
            "days": c.get("estimated_delivery_days"), "rating": c.get("rating"),
        } for c in d.get("available_courier_companies") or []]
        couriers.sort(key=lambda c: (float(c["rate"] or 1e9)))
        return {"recommended_courier_id": d.get("recommended_courier_company_id"), "couriers": couriers}

    async def create_order(self, payload: dict) -> dict:
        data = await self._call("POST", "/orders/create/adhoc", json=payload)
        if not data.get("shipment_id"):
            raise ShiprocketError(f"Shiprocket did not create the shipment: {data.get('message') or data}")
        return {"sr_order_id": data.get("order_id"), "shipment_id": data.get("shipment_id"), "status": data.get("status")}

    async def assign_awb(self, shipment_id: int, courier_id: Optional[int] = None) -> dict:
        body: Dict[str, Any] = {"shipment_id": shipment_id}
        if courier_id:
            body["courier_id"] = courier_id
        data = await self._call("POST", "/courier/assign/awb", json=body)
        resp = ((data or {}).get("response") or {}).get("data") or {}
        if not resp.get("awb_code"):
            raise ShiprocketError(f"Could not assign a courier: {data.get('message') or resp or data}")
        return {"awb": resp.get("awb_code"), "courier": resp.get("courier_name"),
                "courier_id": resp.get("courier_company_id")}

    async def request_pickup(self, shipment_id: int) -> dict:
        data = await self._call("POST", "/courier/generate/pickup", json={"shipment_id": [shipment_id]})
        resp = (data or {}).get("response") or {}
        return {"pickup_date": resp.get("pickup_scheduled_date"), "token": resp.get("pickup_token_number")}

    async def label(self, shipment_id: int) -> Optional[str]:
        data = await self._call("POST", "/courier/generate/label", json={"shipment_id": [shipment_id]})
        return (data or {}).get("label_url")

    async def track(self, awb: str) -> dict:
        data = await self._call("GET", f"/courier/track/awb/{awb}")
        td = (data or {}).get("tracking_data") or {}
        track = (td.get("shipment_track") or [{}])[0]
        return {"status": track.get("current_status"), "delivered_date": track.get("delivered_date"),
                "edd": track.get("edd") or td.get("etd"), "track_url": td.get("track_url")}


def build_order_payload(*, ref: str, date_iso: str, pickup_location: str, address: dict,
                        items: List[dict], sub_total: float, cod: bool,
                        weight_kg: float, length_cm: float, breadth_cm: float, height_cm: float) -> dict:
    return {
        "order_id": ref,
        "order_date": date_iso[:16].replace("T", " "),
        "pickup_location": pickup_location,
        "billing_customer_name": address["name"][:50],
        "billing_last_name": "",
        "billing_address": address["line1"][:190],
        "billing_address_2": (address.get("line2") or "")[:190],
        "billing_city": address["city"],
        "billing_pincode": str(address["pincode"]),
        "billing_state": address["state"],
        "billing_country": "India",
        "billing_email": address.get("email") or "",
        "billing_phone": str(address["phone"])[-10:],
        "shipping_is_billing": True,
        "order_items": [{"name": i["name"][:100], "sku": i["sku"], "units": int(i["quantity"]),
                         "selling_price": round(float(i["unit_price"]), 2),
                         "hsn": i.get("hsn") or ""} for i in items],
        "payment_method": "COD" if cod else "Prepaid",
        "sub_total": round(float(sub_total), 2),
        "length": max(1, float(length_cm)), "breadth": max(1, float(breadth_cm)),
        "height": max(1, float(height_cm)), "weight": max(0.05, float(weight_kg)),
    }
