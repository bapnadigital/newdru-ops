"""Security regression tests. Run offline with an in-memory MongoDB:

    cd backend && pip install -r requirements-dev.txt && pytest tests/test_security.py -q
"""
import importlib
import uuid
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OWNER_PW = "Owner-Test-Pass-2026"
SEED_PW = "Seed-Test-Pass-2026"


@pytest.fixture()
def app_client(monkeypatch):
    from mongomock_motor import AsyncMongoMockClient

    monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
    monkeypatch.setenv("DB_NAME", f"newdru_test_{uuid.uuid4().hex[:8]}")  # fresh DB per test
    monkeypatch.setenv("JWT_SECRET", "x" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD", OWNER_PW)
    monkeypatch.setenv("SEED_PASSWORD", SEED_PW)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("PINELABS_WEBHOOK_SECRET", raising=False)
    import motor.motor_asyncio
    monkeypatch.setattr(motor.motor_asyncio, "AsyncIOMotorClient", AsyncMongoMockClient)
    if "server" in sys.modules:
        del sys.modules["server"]
    server = importlib.import_module("server")
    with TestClient(server.app, base_url="https://testserver") as c:
        yield c, server


def login(c, email, pw, ip="1.1.1.1"):
    return c.post("/api/auth/login", json={"email": email, "password": pw},
                  headers={"CF-Connecting-IP": ip})


def bearer(c, email, pw):
    r = login(c, email, pw)
    assert r.status_code == 200, r.text
    c.cookies.clear()  # use the Bearer token only, so several users can be tested at once
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_docs_hidden_in_production(app_client):
    c, _ = app_client
    assert c.get("/api/docs").status_code == 404
    assert c.get("/api/openapi.json").status_code == 404


def test_no_wildcard_cors(app_client):
    c, _ = app_client
    r = c.get("/api/health", headers={"Origin": "https://evil.example", "Cookie": "a=b"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_security_headers(app_client):
    c, _ = app_client
    r = c.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_seeded_passwords_not_reset_on_restart(app_client):
    c, server = app_client
    owner = bearer(c, "admin@newdru.com", OWNER_PW)
    users = c.get("/api/users", headers=owner).json()
    store = next(u for u in users if u["email"] == "store@newdru.com")
    new_pw = "Brand-New-Store-Pass-1"
    assert c.patch(f"/api/users/{store['id']}", json={"password": new_pw}, headers=owner).status_code == 200
    # Simulate a restart: run the seeding routine again.
    c.portal.call(server.seed_admin_and_indexes)
    assert login(c, "store@newdru.com", new_pw).status_code == 200
    assert login(c, "store@newdru.com", SEED_PW, ip="2.2.2.2").status_code == 401


def test_password_change_revokes_old_sessions(app_client):
    c, _ = app_client
    owner = bearer(c, "admin@newdru.com", OWNER_PW)
    store_hdr = bearer(c, "store@newdru.com", SEED_PW)
    assert c.get("/api/auth/me", headers=store_hdr).status_code == 200
    users = c.get("/api/users", headers=owner).json()
    store = next(u for u in users if u["email"] == "store@newdru.com")
    c.patch(f"/api/users/{store['id']}", json={"password": "Another-Pass-2026"}, headers=owner)
    assert c.get("/api/auth/me", headers=store_hdr).status_code == 401


def test_short_password_rejected(app_client):
    c, _ = app_client
    owner = bearer(c, "admin@newdru.com", OWNER_PW)
    r = c.post("/api/users", json={"email": "x@newdru.com", "name": "X", "role": "cashier",
                                   "password": "short"}, headers=owner)
    assert r.status_code == 422


def test_lockout_cannot_be_dodged_with_fake_forwarded_for(app_client):
    c, _ = app_client
    for i in range(6):
        c.post("/api/auth/login", json={"email": "admin@newdru.com", "password": "wrong-password"},
               headers={"X-Forwarded-For": f"9.9.9.{i}"})
    r = c.post("/api/auth/login", json={"email": "admin@newdru.com", "password": OWNER_PW},
               headers={"X-Forwarded-For": "8.8.8.8"})
    assert r.status_code == 429


def test_store_staff_cannot_dump_customers_or_b2b(app_client):
    c, _ = app_client
    store = bearer(c, "store@newdru.com", SEED_PW)
    assert c.get("/api/customers?limit=100000", headers=store).status_code == 400
    r = c.get("/api/customers?q=abc&limit=100000", headers=store)
    assert r.status_code == 200 and r.json()["limit"] <= 10
    assert c.get("/api/b2b/customers", headers=store).status_code == 403
    assert c.get("/api/b2b/collections/receivables.csv", headers=store).status_code == 403
    assert c.get("/api/messaging/log", headers=store).status_code == 403
    wh = bearer(c, "warehouse@newdru.com", SEED_PW)
    assert c.get("/api/customers?q=abc", headers=wh).status_code == 403
    assert c.get("/api/pos/sales", headers=wh).status_code == 403


def test_owner_override_is_rate_limited(app_client):
    c, _ = app_client
    store = bearer(c, "store@newdru.com", SEED_PW)
    codes = [c.post("/api/auth/verify-admin", json={"email": "admin@newdru.com", "password": f"guess-{i}"},
                    headers=store).status_code for i in range(7)]
    assert codes[-1] == 429


def test_pinelabs_webhook_closed_without_secret(app_client):
    c, _ = app_client
    r = c.post("/api/pinelabs/webhook", json={"PlutusTransactionReferenceID": "1", "ResponseMessage": "APPROVED"})
    assert r.status_code == 401


def test_regex_search_input_is_escaped(app_client):
    c, _ = app_client
    owner = bearer(c, "admin@newdru.com", OWNER_PW)
    assert c.get("/api/products?q=(a+)+$", headers=owner).status_code == 200


def test_public_warranty_rejects_script_upload(app_client):
    c, _ = app_client
    r = c.post("/api/public/warranty/register", json={
        "product_code": "X", "name": "A", "email": "a@b.co", "phone": "9999999999",
        "purchase_date": "2026-11-01", "purchase_source": "amazon",
        "invoice_url": "javascript:alert(1)"})
    assert r.status_code == 422


def test_csv_export_neutralises_formulas(app_client):
    c, server = app_client
    async def seed():
        await server.db.customers.insert_one({"id": "c1", "name": "=HYPERLINK(\"http://x\")", "phone": "9999999999"})
    c.portal.call(seed)
    owner = bearer(c, "admin@newdru.com", OWNER_PW)
    body = c.get("/api/customers/export/csv", headers=owner).text
    assert "'=HYPERLINK" in body


def test_oversized_upload_rejected(app_client):
    c, _ = app_client
    r = c.post("/api/public/warranty/register", content=b"x" * (7 * 1024 * 1024),
               headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_csp_on_pages(app_client):
    c, _ = app_client
    r = c.get("/api/health")
    assert "content-security-policy" not in {k.lower() for k in r.headers}


def test_production_never_seeds_demo_password(monkeypatch):
    import importlib, uuid, motor.motor_asyncio
    from mongomock_motor import AsyncMongoMockClient
    from fastapi.testclient import TestClient
    monkeypatch.setenv("MONGO_URL", "mongodb://x")
    monkeypatch.setenv("DB_NAME", f"seed_{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("JWT_SECRET", "x" * 48)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SEED_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(motor.motor_asyncio, "AsyncIOMotorClient", AsyncMongoMockClient)
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app, base_url="https://t") as c:
        r = c.post("/api/auth/login", json={"email": "admin@newdru.com", "password": "Newdru@2026"})
        assert r.status_code == 401
        assert c.portal.call(server.db.users.count_documents, {}) == 0



def test_exports_are_audited(app_client):
    c, server = app_client
    owner = bearer(c, "admin@newdru.com", OWNER_PW)
    assert c.get("/api/customers/export/csv", headers=owner).status_code == 200
    async def logs():
        return await server.db.audit_logs.find({"action": "export.customers"}).to_list(10)
    entries = c.portal.call(logs)
    assert len(entries) == 1
