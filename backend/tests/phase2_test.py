"""Newdru Phase 2 backend tests: Pine Labs, B2B/Collections, FC Sync, Messaging."""
import io
import os
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@newdru.com", "password": "Newdru@2026"}


def _login(email, password):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": password})


def _client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


def _ensure_user(owner, email, password, role, name):
    r = _login(email, password)
    if r.status_code == 200:
        return r.json()["token"], r.json()["user"]
    r2 = owner.post(f"{API}/users", json={
        "email": email, "password": password, "role": role, "name": name, "active": True,
    })
    if r2.status_code == 409:
        users = owner.get(f"{API}/users").json()
        u = next((u for u in users if u["email"] == email), None)
        assert u, f"user {email} missing"
        owner.patch(f"{API}/users/{u['id']}", json={"password": password, "role": role, "active": True})
    else:
        assert r2.status_code in (200, 201), r2.text
    r3 = _login(email, password)
    assert r3.status_code == 200, r3.text
    return r3.json()["token"], r3.json()["user"]


# ------------------- Fixtures -------------------

@pytest.fixture(scope="module")
def owner_tok():
    r = _login(**ADMIN)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def owner(owner_tok):
    return _client(owner_tok)


@pytest.fixture(scope="module")
def cashier(owner):
    tok, u = _ensure_user(owner, "cashier@newdru.com", "Cash@123", "cashier", "Test Cashier")
    return {"client": _client(tok), "user": u}


@pytest.fixture(scope="module")
def store_mgr(owner):
    tok, u = _ensure_user(owner, "store@newdru.com", "Store@123", "store_manager", "Store Mgr")
    return {"client": _client(tok), "user": u}


@pytest.fixture(scope="module")
def wh_mgr(owner):
    tok, u = _ensure_user(owner, "warehouse@newdru.com", "Ware@123", "warehouse_manager", "WH Mgr")
    return {"client": _client(tok), "user": u}


@pytest.fixture(scope="module")
def wh_staff(owner):
    tok, u = _ensure_user(owner, "staff@newdru.com", "Staff@123", "warehouse_staff", "WH Staff")
    return {"client": _client(tok), "user": u}


@pytest.fixture(scope="module")
def demo_product(owner):
    pr = owner.get(f"{API}/products?q=ND-T001").json()
    assert pr, "seed product ND-T001 missing"
    prod = pr[0]
    # ensure some BHIWANDI stock
    owner.post(f"{API}/inventory/receive", json={
        "location_code": "BHIWANDI", "reference": "PH2-SEED",
        "lines": [{"sku": prod["sku"], "cartons": 0, "units": 200}]
    })
    return prod


# ============================================================
# Pine Labs
# ============================================================

class TestPineLabsConfig:
    def test_config_returns_mode(self, owner):
        r = owner.get(f"{API}/pinelabs/config")
        assert r.status_code == 200
        assert r.json().get("mode") in ("simulator", "uat", "production", "disabled")


