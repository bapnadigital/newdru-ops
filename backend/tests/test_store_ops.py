"""Store operations: stock counts and Pine Labs-verified card bills."""
import importlib
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OWNER_PW = "Owner-Test-Pass-2026"
SEED_PW = "Seed-Test-Pass-2026"


@pytest.fixture()
def app(monkeypatch):
    import motor.motor_asyncio
    from mongomock_motor import AsyncMongoMockClient
    monkeypatch.setenv("MONGO_URL", "mongodb://x")
    monkeypatch.setenv("DB_NAME", f"ops_{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("JWT_SECRET", "x" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD", OWNER_PW)
    monkeypatch.setenv("SEED_PASSWORD", SEED_PW)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(motor.motor_asyncio, "AsyncIOMotorClient", AsyncMongoMockClient)
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app, base_url="https://t") as c:
        yield c, server


def bearer(c, email, pw):
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    c.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def seed_product(c, server, sku="SKU-1", store_qty=10):
    db = server.db
    async def go():
        await db.products.insert_one({"id": "p-" + sku, "sku": sku, "name": "Thing " + sku, "barcode": "890" + sku,
                                      "sell_price": 100.0, "gst_rate": 18, "cogs_per_unit": 0})
        await db.inventory.insert_one({"product_id": "p-" + sku, "location_code": "STORE", "quantity": store_qty})
    c.portal.call(go)


def test_blind_stock_count_records_difference(app):
    c, server = app
    seed_product(c, server, "SKU-1", 10)
    store = bearer(c, "store@newdru.com", SEED_PW)
    sheet = c.get("/api/inventory/count-sheet?location_code=STORE", headers=store).json()
    assert "quantity" not in sheet["products"][0]          # blind count
    r = c.post("/api/inventory/count", json={"location_code": "STORE", "note": "Sunday count",
                                             "lines": [{"sku": "SKU-1", "counted": 8}]}, headers=store)
    assert r.status_code == 200
    assert r.json()["items_with_difference"] == 1 and "lines" not in r.json()
    owner = bearer(c, "admin@newdru.com", OWNER_PW)
    counts = c.get("/api/inventory/counts", headers=owner).json()
    assert counts[0]["units_missing"] == 2
    async def qty():
        return (await server.db.inventory.find_one({"product_id": "p-SKU-1", "location_code": "STORE"}))["quantity"]
    assert c.portal.call(qty) == 8
    wh = bearer(c, "warehouse@newdru.com", SEED_PW)
    assert c.post("/api/inventory/count", json={"location_code": "STORE", "lines": [{"sku": "SKU-1", "counted": 1}]},
                  headers=wh).status_code == 403


def _sale(sku, amount, payment):
    return {"items": [{"product_id": "p-" + sku, "sku": sku, "name": "Thing", "quantity": 1,
                       "unit_price": amount, "gst_rate": 18, "discount": 0}],
            "payments": [payment], "cart_discount": 0}


def test_live_terminal_requires_approved_ptr(app, monkeypatch):
    c, server = app
    seed_product(c, server, "SKU-2", 5)
    monkeypatch.setenv("PINELABS_MODE", "production")
    store = bearer(c, "store@newdru.com", SEED_PW)
    # Card without a terminal reference is refused
    r = c.post("/api/pos/sales", json=_sale("SKU-2", 100, {"method": "card", "amount": 100}), headers=store)
    assert r.status_code == 400 and "Pine Labs" in r.text
    # Approved terminal txn works once, and stock goes down
    async def add_txn():
        await server.db.pinelabs_txns.insert_one({"ptr_id": "PTR1", "status": "APPROVED", "amount_paise": 10000,
                                                  "rrn": "R1", "masked_pan": "XXXX1234"})
    c.portal.call(add_txn)
    ok = c.post("/api/pos/sales", json=_sale("SKU-2", 100, {"method": "card", "amount": 100, "ptr_id": "PTR1"}), headers=store)
    assert ok.status_code == 200, ok.text
    assert ok.json()["payments"][0]["rrn"] == "R1"
    again = c.post("/api/pos/sales", json=_sale("SKU-2", 100, {"method": "card", "amount": 100, "ptr_id": "PTR1"}), headers=store)
    assert again.status_code == 400
    async def qty():
        return (await server.db.inventory.find_one({"product_id": "p-SKU-2", "location_code": "STORE"}))["quantity"]
    assert c.portal.call(qty) == 4
