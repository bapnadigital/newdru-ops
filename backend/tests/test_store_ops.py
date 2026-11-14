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


def test_b2b_dispatch_after_invoice_moves_stock_once(app):
    c, server = app
    seed_product(c, server, "SKU-9", 0)
    async def stock():
        await server.db.inventory.insert_one({"product_id": "p-SKU-9", "location_code": "BHIWANDI", "quantity": 50})
        await server.db.b2b_orders.insert_one({"id": "o1", "order_no": "SO-1", "customer_id": "c1", "ship_from": "BHIWANDI",
            "items": [{"product_id": "p-SKU-9", "quantity": 5}], "total": 500.0, "status": "confirmed",
            "dispatched_at": None, "invoice_no": None, "paid_amount": 0.0, "payment_terms_days": 30})
    c.portal.call(stock)
    owner = bearer(c, "admin@newdru.com", OWNER_PW)
    assert c.post("/api/b2b/orders/o1/invoice", headers=owner).status_code == 200
    r = c.post("/api/b2b/orders/o1/dispatch", headers=owner)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "invoiced"            # invoice status kept
    assert c.post("/api/b2b/orders/o1/dispatch", headers=owner).status_code == 400  # not twice
    async def qty():
        return (await server.db.inventory.find_one({"product_id": "p-SKU-9", "location_code": "BHIWANDI"}))["quantity"]
    assert c.portal.call(qty) == 45


def _transfer(c, server, qty_sent):
    async def go():
        await server.db.inventory.update_one({"product_id": "p-SKU-T", "location_code": "BHIWANDI"},
                                             {"$set": {"quantity": 100}}, upsert=True)
        await server.db.transfers.insert_one({"id": "t1", "from_location": "BHIWANDI", "to_location": "STORE",
            "status": "approved", "items": [{"product_id": "p-SKU-T", "sku": "SKU-T", "name": "T", "requested_qty": qty_sent}]})
    c.portal.call(go)


def _q(c, server, loc):
    async def go():
        d = await server.db.inventory.find_one({"product_id": "p-SKU-T", "location_code": loc})
        return (d or {}).get("quantity", 0)
    return c.portal.call(go)


def test_transfer_cannot_over_receive_and_records_shortage(app):
    c, server = app
    seed_product(c, server, "SKU-T", 0)
    _transfer(c, server, 10)
    owner = bearer(c, "admin@newdru.com", OWNER_PW)
    assert c.post("/api/stock/transfers/t1/dispatch", json={"items": [{"product_id": "p-SKU-T", "dispatched_qty": 999}]},
                  headers=owner).status_code == 200
    assert _q(c, server, "BHIWANDI") == 90                      # capped at requested 10
    assert c.post("/api/stock/transfers/t1/dispatch", json={}, headers=owner).status_code == 400
    c.post("/api/stock/transfers/t1/receive", json={"items": [{"product_id": "p-SKU-T", "received_qty": 50}]}, headers=owner)
    assert _q(c, server, "STORE") == 10                         # capped at what was sent
    assert c.post("/api/stock/transfers/t1/receive", json={}, headers=owner).status_code == 400


def test_cancel_dispatched_transfer_returns_stock(app):
    c, server = app
    seed_product(c, server, "SKU-T", 0)
    _transfer(c, server, 10)
    owner = bearer(c, "admin@newdru.com", OWNER_PW)
    c.post("/api/stock/transfers/t1/dispatch", json={}, headers=owner)
    assert _q(c, server, "BHIWANDI") == 90
    assert c.post("/api/stock/transfers/t1/cancel", headers=owner).status_code == 200
    assert _q(c, server, "BHIWANDI") == 100