class TestPineLabsFlow:
    def test_pay_status_approve_flow(self, cashier, owner):
        client_ref = f"NDR-{uuid.uuid4().hex[:8].upper()}"
        r = cashier["client"].post(f"{API}/pinelabs/pay",
                                    json={"amount": 1234.5, "mode": "card", "client_ref": client_ref})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "OPEN"
        ptr = d["ptr_id"]
        assert ptr

        # idempotency: same client_ref returns same ptr
        r2 = cashier["client"].post(f"{API}/pinelabs/pay",
                                     json={"amount": 1234.5, "mode": "card", "client_ref": client_ref})
        assert r2.status_code == 200
        assert r2.json()["ptr_id"] == ptr

        # owner-only simulate approve
        rc = cashier["client"].post(f"{API}/pinelabs/simulate/{ptr}/approve",
                                     json={"outcome": "approved"})
        assert rc.status_code == 403

        ra = owner.post(f"{API}/pinelabs/simulate/{ptr}/approve",
                        json={"outcome": "approved"})
        assert ra.status_code == 200, ra.text

        rs = cashier["client"].get(f"{API}/pinelabs/status/{ptr}")
        assert rs.status_code == 200
        s = rs.json()
        assert s["status"] == "APPROVED"
        assert s["rrn"] and s["approval_code"] and s["masked_pan"] and s["acquirer"]

    def test_warehouse_staff_cannot_pay(self, wh_staff):
        r = wh_staff["client"].post(f"{API}/pinelabs/pay", json={"amount": 100, "mode": "card"})
        assert r.status_code == 403

    def test_cancel_open_then_approved_400(self, cashier, owner):
        r = cashier["client"].post(f"{API}/pinelabs/pay", json={"amount": 50, "mode": "card"})
        assert r.status_code == 200
        ptr = r.json()["ptr_id"]
        rc = cashier["client"].post(f"{API}/pinelabs/cancel/{ptr}")
        assert rc.status_code == 200
        assert rc.json()["status"] == "CANCELLED"

        # Now create + approve one, then cancel -> 400
        r2 = cashier["client"].post(f"{API}/pinelabs/pay", json={"amount": 60, "mode": "card"})
        ptr2 = r2.json()["ptr_id"]
        owner.post(f"{API}/pinelabs/simulate/{ptr2}/approve", json={"outcome": "approved"})
        rc2 = cashier["client"].post(f"{API}/pinelabs/cancel/{ptr2}")
        assert rc2.status_code == 400

    def test_webhook_updates_open(self, cashier):
        r = cashier["client"].post(f"{API}/pinelabs/pay", json={"amount": 70, "mode": "card"})
        ptr = r.json()["ptr_id"]
        wh = requests.post(f"{API}/pinelabs/webhook",
                           json={"PlutusTransactionReferenceID": ptr,
                                 "ResponseMessage": "APPROVED",
                                 "RRN": "111222", "ApprovalCode": "ABC123",
                                 "MaskedPAN": "**** 4242", "Acquirer": "HDFC"})
        assert wh.status_code == 200, wh.text
        # confirm via status
        rs = cashier["client"].get(f"{API}/pinelabs/status/{ptr}")
        assert rs.json()["status"] == "APPROVED"


# ============================================================
# B2B / Collections
# ============================================================

@pytest.fixture(scope="module")
def b2b_customer(owner):
    phone = f"9{uuid.uuid4().int % 10**9:09d}"
    r = owner.post(f"{API}/b2b/customers", json={
        "name": "TEST WholeCust", "company": "TESTCO",
        "phone": phone, "gstin": "27ABCDE1234F1Z5",
        "credit_limit": 250000, "payment_terms_days": 30,
    })
    assert r.status_code == 200, r.text
    return r.json()


class TestB2BCustomer:
    def test_create_and_search(self, owner, b2b_customer):
        assert b2b_customer["customer_type"] == "wholesale"
        assert b2b_customer["outstanding"] == 0
        # search
        r = owner.get(f"{API}/b2b/customers?q={b2b_customer['phone']}")
        assert r.status_code == 200
        assert any(c["id"] == b2b_customer["id"] for c in r.json())

    def test_duplicate_phone_400(self, owner, b2b_customer):
        r = owner.post(f"{API}/b2b/customers", json={
            "name": "Dup", "phone": b2b_customer["phone"],
            "credit_limit": 1000, "payment_terms_days": 15,
        })
        assert r.status_code == 400

    def test_rbac_forbidden(self, cashier, wh_mgr, wh_staff):
        payload = {"name": "X", "phone": f"9{uuid.uuid4().int % 10**9:09d}"}
        for c in (cashier["client"], wh_mgr["client"], wh_staff["client"]):
            r = c.post(f"{API}/b2b/customers", json=payload)
            assert r.status_code == 403


