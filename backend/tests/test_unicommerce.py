"""Unicommerce sync tests with a fake Unicommerce server (no network)."""
import asyncio
import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def fake_uniware(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/oauth/token":
            assert request.url.params["client_id"] == "my-trusted-client"
            return httpx.Response(200, json={"access_token": "tok-1", "refresh_token": "ref-1",
                                             "expires_in": 3600, "token_type": "bearer"})
        assert request.headers["authorization"] == "bearer tok-1"
        if request.url.path.endswith("/inventorySnapshot/get"):
            assert request.headers["facility"] == "AMZFBA01"
            body = json.loads(request.content)
            return httpx.Response(200, json={"successful": True, "inventorySnapshots": [
                {"itemTypeSKU": s, "inventory": 7 if s == "SKU-A" else 0, "openSale": 1,
                 "inventoryBlocked": 0, "putawayPending": 0, "pendingStockTransfer": 0}
                for s in body["itemTypeSKUs"]] + [{"itemTypeSKU": "NOT-IN-APP", "inventory": 3}]})
        if request.url.path.endswith("/saleOrder/search"):
            return httpx.Response(200, json={"successful": True, "totalRecords": 2, "elements": [
                {"code": "SO1", "displayOrderCode": "402-1", "channel": "AMAZON_IN", "status": "COMPLETE", "created": 1},
                {"code": "SO2", "displayOrderCode": "OD-2", "channel": "FLIPKART", "status": "PROCESSING", "created": 1},
            ]})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("UNICOMMERCE_MODE", "live")
    monkeypatch.setenv("UNICOMMERCE_TENANT", "newdru")
    monkeypatch.setenv("UNICOMMERCE_USER", "api-user")
    monkeypatch.setenv("UNICOMMERCE_PASSWORD", "test-only")
    monkeypatch.setenv("UNICOMMERCE_FACILITIES", "AMAZON_FC=AMZFBA01")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_inventory_and_orders_sync(env):
    from mongomock_motor import AsyncMongoMockClient
    from services import unicommerce as uc
    from services import unicommerce_sync as ucs

    db = AsyncMongoMockClient()["uc_test"]

    async def go():
        await db.products.insert_many([{"id": "p1", "sku": "SKU-A"}, {"id": "p2", "sku": "SKU-B"}])
        await db.inventory.insert_one({"product_id": "p2", "location_code": "AMAZON_FC", "quantity": 0})
        calls = []
        client = uc.UnicommerceClient.from_env(transport=fake_uniware(calls))
        inv = await ucs.sync_inventory(db, client)
        a = await db.inventory.find_one({"product_id": "p1", "location_code": "AMAZON_FC"})
        moves = await db.stock_movements.count_documents({"movement_type": "fc_sync"})
        orders = await ucs.sync_orders(db, client, since_minutes=60)
        # Only one login for both jobs (token reused)
        logins = [c for c in calls if c.url.path == "/oauth/token"]
        stored = await db.unicommerce_orders.find_one({"code": "SO1"})
        return inv, a, moves, orders, logins, stored

    inv, a, moves, orders, logins, stored = run(go())
    loc = inv["locations"]["AMAZON_FC"]
    assert a["quantity"] == 7
    assert loc["changed"] == 1 and loc["unchanged"] == 1
    assert loc["unknown_skus"] == ["NOT-IN-APP"]
    assert moves == 1
    assert orders == {"received": 2, "new": 2, "updated": 0}
    assert len(logins) == 1
    assert "notificationMobile" not in stored and "billingAddress" not in stored


def test_unmapped_locations_never_touched(env, monkeypatch):
    from mongomock_motor import AsyncMongoMockClient
    from services import unicommerce as uc
    from services import unicommerce_sync as ucs
    db = AsyncMongoMockClient()["uc_test2"]

    async def go():
        await db.products.insert_one({"id": "p1", "sku": "SKU-A"})
        await db.inventory.insert_one({"product_id": "p1", "location_code": "STORE", "quantity": 42})
        client = uc.UnicommerceClient.from_env(transport=fake_uniware([]))
        await ucs.sync_inventory(db, client)
        return await db.inventory.find_one({"product_id": "p1", "location_code": "STORE"})

    assert run(go())["quantity"] == 42


def test_bad_tenant_rejected():
    from services import unicommerce as uc
    with pytest.raises(uc.UnicommerceError):
        uc.UnicommerceClient("evil.example.com/x", "u", "p")


def test_cron_endpoint_needs_secret(monkeypatch):
    import importlib
    import uuid
    import motor.motor_asyncio
    from fastapi.testclient import TestClient
    from mongomock_motor import AsyncMongoMockClient
    monkeypatch.setenv("MONGO_URL", "mongodb://x")
    monkeypatch.setenv("DB_NAME", f"t_{uuid.uuid4().hex[:6]}")
    monkeypatch.setenv("JWT_SECRET", "x" * 48)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CRON_SECRET", "cron-test-secret-value")
    monkeypatch.setenv("UNICOMMERCE_MODE", "disabled")
    monkeypatch.setattr(motor.motor_asyncio, "AsyncIOMotorClient", AsyncMongoMockClient)
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app, base_url="https://t") as c:
        assert c.post("/api/internal/cron").status_code == 401
        assert c.post("/api/internal/cron", headers={"X-Cron-Token": "wrong"}).status_code == 401
        r = c.post("/api/internal/cron", headers={"X-Cron-Token": "cron-test-secret-value"})
        assert r.status_code == 200 and r.json()["unicommerce"]["skipped"]


