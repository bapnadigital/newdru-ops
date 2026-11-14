"""Verification tests for the 4 Newdru bug-fix categories:
1. Catalog cleanup (49 real products with shipping_marks)
2. Box-Fit planner math
3. Customer count + CSV import + cashier RBAC
4. Pine Labs Cloud settings + payment simulator round-trip
"""
import os
import io
import math
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    # Read frontend .env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE = line.split("=", 1)[1].strip().rstrip("/")

API = f"{BASE}/api"

OWNER = ("admin@newdru.com", "Newdru@2026")
STORE = ("store@newdru.com", "Newdru@2026")
CASHIER = ("cashier@newdru.com", "Cash@123")


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    if r.status_code != 200:
        return None
    j = r.json()
    return j.get("access_token") or j.get("token") or j.get("jwt")


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture(scope="module")
def owner_token():
    tok = _login(*OWNER)
    assert tok, "Owner login failed"
    return tok


@pytest.fixture(scope="module")
def store_token():
    tok = _login(*STORE)
    assert tok, "Store manager login failed"
    return tok


@pytest.fixture(scope="module")
def cashier_token(owner_token):
    tok = _login(*CASHIER)
    if tok:
        return tok
    # try create as owner
    payload = {"email": CASHIER[0], "name": "Test Cashier", "password": CASHIER[1],
               "role": "cashier", "active": True}
    r = requests.post(f"{API}/users", json=payload, headers=_h(owner_token), timeout=15)
    # if already exists w/ different password, try resetting via patch
    tok = _login(*CASHIER)
    assert tok, f"Cashier login failed after create attempt (status={r.status_code} body={r.text[:200]})"
    return tok


# ------------------------------------------------------------------
# 1) Catalog cleanup
# ------------------------------------------------------------------
class TestCatalog:
    def _all(self, owner_token):
        # Try list products; support pagination
        rows = []
        skip = 0
        while True:
            r = requests.get(f"{API}/products", headers=_h(owner_token),
                             params={"skip": skip, "limit": 500}, timeout=20)
            assert r.status_code == 200, f"GET /products {r.status_code} {r.text[:200]}"
            j = r.json()
            if isinstance(j, dict) and "rows" in j:
                rows.extend(j["rows"])
                if len(j["rows"]) < 500 or (skip + len(j["rows"])) >= j.get("total", 0):
                    break
                skip += 500
            elif isinstance(j, list):
                rows = j
                break
            else:
                break
        return rows

    def test_49_products_all_have_shipping_mark(self, owner_token):
        rows = self._all(owner_token)
        print(f"Total products: {len(rows)}")
        assert len(rows) == 49, f"Expected exactly 49 products, got {len(rows)}"
        missing = [p.get("sku") for p in rows if not (p.get("shipping_mark") or "").strip()]
        assert not missing, f"Products without shipping_mark: {missing}"

    def test_no_old_seed_skus(self, owner_token):
        rows = self._all(owner_token)
        skus = {p.get("sku") for p in rows}
        deleted = {"ND-T001", "ND-T002", "ND-J005", "ND-H010", "ND-C020", "ND-S030"}
        overlap = skus & deleted
        assert not overlap, f"Old seed SKUs still present: {overlap}"

    def test_expected_skus_present(self, owner_token):
        rows = self._all(owner_token)
        skus = {p.get("sku") for p in rows}
        expected = {"BAPNA-BLACK", "ARMSH-BLUE", "CASCAS-GOLD",
                    "SHUTOVE", "TOVISH", "RANGER", "AMTER", "SHUMASK"}
        missing = expected - skus
        assert not missing, f"Expected SKUs missing: {missing}"

    def test_sku_matches_shipping_mark_pattern(self, owner_token):
        rows = self._all(owner_token)
        # SKU should equal shipping_mark or shipping_mark-VARIANT
        bad = []
        for p in rows:
            sku = (p.get("sku") or "").strip()
            sm = (p.get("shipping_mark") or "").strip()
            if not sku.startswith(sm):
                bad.append((sku, sm))
        assert not bad, f"SKUs not matching shipping_mark pattern: {bad[:10]}"