class TestB2BOrderLifecycle:
    def test_full_lifecycle(self, owner, b2b_customer, demo_product):
        P = 100.0  # unit_price inclusive
        # (a) create order
        r = owner.post(f"{API}/b2b/orders", json={
            "customer_id": b2b_customer["id"],
            "lines": [{
                "product_id": demo_product["id"], "sku": demo_product["sku"],
                "name": demo_product["name"], "hsn": demo_product.get("hsn"),
                "gst_rate": 18, "quantity": 10, "unit_price": P
            }],
            "ship_from": "BHIWANDI",
        })
        assert r.status_code == 200, r.text
        order = r.json()
        assert order["status"] == "confirmed"
        assert abs(order["total"] - 10 * P) < 0.05
        # subtotal + tax = total (gst-inclusive)
        assert abs(order["subtotal"] + order["tax_total"] - order["total"]) < 0.05
        oid = order["id"]

        # (b) dispatch
        before = owner.get(f"{API}/inventory/grid?q={demo_product['sku']}").json()["rows"][0]["locations"]["BHIWANDI"]["quantity"]
        r2 = owner.post(f"{API}/b2b/orders/{oid}/dispatch")
        assert r2.status_code == 200
        assert r2.json()["status"] == "dispatched"
        after = owner.get(f"{API}/inventory/grid?q={demo_product['sku']}").json()["rows"][0]["locations"]["BHIWANDI"]["quantity"]
        assert after == before - 10

        # stock movement
        mv = owner.get(f"{API}/stock/movements?product_id={demo_product['id']}&limit=20").json()
        assert any(m.get("movement_type") == "b2b_dispatch" for m in mv), f"no b2b_dispatch mvt: {mv[:3]}"

        # (c) invoice
        r3 = owner.post(f"{API}/b2b/orders/{oid}/invoice")
        assert r3.status_code == 200, r3.text
        d3 = r3.json()
        assert d3["invoice_no"].startswith("WI-"), d3
        parts = d3["invoice_no"].split("-")
        assert len(parts) == 3 and len(parts[2]) == 5
        assert d3["due_date"]
        assert abs(d3["outstanding"] - 10 * P) < 0.05

        # (d) partial payment
        r4 = owner.post(f"{API}/b2b/orders/{oid}/payments",
                         json={"method": "bank_transfer", "amount": P})
        assert r4.status_code == 200, r4.text
        d4 = r4.json()
        assert abs(d4["paid_amount"] - P) < 0.05
        assert d4["status"] == "partially_paid"

        # (e) dashboard
        r5 = owner.get(f"{API}/b2b/collections/dashboard")
        assert r5.status_code == 200
        dash = r5.json()
        remaining = 10 * P - P
        assert dash["total_outstanding"] >= remaining - 0.05  # may include others
        assert dash["buckets"]["0-30"] >= remaining - 0.05

    def test_credit_limit_guard(self, owner):
        phone = f"9{uuid.uuid4().int % 10**9:09d}"
        c = owner.post(f"{API}/b2b/customers", json={
            "name": "TEST Small", "phone": phone,
            "credit_limit": 1000, "payment_terms_days": 30,
        }).json()
        # try order total 5000 (5 x 1000 inclusive)
        # Need a product
        prod = owner.get(f"{API}/products?q=ND-T001").json()[0]
        r = owner.post(f"{API}/b2b/orders", json={
            "customer_id": c["id"],
            "lines": [{"product_id": prod["id"], "sku": prod["sku"], "name": prod["name"],
                       "gst_rate": 18, "quantity": 5, "unit_price": 1000}],
        })
        assert r.status_code == 400
        assert "credit" in r.text.lower() or "outstanding" in r.text.lower()

    def test_rbac_order_forbidden(self, cashier, wh_mgr, wh_staff, b2b_customer, demo_product):
        payload = {
            "customer_id": b2b_customer["id"],
            "lines": [{"product_id": demo_product["id"], "sku": demo_product["sku"],
                       "name": demo_product["name"], "gst_rate": 18,
                       "quantity": 1, "unit_price": 100}],
        }
        for c in (cashier["client"], wh_mgr["client"], wh_staff["client"]):
            r = c.post(f"{API}/b2b/orders", json=payload)
            assert r.status_code == 403


