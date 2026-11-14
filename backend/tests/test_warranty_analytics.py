"""Warranty Analytics extension tests (iteration_6)."""
import os
import re
from datetime import datetime

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
    return r.json().get("token")


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def owner_token():
    t = _login(*OWNER)
    assert t, "owner login failed"
    return t


@pytest.fixture(scope="module")
def store_token():
    t = _login(*STORE)
    assert t, "store manager login failed"
    return t


@pytest.fixture(scope="module")
def cashier_token():
    t = _login(*CASHIER)
    assert t, "cashier login failed"
    return t


REQUIRED_KEYS = {
    "total", "last_30_days", "prev_30_days", "mom_change_pct",
    "active", "claims_open", "claims_total", "claim_rate_pct",
    "by_source", "by_state", "top_skus", "mom_series",
}


# ---- Shape / access ----
def test_owner_shape(owner_token):
    r = requests.get(f"{API}/warranty/analytics", headers=_h(owner_token), timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    missing = REQUIRED_KEYS - set(data.keys())
    assert not missing, f"missing keys: {missing}"
    assert isinstance(data["by_source"], list)
    assert isinstance(data["by_state"], list)
    assert isinstance(data["top_skus"], list)
    assert isinstance(data["mom_series"], list)


def test_store_manager_can_access(store_token):
    r = requests.get(f"{API}/warranty/analytics", headers=_h(store_token), timeout=15)
    assert r.status_code == 200


def test_cashier_forbidden(cashier_token):
    r = requests.get(f"{API}/warranty/analytics", headers=_h(cashier_token), timeout=15)
    assert r.status_code == 403


# ---- months param ----
@pytest.mark.parametrize("months,expected", [(3, 3), (6, 6), (12, 12), (24, 24)])
def test_mom_series_length(owner_token, months, expected):
    r = requests.get(f"{API}/warranty/analytics", headers=_h(owner_token),
                     params={"months": months}, timeout=15)
    assert r.status_code == 200
    assert len(r.json()["mom_series"]) == expected


def test_months_clamp_low(owner_token):
    r = requests.get(f"{API}/warranty/analytics", headers=_h(owner_token),
                     params={"months": 1}, timeout=15)
    assert r.status_code == 200
    assert len(r.json()["mom_series"]) == 3


def test_months_clamp_high(owner_token):
    r = requests.get(f"{API}/warranty/analytics", headers=_h(owner_token),
                     params={"months": 99}, timeout=15)
    assert r.status_code == 200
    assert len(r.json()["mom_series"]) == 24


# ---- month labels: YYYY-MM chronological, no gaps ----
def test_mom_series_labels_chronological_no_gaps(owner_token):
    r = requests.get(f"{API}/warranty/analytics", headers=_h(owner_token),
                     params={"months": 12}, timeout=15)
    assert r.status_code == 200
    series = r.json()["mom_series"]
    labels = [s["month"] for s in series]
    # Format YYYY-MM
    for lb in labels:
        assert re.match(r"^\d{4}-\d{2}$", lb), f"bad label {lb}"
    # Chronological oldest first
    assert labels == sorted(labels)
    # No gaps: each next month = prev + 1
    def _to_int(lb):
        y, m = lb.split("-")
        return int(y) * 12 + int(m)
    ints = [_to_int(lb) for lb in labels]
    for i in range(1, len(ints)):
        assert ints[i] - ints[i - 1] == 1, f"gap between {labels[i-1]} and {labels[i]}"


# ---- Seeded data assertions ----
def test_bapna_black_claim_rate(owner_token):
    r = requests.get(f"{API}/warranty/analytics", headers=_h(owner_token), timeout=15)
    assert r.status_code == 200
    data = r.json()
    match = [s for s in data["top_skus"] if s["sku"] == "BAPNA-BLACK"]
    assert match, "BAPNA-BLACK missing from top_skus"
    row = match[0]
    # Verify formula holds for the seeded SKU regardless of exact claim count
    assert row["count"] >= 1
    expected = round(row["claims"] / row["count"] * 100, 2)
    assert row["claim_rate_pct"] == expected


def test_mom_change_pct_prev0_last_positive(owner_token):
    r = requests.get(f"{API}/warranty/analytics", headers=_h(owner_token), timeout=15)
    data = r.json()
    if data["prev_30_days"] == 0 and data["last_30_days"] > 0:
        assert data["mom_change_pct"] == 100.0


def test_mom_change_pct_formula(owner_token):
    r = requests.get(f"{API}/warranty/analytics", headers=_h(owner_token), timeout=15)
    data = r.json()
    last = data["last_30_days"]
    prev = data["prev_30_days"]
    if prev > 0:
        expected = round((last - prev) / prev * 100, 1)
        assert data["mom_change_pct"] == expected


def test_top_skus_claim_rate_formula(owner_token):
    r = requests.get(f"{API}/warranty/analytics", headers=_h(owner_token), timeout=15)
    data = r.json()
    for s in data["top_skus"]:
        if s["count"] > 0:
            expected = round(s["claims"] / s["count"] * 100, 2)
            assert s["claim_rate_pct"] == expected


def test_unauth(owner_token):
    r = requests.get(f"{API}/warranty/analytics", timeout=15)
    assert r.status_code in (401, 403)