# ------------------------------------------------------------------
# 2) Box-Fit planner
# ------------------------------------------------------------------
class TestBoxFit:
    def _bf(self, tok, product_id, qty):
        r = requests.get(f"{API}/planner/box-fit", headers=_h(tok),
                         params={"product_id": product_id, "quantity": qty}, timeout=15)
        assert r.status_code == 200, f"box-fit {product_id} qty={qty}: {r.status_code} {r.text[:300]}"
        return r.json()

    def test_shumask_1000(self, owner_token):
        j = self._bf(owner_token, "SHUMASK", 1000)
        c = j["computation"]
        assert c["total_boxes"] == 3
        assert c["full_boxes"] == 2
        assert c["loose_units"] == 80
        assert abs(c["unit_weight_kg"] - 0.0352) < 0.001
        assert abs(c["total_weight_kg"] - 35.2) < 0.1
        assert abs(c["weight_per_box_kg"] - 16.19) < 0.02
        assert abs(c["total_volume_cft"] - 5.82) < 0.1
        assert abs(c["total_volume_cbm"] - 0.165) < 0.01
        assert j["stock"]["verdict"] == "YES"

    def test_shutove_500(self, owner_token):
        j = self._bf(owner_token, "SHUTOVE", 500)
        c = j["computation"]
        assert c["total_boxes"] == 84
        assert c["full_boxes"] == 83
        assert c["loose_units"] == 2
        assert abs(c["total_weight_kg"] - 878.33) < 0.5
        assert j["stock"]["verdict"] == "YES"

    def test_tovish_1000(self, owner_token):
        j = self._bf(owner_token, "TOVISH", 1000)
        c = j["computation"]
        assert c["total_boxes"] == 250
        assert c["full_boxes"] == 250
        assert c["loose_units"] == 0
        assert abs(c["total_weight_kg"] - 4250.0) < 0.5
        assert j["stock"]["verdict"] == "YES"

    def test_ranger_missing_packaging_warning(self, owner_token):
        j = self._bf(owner_token, "RANGER", 100)
        warnings = j.get("warnings") or []
        joined = " | ".join(warnings)
        assert "Packaging not set" in joined, f"Expected 'Packaging not set' warning; got: {warnings}"


# ------------------------------------------------------------------
# 3) Customers pagination + CSV import + RBAC
# ------------------------------------------------------------------
class TestCustomers:
    def test_customer_list_shape_and_total(self, owner_token):
        r = requests.get(f"{API}/customers", headers=_h(owner_token),
                         params={"limit": 1}, timeout=15)
        assert r.status_code == 200
        j = r.json()
        for k in ("total", "skip", "limit", "rows"):
            assert k in j, f"missing key {k}"
        print(f"Customer total = {j['total']}")
        # spec says currently 7 but allow real customers created since
        assert j["total"] == 7, f"Expected 7 customers, got {j['total']}"

    def test_no_shopify_example_customers(self, owner_token):
        r = requests.get(f"{API}/customers", headers=_h(owner_token),
                         params={"limit": 500, "q": "@shopify.example"}, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["total"] == 0, f"Found synthetic @shopify.example customers: {j['total']}"

    def _cleanup_shopify_example(self):
        # No DELETE endpoint exists on /api/customers/{id} — clean via mongo directly.
        try:
            import asyncio
            from motor.motor_asyncio import AsyncIOMotorClient
            async def _go():
                cli = AsyncIOMotorClient("mongodb://localhost:27017")
                await cli["newdru_db"].customers.delete_many({"email": {"$regex": "@shopify.example$"}})
            asyncio.get_event_loop().run_until_complete(_go()) if False else asyncio.run(_go())
        except Exception as e:
            print("cleanup skipped:", e)

    def test_csv_import_creates_then_updates(self, owner_token):
        self._cleanup_shopify_example()
        csv_body = (
            "name,email,phone,total_spent,order_count,consent_email,consent_sms,"
            "consent_whatsapp,city,state,country,tags,channel\n"
            "TEST Alice,test_alice@shopify.example,+911111100001,1200,3,true,false,true,Mumbai,MH,India,vip;wholesale,online (shopify)\n"
            "TEST Bob,test_bob@shopify.example,+911111100002,0,0,false,false,false,Pune,MH,India,,store\n"
        )
        files = {"file": ("test.csv", csv_body, "text/csv")}
        # first import
        r1 = requests.post(f"{API}/customers/import-csv", headers=_h(owner_token),
                           files=files, timeout=30)
        assert r1.status_code == 200, f"{r1.status_code} {r1.text[:300]}"
        j1 = r1.json()
        assert j1["created"] >= 2, f"Expected >=2 created, got {j1}"
        # second import (dedupe by email)
        files2 = {"file": ("test.csv", csv_body, "text/csv")}
        r2 = requests.post(f"{API}/customers/import-csv", headers=_h(owner_token),
                           files=files2, timeout=30)
        assert r2.status_code == 200
        j2 = r2.json()
        assert j2["created"] == 0, f"Second import should create 0, got {j2}"
        assert j2["updated"] >= 2, f"Second import should update >=2, got {j2}"

        # cleanup via mongo since no DELETE endpoint
        self._cleanup_shopify_example()

    def test_cashier_forbidden_on_import(self, cashier_token):
        csv_body = "name,email\nX,x@shopify.example\n"
        r = requests.post(f"{API}/customers/import-csv", headers=_h(cashier_token),
                          files={"file": ("t.csv", csv_body, "text/csv")}, timeout=15)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text[:200]}"