class TestB2BCSV:
    def test_receivables_csv_headers(self, owner_tok):
        r = requests.get(f"{API}/b2b/collections/receivables.csv",
                         headers={"Authorization": f"Bearer {owner_tok}"})
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        first_line = r.content.decode().splitlines()[0]
        for h in ["Order No", "Invoice No", "Customer", "GSTIN", "Total", "Paid",
                  "Outstanding", "Invoice Date", "Due Date", "Days Overdue", "Bucket"]:
            assert h in first_line


# ============================================================
# FC Sync (Unicommerce CSV)
# ============================================================

class TestFCSync:
    def test_config(self, owner):
        r = owner.get(f"{API}/fc-sync/config")
        assert r.status_code == 200
        assert "mode" in r.json()

    def test_csv_upload_updates(self, owner_tok, owner):
        # Get real SKUs
        prods = owner.get(f"{API}/products?limit=5").json()
        assert len(prods) >= 2
        sku1, sku2 = prods[0]["sku"], prods[1]["sku"]
        csv_text = f"sku,quantity\n{sku1},120\n{sku2},45\nUNKNOWN-SKU-XYZ,999\n"
        files = {"file": ("fc.csv", csv_text, "text/csv")}
        data = {"location_code": "AMAZON_FC"}
        r = requests.post(f"{API}/fc-sync/csv",
                          headers={"Authorization": f"Bearer {owner_tok}"},
                          data=data, files=files)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["updated"] == 2
        assert d["unknown_count"] == 1
        assert "UNKNOWN-SKU-XYZ" in d["unknown_skus"]
        assert d["synced_at"]

        # verify grid
        grid = owner.get(f"{API}/inventory/grid?q={sku1}").json()
        row = grid["rows"][0]
        assert row["locations"]["AMAZON_FC"]["quantity"] == 120
        assert row["locations"]["AMAZON_FC"].get("last_synced_at")

    def test_bad_location_400(self, owner_tok):
        csv_text = "sku,quantity\nX,1\n"
        r = requests.post(f"{API}/fc-sync/csv",
                          headers={"Authorization": f"Bearer {owner_tok}"},
                          data={"location_code": "STORE"},
                          files={"file": ("x.csv", csv_text, "text/csv")})
        assert r.status_code == 400

    def test_rbac(self, cashier, store_mgr, wh_mgr, owner_tok):
        csv_text = "sku,quantity\nND-T001,10\n"
        # cashier forbidden
        r1 = requests.post(f"{API}/fc-sync/csv",
                           headers={"Authorization": f"Bearer {cashier['client'].headers['Authorization'].split()[1]}"},
                           data={"location_code": "AMAZON_FC"},
                           files={"file": ("x.csv", csv_text, "text/csv")})
        assert r1.status_code == 403
        # store manager forbidden
        r2 = requests.post(f"{API}/fc-sync/csv",
                           headers={"Authorization": f"Bearer {store_mgr['client'].headers['Authorization'].split()[1]}"},
                           data={"location_code": "AMAZON_FC"},
                           files={"file": ("x.csv", csv_text, "text/csv")})
        assert r2.status_code == 403
        # wh manager allowed
        r3 = requests.post(f"{API}/fc-sync/csv",
                           headers={"Authorization": f"Bearer {wh_mgr['client'].headers['Authorization'].split()[1]}"},
                           data={"location_code": "AMAZON_FC"},
                           files={"file": ("x.csv", csv_text, "text/csv")})
        assert r3.status_code == 200


# ============================================================
# Messaging
# ============================================================

