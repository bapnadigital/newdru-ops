"""Shiprocket shipping: one-click ship of a wholesale order, tracking webhook, safeguards."""
import importlib
import json
import os
import sys
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OWNER_PW = "Owner-Test-Pass-2026"
SEED_PW = "Seed-Test-Pass-2026"


def fake_sr(calls):
    def h(req: httpx.Request):
        calls.append(req)
        p = req.url.path
        if p.endswith("/auth/login"):
            return httpx.Response(200, json={"token": "srtok"})
        assert req.headers["authorization"] == "Bearer srtok"
        if p.endswith("/orders/create/adhoc"):
            body = json.loads(req.content)
            assert body["pickup_location"] == "Bhiwandi" and body["billing_pincode"] == "400071"
            return httpx.Response(200, json={"order_id": 111, "shipment_id": 222, "status": "NEW"})
        if p.endswith("/courier/assign/awb"):
            return httpx.Response(200, json={"awb_assign_status": 1, "response": {"data": {
                "awb_code": "AWB123", "courier_name": "Delhivery", "courier_company_id": 7}}})
        if p.endswith("/courier/generate/pickup"):
            return httpx.Response(200, json={"response": {"pickup_scheduled_date": "2026-11-16"}})
        if p.endswith("/courier/generate/label"):
            return httpx.Response(200, json={"label_created": 1, "label_url": "https://example.com/label.pdf"})
        if "/courier/serviceability" in p:
            return httpx.Response(200, json={"data": {"recommended_courier_company_id": 7,
                "available_courier_companies": [{"courier_company_id": 9, "courier_name": "Blue", "rate": 120},
                                                {"courier_company_id": 7, "courier_name": "Delhivery", "rate": 80}]}})
        return httpx.Response(404)
    return httpx.MockTransport(h)


@pytest.fixture()
def app(monkeypatch):
    import motor.motor_asyncio
    from mongomock_motor import AsyncMongoMockClient
    env = dict(MONGO_URL="mongodb://x", DB_NAME=f"ship_{uuid.uuid4().hex[:8]}", JWT_SECRET="x" * 48,
               ADMIN_PASSWORD=OWNER_PW, SEED_PASSWORD=SEED_PW, APP_ENV="production",
               SHIPROCKET_MODE="live", SHIPROCKET_EMAIL="api@example.com", SHIPROCKET_PASSWORD="test-only",
               SHIPROCKET_PICKUP_LOCATION="Bhiwandi", SHIPROCKET_PICKUP_PINCODE="421302",
               SHIPROCKET_WEBHOOK_SECRET="hook-test-secret")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(motor.motor_asyncio, "AsyncIOMotorClient", AsyncMongoMockClient)
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    from services import shiprocket as sr
    calls = []
    real = httpx.AsyncClient
    monkeypatch.setattr(sr.httpx, "AsyncClient",
                        lambda *a, **k: real(*a, **{**k, "transport": fake_sr(calls)}))
    sr.ShiprocketClient._token = None
    with TestClient(server.app, base_url="https://t") as c:
        yield c, server, calls


def bearer(c, email, pw):
    r = c.post("/api/auth/login", json={"email": email, "password": pw}); assert r.status_code == 200
    c.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['token']}"}


ADDR = {"name": "Retail Shop", "phone": "+91 98765 43210", "line1": "12 Market Road", "city": "Mumbai",
        "state": "Maharashtra", "pincode": "400071"}


def test_ship_b2b_order_end_to_end(app):
    c, server, calls = app
    async def seed():
        await server.db.b2b_orders.insert_one({"id": "o1", "order_no": "B2B-0001", "status": "confirmed",
            "ship_from": "BHIWANDI", "total": 1000.0, "created_at": "2026-11-15T10:00:00+00:00",
            "items": [{"name": "Thing", "sku": "SKU-1", "quantity": 2, "unit_price": 500, "line_total": 1000}]})
    c.portal.call(seed)
    owner = bearer(c, "admin@newdru.com", OWNER_PW)
    rates = c.post("/api/shipping/rates", json={"delivery_pincode": "400071", "weight_kg": 2}, headers=owner).json()
    assert rates["couriers"][0]["name"] == "Delhivery"          # cheapest first
    r = c.post("/api/shipping/ship", json={"kind": "b2b", "ref_id": "o1", "address": ADDR, "weight_kg": 2}, headers=owner)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["awb"] == "AWB123" and d["status"] == "pickup_scheduled" and d["label_url"]
    again = c.post("/api/shipping/ship", json={"kind": "b2b", "ref_id": "o1", "address": ADDR, "weight_kg": 2}, headers=owner)
    assert again.status_code == 409                               # never shipped twice
    # webhook: wrong token refused, right token updates status
    assert c.post("/api/courier-updates", json={"awb": "AWB123", "current_status": "DELIVERED"}).status_code == 401
    ok = c.post("/api/courier-updates", json={"awb": "AWB123", "current_status": "DELIVERED"},
                headers={"x-api-key": "hook-test-secret"})
    assert ok.status_code == 200
    async def order():
        return await server.db.b2b_orders.find_one({"id": "o1"})
    o = c.portal.call(order)
    assert o["shipment"]["status"] == "delivered" and o["delivered_at"]


def test_store_manager_cannot_ship_wholesale(app):
    c, server, _ = app
    store = bearer(c, "store@newdru.com", SEED_PW)
    r = c.post("/api/shipping/ship", json={"kind": "b2b", "ref_id": "x", "address": ADDR, "weight_kg": 1}, headers=store)
    assert r.status_code == 403


def test_bad_pincode_rejected(app):
    c, _, _ = app
    owner = bearer(c, "admin@newdru.com", OWNER_PW)
    bad = {**ADDR, "pincode": "12"}
    r = c.post("/api/shipping/ship", json={"kind": "sale", "ref_id": "x", "address": bad, "weight_kg": 1}, headers=owner)
    assert r.status_code == 422


def test_goods_in_rejects_negative(app):
    c, server, _ = app
    async def seed():
        await server.db.products.insert_one({"id": "p1", "sku": "SKU-1", "name": "Thing", "units_per_carton": 10})
    c.portal.call(seed)
    wh = bearer(c, "warehouse@newdru.com", SEED_PW)
    r = c.post("/api/inventory/receive", json={"location_code": "BHIWANDI", "lines": [{"sku": "SKU-1", "cartons": -5}]}, headers=wh)
    assert r.status_code == 400