def fake_uniware_push(calls, current):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        if request.url.path.endswith("/inventorySnapshot/get"):
            body = json.loads(request.content)
            return httpx.Response(200, json={"successful": True, "inventorySnapshots": [
                {"itemTypeSKU": s, "inventory": current[s]} for s in body["itemTypeSKUs"] if s in current]})
        if request.url.path.endswith("/inventory/adjust/bulk"):
            body = json.loads(request.content)
            return httpx.Response(200, json={"successful": True, "inventoryAdjustmentResponses": [
                {"successful": True, "errors": []} for _ in body["inventoryAdjustments"]]})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_push_preview_and_push(monkeypatch, env):
    from mongomock_motor import AsyncMongoMockClient
    from services import unicommerce as uc
    from services import unicommerce_sync as ucs
    monkeypatch.setenv("UNICOMMERCE_FACILITIES", "")
    monkeypatch.setenv("UNICOMMERCE_PUSH_LOCATION", "BHIWANDI")
    monkeypatch.setenv("UNICOMMERCE_PUSH_FACILITY", "bapnadigital")
    db = AsyncMongoMockClient()["uc_push"]
    current = {"SHUMASK_GlowSkinPro": 0, "SHUMASK_GlowSkinPro-4": 0,
               "SHUFA-Gold": 0, "SHUFA-White": 0}

    async def go():
        await db.products.insert_many([
            {"id": "m", "sku": "SHUMASK-COLLAGEN", "unicommerce_skus": [
                {"sku": "SHUMASK_GlowSkinPro", "units": 1}, {"sku": "SHUMASK_GlowSkinPro-4", "units": 4}]},
            {"id": "f", "sku": "SHUFA-VACUUM", "unicommerce_skus": [
                {"sku": "SHUFA-Gold", "units": 1}, {"sku": "SHUFA-White", "units": 1}]},
        ])
        await db.inventory.insert_many([
            {"product_id": "m", "location_code": "BHIWANDI", "quantity": 10},
            {"product_id": "f", "location_code": "BHIWANDI", "quantity": 5}])
        calls = []
        client = uc.UnicommerceClient.from_env(transport=fake_uniware_push(calls, current))
        plan = await ucs.push_plan(db, client)
        writes_before = [c for c in calls if c.url.path.endswith("/adjust/bulk")]
        blocked = None
        try:
            await ucs.push_inventory(db, client)
        except uc.UnicommerceError as e:
            blocked = str(e)
        monkeypatch.setenv("UNICOMMERCE_PUSH_ENABLED", "true")
        res = await ucs.push_inventory(db, client)
        sent = [json.loads(c.content) for c in calls if c.url.path.endswith("/adjust/bulk")]
        return plan, writes_before, blocked, res, sent

    plan, writes_before, blocked, res, sent = run(go())
    targets = {l["unicommerce_sku"]: l["will_set_to"] for l in plan["lines"]}
    assert targets == {"SHUMASK_GlowSkinPro": 10, "SHUMASK_GlowSkinPro-4": 2}
    assert plan["skipped"][0]["product_sku"] == "SHUFA-VACUUM"   # colours can't be split
    assert writes_before == []                                     # preview never writes
    assert "switched off" in blocked                               # push needs explicit enable
    assert res["sent"] == 2 and res["ok"] == 2
    adj = sent[0]["inventoryAdjustments"]
    assert {a["adjustmentType"] for a in adj} == {"REPLACE"}
    assert all(a["facilityCode"] == "bapnadigital" for a in adj)


def test_mapping_import_skips_unconfirmed_rows(monkeypatch):
    import importlib, uuid, sys, motor.motor_asyncio
    from mongomock_motor import AsyncMongoMockClient
    from fastapi.testclient import TestClient
    monkeypatch.setenv("MONGO_URL", "mongodb://x"); monkeypatch.setenv("DB_NAME", f"m_{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("JWT_SECRET", "x" * 48); monkeypatch.setenv("ADMIN_PASSWORD", "Owner-Test-Pass-2026")
    monkeypatch.setenv("SEED_PASSWORD", "Seed-Test-Pass-2026"); monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(motor.motor_asyncio, "AsyncIOMotorClient", AsyncMongoMockClient)
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app, base_url="https://t") as c:
        async def seed():
            await server.db.products.insert_many([{"id": "a", "sku": "A1", "name": "A"}, {"id": "b", "sku": "B1", "name": "B"}])
        c.portal.call(seed)
        tok = c.post("/api/auth/login", json={"email": "admin@newdru.com", "password": "Owner-Test-Pass-2026"}).json()["token"]
        c.cookies.clear()
        csv_text = "app_sku,unicommerce_sku,units,confidence,note\nA1,UA,1,high,\nB1,UB,1,check,guess\n"
        r = c.post("/api/fc-sync/mapping/import", files={"file": ("m.csv", csv_text, "text/csv")},
                   headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text
        assert r.json()["updated_products"] == 1 and r.json()["skipped_unconfirmed"] == 1