class TestMessaging:
    def test_config(self, owner):
        r = owner.get(f"{API}/messaging/config")
        assert r.status_code == 200
        d = r.json()
        assert d["gupshup"]["mode"]
        assert d["msg91"]["mode"]

    def test_send_whatsapp_simulator(self, owner):
        r = owner.post(f"{API}/messaging/send",
                        json={"to": "9812345678", "body": "test", "channel": "whatsapp"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        result = d["result"]
        assert result["provider"] == "gupshup"
        assert result["mode"] == "simulator"
        assert result["to"].startswith("91")

    def test_send_sms_simulator(self, owner):
        r = owner.post(f"{API}/messaging/send",
                        json={"to": "9812345678", "body": "test", "channel": "sms"})
        assert r.status_code == 200
        assert r.json()["result"]["provider"] == "msg91"

    def test_send_receipt_full_flow(self, owner, cashier):
        # Create a POS sale with a customer with phone
        prod = owner.get(f"{API}/products?q=ND-T001").json()[0]
        owner.post(f"{API}/inventory/receive", json={
            "location_code": "STORE", "reference": "MSG-SEED",
            "lines": [{"sku": prod["sku"], "cartons": 0, "units": 5}]
        })
        phone = f"9{uuid.uuid4().int % 10**9:09d}"
        cart = {
            "items": [{"product_id": prod["id"], "sku": prod["sku"], "name": prod["name"],
                       "gst_rate": 18, "quantity": 1, "unit_price": 118, "discount": 0}],
            "payments": [{"method": "cash", "amount": 118}],
            "customer": {"name": "Msg Cust", "phone": phone},
            "client_ref": f"MSG-{uuid.uuid4().hex[:8]}",
        }
        rs = cashier["client"].post(f"{API}/pos/sales", json=cart)
        assert rs.status_code == 200, rs.text
        sale_id = rs.json()["id"]
        r = owner.post(f"{API}/messaging/send-receipt",
                        json={"sale_id": sale_id, "channel": "whatsapp"})
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    def test_send_receipt_no_customer_400(self, owner, cashier):
        prod = owner.get(f"{API}/products?q=ND-T001").json()[0]
        owner.post(f"{API}/inventory/receive", json={
            "location_code": "STORE", "reference": "MSG-SEED2",
            "lines": [{"sku": prod["sku"], "cartons": 0, "units": 5}]
        })
        rs = cashier["client"].post(f"{API}/pos/sales", json={
            "items": [{"product_id": prod["id"], "sku": prod["sku"], "name": prod["name"],
                       "gst_rate": 18, "quantity": 1, "unit_price": 118, "discount": 0}],
            "payments": [{"method": "cash", "amount": 118}],
            "client_ref": f"MSG-NC-{uuid.uuid4().hex[:8]}",
        })
        assert rs.status_code == 200
        sale_id = rs.json()["id"]
        r = owner.post(f"{API}/messaging/send-receipt",
                        json={"sale_id": sale_id, "channel": "whatsapp"})
        assert r.status_code == 400


class TestB2BReminder:
    def test_reminder(self, owner, b2b_customer, demo_product):
        # Create → dispatch → invoice
        r = owner.post(f"{API}/b2b/orders", json={
            "customer_id": b2b_customer["id"],
            "lines": [{"product_id": demo_product["id"], "sku": demo_product["sku"],
                       "name": demo_product["name"], "gst_rate": 18,
                       "quantity": 2, "unit_price": 100}],
        })
        oid = r.json()["id"]
        owner.post(f"{API}/b2b/orders/{oid}/dispatch")
        owner.post(f"{API}/b2b/orders/{oid}/invoice")
        rem = owner.post(f"{API}/b2b/orders/{oid}/remind?channel=whatsapp")
        assert rem.status_code == 200, rem.text
        assert rem.json()["ok"] is True
        # message log includes something (reminder inserted in b2b_reminders,
        # but let's just make sure /messaging/log responds)
        log = owner.get(f"{API}/messaging/log").json()
        assert isinstance(log, list)