def test_returns_credit_note_restock_and_limits(app):
    c, server = app
    seed_product(c, server, "SKU-R", 10)
    store = bearer(c, "store@newdru.com", SEED_PW)
    sale = {"items": [{"product_id": "p-SKU-R", "sku": "SKU-R", "name": "Thing", "quantity": 3,
                       "unit_price": 100, "gst_rate": 18, "discount": 0}],
            "payments": [{"method": "cash", "amount": 200}], "cart_discount": 100}
    s = c.post("/api/pos/sales", json=sale, headers=store)
    assert s.status_code == 200, s.text
    sid = s.json()["id"]
    r = c.post("/api/pos/returns", json={"sale_id": sid, "items": [{"product_id": "p-SKU-R", "quantity": 2}],
                                         "refund_method": "cash", "reason": "size issue"}, headers=store)
    assert r.status_code == 200, r.text
    cn = r.json()
    assert cn["credit_note_no"].startswith("NW-CN-")
    assert abs(cn["refund_total"] - 200 * 2 / 3) < 0.05      # bill discount shared fairly
    async def qty():
        return (await server.db.inventory.find_one({"product_id": "p-SKU-R", "location_code": "STORE"}))["quantity"]
    assert c.portal.call(qty) == 9                           # 10 - 3 + 2
    over = c.post("/api/pos/returns", json={"sale_id": sid, "items": [{"product_id": "p-SKU-R", "quantity": 2}],
                                            "reason": "again"}, headers=store)
    assert over.status_code == 400                           # only 1 left
    shift = c.get("/api/pos/shift/report", headers=store).json()
    assert shift["refunds"]["cash"] == cn["refund_total"]


def test_cashier_cannot_do_returns(app):
    c, server = app
    async def add_cashier():
        from auth import hash_password
        await server.db.users.insert_one({"id": "cash1", "email": "cashier@newdru.com", "name": "C", "role": "cashier",
                                          "active": True, "password_hash": hash_password(SEED_PW)})
    c.portal.call(add_cashier)
    cashier = bearer(c, "cashier@newdru.com", SEED_PW)
    r = c.post("/api/pos/returns", json={"sale_id": "x", "items": [{"product_id": "p", "quantity": 1}],
                                         "reason": "test"}, headers=cashier)
    assert r.status_code == 403


def test_goods_in_retry_does_not_double_stock(app):
    c, server = app
    seed_product(c, server, "SKU-G", 0)
    wh = bearer(c, "warehouse@newdru.com", SEED_PW)
    body = {"location_code": "BHIWANDI", "client_ref": "abc-123", "lines": [{"sku": "SKU-G", "units": 7}]}
    assert c.post("/api/inventory/receive", json=body, headers=wh).status_code == 200
    again = c.post("/api/inventory/receive", json=body, headers=wh)
    assert again.json()["duplicate"] is True
    async def qty():
        return (await server.db.inventory.find_one({"product_id": "p-SKU-G", "location_code": "BHIWANDI"}))["quantity"]
    assert c.portal.call(qty) == 7



def test_price_comes_from_product_list_and_cashier_cannot_discount(app):
    c, server = app
    seed_product(c, server, "SKU-P", 5)          # sell_price 100
    async def add_cashier():
        from auth import hash_password
        await server.db.users.insert_one({"id": "cash2", "email": "till@newdru.com", "name": "T", "role": "cashier",
                                          "active": True, "password_hash": hash_password(SEED_PW)})
    c.portal.call(add_cashier)
    cashier = bearer(c, "till@newdru.com", SEED_PW)
    cheap = _sale("SKU-P", 10, {"method": "cash", "amount": 10})   # tries to bill at Rs 10
    r = c.post("/api/pos/sales", json=cheap, headers=cashier)
    assert r.status_code == 400 and "does not match" in r.text     # real price is 100
    ok = c.post("/api/pos/sales", json=_sale("SKU-P", 10, {"method": "cash", "amount": 100}), headers=cashier)
    assert ok.status_code == 200 and ok.json()["total"] == 100
    disc = _sale("SKU-P", 100, {"method": "cash", "amount": 90})
    disc["cart_discount"] = 10
    assert c.post("/api/pos/sales", json=disc, headers=cashier).status_code == 403