# ------------------------------------------------------------------
# 4) Pine Labs
# ------------------------------------------------------------------
class TestPineLabs:
    def test_config_authed(self, owner_token):
        r = requests.get(f"{API}/pinelabs/config", headers=_h(owner_token), timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        j = r.json()
        assert "mode" in j and "credentials_source" in j

    def test_settings_owner_only(self, owner_token, store_token, cashier_token):
        r_o = requests.get(f"{API}/pinelabs/settings", headers=_h(owner_token), timeout=15)
        assert r_o.status_code == 200, f"owner: {r_o.status_code} {r_o.text[:200]}"
        r_s = requests.get(f"{API}/pinelabs/settings", headers=_h(store_token), timeout=15)
        assert r_s.status_code == 403, f"store_manager should get 403, got {r_s.status_code}"
        r_c = requests.get(f"{API}/pinelabs/settings", headers=_h(cashier_token), timeout=15)
        assert r_c.status_code == 403, f"cashier should get 403, got {r_c.status_code}"

    def test_settings_persist_and_mask(self, owner_token):
        # first save without security_token
        body = {"merchant_id": "TEST_MERCH", "store_id": "S1", "terminal_id": "T1",
                "user_id": "u1", "mode": "simulator"}
        r = requests.post(f"{API}/pinelabs/settings", json=body, headers=_h(owner_token), timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        g = requests.get(f"{API}/pinelabs/settings", headers=_h(owner_token), timeout=15).json()
        assert g["merchant_id"] == "TEST_MERCH"
        assert g["store_id"] == "S1"
        assert g["terminal_id"] == "T1"
        assert g["user_id"] == "u1"
        assert g["mode"] == "simulator"
        # security_token_masked should be None (we didn't send one and previously not set)
        # (tolerant: only fail if it accidentally leaks a non-mask value)
        if g.get("security_token_masked") is not None:
            assert "•" in g["security_token_masked"]

        # now save security_token and verify mask
        r2 = requests.post(f"{API}/pinelabs/settings",
                           json={"security_token": "SECRET1234"},
                           headers=_h(owner_token), timeout=15)
        assert r2.status_code == 200
        g2 = requests.get(f"{API}/pinelabs/settings", headers=_h(owner_token), timeout=15).json()
        m = g2.get("security_token_masked")
        assert m and m.startswith("SE") and m.endswith("34") and "•" in m, f"bad mask: {m!r}"

    def test_pay_and_simulator_round_trip(self, owner_token, store_token, cashier_token):
        # ensure sim mode
        requests.post(f"{API}/pinelabs/settings", json={"mode": "simulator"},
                      headers=_h(owner_token), timeout=15)

        import uuid
        cref = "TEST-" + uuid.uuid4().hex[:10]
        body = {"amount": 100, "mode": "card", "client_ref": cref}
        r = requests.post(f"{API}/pinelabs/pay", json=body, headers=_h(owner_token), timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        j = r.json()
        assert j["status"] == "OPEN"
        ptr = j["ptr_id"]

        # idempotency check
        r2 = requests.post(f"{API}/pinelabs/pay", json=body, headers=_h(owner_token), timeout=15)
        j2 = r2.json()
        assert j2["ptr_id"] == ptr, f"idempotency broken: {ptr} vs {j2['ptr_id']}"

        # non-owner cannot approve
        r_s = requests.post(f"{API}/pinelabs/simulate/{ptr}/approve", json={"outcome": "approved"},
                            headers=_h(store_token), timeout=15)
        assert r_s.status_code == 403
        r_c = requests.post(f"{API}/pinelabs/simulate/{ptr}/approve", json={"outcome": "approved"},
                            headers=_h(cashier_token), timeout=15)
        assert r_c.status_code == 403

        # owner approves
        r_a = requests.post(f"{API}/pinelabs/simulate/{ptr}/approve",
                            json={"outcome": "approved"},
                            headers=_h(owner_token), timeout=15)
        assert r_a.status_code == 200, f"{r_a.status_code} {r_a.text[:300]}"

        # status
        r_st = requests.get(f"{API}/pinelabs/status/{ptr}", headers=_h(owner_token), timeout=15)
        assert r_st.status_code == 200
        s = r_st.json()
        assert s["status"] == "APPROVED", f"status={s}"
        assert s.get("rrn"), "rrn missing"
        assert s.get("approval_code"), "approval_code missing"
        assert s.get("masked_pan"), "masked_pan missing"
