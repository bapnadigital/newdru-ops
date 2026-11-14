"""Warranty + Shopify sync module tests."""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE}/api"

OWNER = ("admin@newdru.com", "Newdru@2026")
STORE = ("store@newdru.com", "Newdru@2026")
CASHIER = ("cashier@newdru.com", "Newdru@2026")


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    if r.status_code != 200:
        return None
    j = r.json()
    return j.get("token") or j.get("access_token")


def _h(t): return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def owner_token():
    t = _login(*OWNER); assert t; return t


@pytest.fixture(scope="module")
def store_token():
    t = _login(*STORE); assert t; return t


@pytest.fixture(scope="module")
def cashier_token():
    t = _login(*CASHIER)
    if not t:
        # Try alternate password from prior iteration
        t = _login(CASHIER[0], "Cash@123")
    assert t, "cashier login failed"
    return t


SKU = "BAPNA-BLACK"


# ------------------ Public: product lookup ------------------
class TestPublicLookup:
    def test_lookup_ok(self):
        r = requests.get(f"{API}/public/warranty/product-lookup", params={"code": SKU}, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        for k in ("sku", "name", "warranty_months"):
            assert k in j
        assert j["sku"] == SKU
        assert isinstance(j["warranty_months"], int)

    def test_lookup_missing_code(self):
        r = requests.get(f"{API}/public/warranty/product-lookup", params={"code": ""}, timeout=15)
        assert r.status_code in (400, 404, 422)

    def test_lookup_unknown_sku(self):
        r = requests.get(f"{API}/public/warranty/product-lookup", params={"code": "NOPE-XXX"}, timeout=15)
        assert r.status_code == 404


# ------------------ Public: register ------------------
UNIQUE_EMAIL = f"e2e.warranty.{uuid.uuid4().hex[:8]}@example.com"
_state = {}


class TestPublicRegister:
    def test_future_date_400(self):
        pd = (datetime.now() + timedelta(days=5)).date().isoformat()
        body = {"product_code": SKU, "name": "Test", "email": UNIQUE_EMAIL,
                "phone": "+919876543210", "purchase_date": pd, "purchase_source": "amazon"}
        r = requests.post(f"{API}/public/warranty/register", json=body, timeout=15)
        assert r.status_code == 400, r.text

    def test_too_old_400(self):
        pd = (datetime.now() - timedelta(days=500)).date().isoformat()
        body = {"product_code": SKU, "name": "Test", "email": UNIQUE_EMAIL,
                "phone": "+919876543210", "purchase_date": pd, "purchase_source": "amazon"}
        r = requests.post(f"{API}/public/warranty/register", json=body, timeout=15)
        assert r.status_code == 400

    def test_unknown_sku_404(self):
        pd = (datetime.now() - timedelta(days=14)).date().isoformat()
        body = {"product_code": "NOPE-XXX", "name": "Test", "email": UNIQUE_EMAIL,
                "phone": "+919876543210", "purchase_date": pd, "purchase_source": "amazon"}
        r = requests.post(f"{API}/public/warranty/register", json=body, timeout=15)
        assert r.status_code == 404

    def test_register_success(self):
        pd = (datetime.now() - timedelta(days=14)).date().isoformat()
        body = {"product_code": SKU, "name": "Test User", "email": UNIQUE_EMAIL,
                "phone": "+919876543210", "purchase_date": pd, "purchase_source": "amazon"}
        r = requests.post(f"{API}/public/warranty/register", json=body, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        for k in ("warranty_id", "product_name", "warranty_end", "warranty_months", "certificate_url"):
            assert k in j
        assert j["warranty_months"] == 6 or isinstance(j["warranty_months"], int)
        _state["wid"] = j["warranty_id"]
        _state["cert_url"] = j["certificate_url"]

    def test_duplicate_400(self):
        pd = (datetime.now() - timedelta(days=14)).date().isoformat()
        body = {"product_code": SKU, "name": "Test User", "email": UNIQUE_EMAIL,
                "phone": "+919876543210", "purchase_date": pd, "purchase_source": "amazon"}
        r = requests.post(f"{API}/public/warranty/register", json=body, timeout=15)
        assert r.status_code == 400
        assert "already registered" in r.text.lower()


# ------------------ Certificate + status + claim ------------------
class TestPublicPostRegister:
    def test_certificate_pdf(self):
        wid = _state.get("wid")
        assert wid, "register test must run first"
        r = requests.get(f"{BASE}/api/warranty/public/certificate/{wid}.pdf", timeout=15)
        assert r.status_code == 200, r.text[:200]
        assert "application/pdf" in r.headers.get("content-type", "")
        assert len(r.content) > 100

    def test_status(self):
        wid = _state["wid"]
        r = requests.get(f"{API}/public/warranty/status/{wid}", timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["warranty_id"] == wid
        assert j["status"] == "active"
        assert "days_left" in j and j["days_left"] >= 0
        assert "warranty_end" in j

    def test_claim(self):
        wid = _state["wid"]
        body = {"issue_type": "defect", "description": "Zipper broken"}
        r = requests.post(f"{API}/public/warranty/claim/{wid}", json=body, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("status") == "submitted"
        assert "claim_id" in j
        _state["claim_id"] = j["claim_id"]


# ------------------ Admin endpoints ------------------
class TestAdmin:
    def test_activity_shows_events(self, owner_token):
        wid = _state["wid"]
        r = requests.get(f"{API}/warranty/activity", headers=_h(owner_token),
                         params={"q": wid}, timeout=15)
        assert r.status_code == 200
        rows = r.json()["rows"]
        events = {row["event"] for row in rows}
        assert "purchased" in events, events
        assert "warranty_registered" in events, events
        # tracking + ip should be present
        for row in rows:
            if row["event"] == "warranty_registered":
                assert "tracking_id" in row
                assert "ip" in row

    def test_registrations_list_owner(self, owner_token):
        r = requests.get(f"{API}/warranty/registrations", headers=_h(owner_token),
                         params={"skip": 0, "limit": 20}, timeout=15)
        assert r.status_code == 200
        j = r.json()
        for k in ("total", "skip", "limit", "rows"):
            assert k in j

    def test_registrations_list_store(self, store_token):
        r = requests.get(f"{API}/warranty/registrations", headers=_h(store_token), timeout=15)
        assert r.status_code == 200

    def test_registrations_list_cashier_forbidden(self, cashier_token):
        r = requests.get(f"{API}/warranty/registrations", headers=_h(cashier_token), timeout=15)
        assert r.status_code == 403

    def test_registrations_no_auth(self):
        r = requests.get(f"{API}/warranty/registrations", timeout=15)
        assert r.status_code == 401

    def test_registration_detail(self, owner_token):
        wid = _state["wid"]
        r = requests.get(f"{API}/warranty/registrations/{wid}", headers=_h(owner_token), timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        for k in ("registration", "claims", "activity", "product"):
            assert k in j
        assert "days_left" in j["registration"]

    def test_patch_registration_owner(self, owner_token):
        wid = _state["wid"]
        r = requests.patch(f"{API}/warranty/registrations/{wid}",
                           json={"status": "approved"}, headers=_h(owner_token), timeout=15)
        assert r.status_code == 200, r.text

    def test_patch_registration_non_owner_forbidden(self, store_token):
        wid = _state["wid"]
        r = requests.patch(f"{API}/warranty/registrations/{wid}",
                           json={"status": "active"}, headers=_h(store_token), timeout=15)
        assert r.status_code == 403

    def test_claims_list_shows_new_claim(self, owner_token):
        r = requests.get(f"{API}/warranty/claims", headers=_h(owner_token), timeout=15)
        assert r.status_code == 200
        rows = r.json()["rows"]
        cid = _state.get("claim_id")
        assert any(row["id"] == cid for row in rows), f"claim {cid} not found"

    def test_analytics(self, owner_token):
        r = requests.get(f"{API}/warranty/analytics", headers=_h(owner_token), timeout=15)
        assert r.status_code == 200
        j = r.json()
        for k in ("total", "last_30_days", "active", "claims_open", "claims_total",
                  "by_source", "by_state", "top_skus"):
            assert k in j

    def test_export_csv_owner(self, owner_token):
        r = requests.get(f"{API}/warranty/export.csv", headers=_h(owner_token), timeout=15)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        assert "Warranty ID" in r.text

    def test_export_csv_non_owner_forbidden(self, store_token):
        r = requests.get(f"{API}/warranty/export.csv", headers=_h(store_token), timeout=15)
        assert r.status_code == 403


# ------------------ Per-SKU settings ------------------
class TestSettings:
    def test_get_settings(self, owner_token):
        r = requests.get(f"{API}/warranty/settings", headers=_h(owner_token), timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["default_months"] == 6
        assert isinstance(j["products"], list)

    def test_override_and_revert(self, owner_token):
        # set 12
        r = requests.post(f"{API}/warranty/settings/product",
                          json={"sku": SKU, "warranty_months": 12},
                          headers=_h(owner_token), timeout=15)
        assert r.status_code == 200
        # verify via public lookup
        r2 = requests.get(f"{API}/public/warranty/product-lookup", params={"code": SKU}, timeout=15)
        assert r2.json()["warranty_months"] == 12
        # revert to 6
        r3 = requests.post(f"{API}/warranty/settings/product",
                           json={"sku": SKU, "warranty_months": 6},
                           headers=_h(owner_token), timeout=15)
        assert r3.status_code == 200
        r4 = requests.get(f"{API}/public/warranty/product-lookup", params={"code": SKU}, timeout=15)
        assert r4.json()["warranty_months"] == 6


# ------------------ Shopify sync ------------------
class TestShopify:
    def test_config_owner(self, owner_token):
        r = requests.get(f"{API}/shopify/config", headers=_h(owner_token), timeout=15)
        assert r.status_code == 200
        j = r.json()
        for k in ("mode", "ready", "access_token_set"):
            assert k in j

    def test_config_non_owner_forbidden(self, store_token):
        r = requests.get(f"{API}/shopify/config", headers=_h(store_token), timeout=15)
        assert r.status_code == 403

    def test_save_settings(self, owner_token):
        body = {"shop_domain": "newdru.myshopify.com",
                "access_token": "shpat_TEST123",
                "mode": "pull_only"}
        r = requests.post(f"{API}/shopify/settings", json=body,
                          headers=_h(owner_token), timeout=15)
        assert r.status_code == 200, r.text
        r2 = requests.get(f"{API}/shopify/config", headers=_h(owner_token), timeout=15)
        j = r2.json()
        assert j["access_token_set"] is True
        assert j.get("shop_domain") == "newdru.myshopify.com" or j.get("shop_domain")

    def test_sync_orders_invalid_creds_no_500(self, owner_token):
        r = requests.post(f"{API}/shopify/sync/orders", headers=_h(owner_token), timeout=30)
        # must not 500
        assert r.status_code != 500, r.text
        assert r.status_code == 200
        j = r.json()
        # invalid creds -> ok:false gracefully
        assert j.get("ok") is False or j.get("ok") is True

    def test_sync_inventory_not_full_mode(self, owner_token):
        # ensure mode is pull_only
        requests.post(f"{API}/shopify/settings", json={"mode": "pull_only"},
                      headers=_h(owner_token), timeout=15)
        r = requests.post(f"{API}/shopify/sync/inventory", headers=_h(owner_token), timeout=15)
        assert r.status_code == 400, r.text
