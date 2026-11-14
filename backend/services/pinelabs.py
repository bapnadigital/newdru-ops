"""Pine Labs Plutus Cloud Integration client.

Modes (env `PINELABS_MODE`):
- disabled  : all calls return {status:"not_configured"}
- simulator : local stub returns realistic mock responses; approvals granted via
              /api/pinelabs/simulate/{ptr_id}/approve  (dev only)
- uat / production : real HTTP calls to Pine Labs Cloud API

Amounts are always in PAISE (integer) end-to-end.
NEVER stores raw PAN / CVV / PIN. Only masked_pan, rrn, approval_code, acquirer.
"""
from __future__ import annotations
import os
import logging
import secrets
import httpx
from datetime import datetime, timezone
from typing import Optional, Literal

log = logging.getLogger("pinelabs")

Mode = Literal["disabled", "simulator", "uat", "production"]


def _mode() -> Mode:
    m = (os.environ.get("PINELABS_MODE") or "simulator").lower()
    return m if m in ("disabled", "simulator", "uat", "production") else "disabled"


def _base_url() -> str:
    if _mode() == "production":
        return os.environ.get("PINELABS_PROD_URL", "https://plutuscloudservice.in:8201")
    return os.environ.get("PINELABS_UAT_URL", "https://www.plutuscloudserviceuat.in:8201")


def _cred(k: str, default: str = "") -> str:
    return os.environ.get(k, default) or ""


# --- DB-backed credentials (owner can save from Integrations screen; overrides env) ---
_SETTINGS_CACHE: dict = {}


async def load_db_settings(db) -> dict:
    """Fetch pinelabs settings from db.settings (singleton row id='pinelabs')."""
    global _SETTINGS_CACHE
    doc = await db.settings.find_one({"_id": "pinelabs"})
    _SETTINGS_CACHE = doc or {}
    return _SETTINGS_CACHE


def _s(key: str, env_fallback: str) -> str:
    return (_SETTINGS_CACHE.get(key) or _cred(env_fallback) or "").strip()


async def save_db_settings(db, patch: dict) -> dict:
    global _SETTINGS_CACHE
    patch = {k: (v or None) for k, v in patch.items()}
    await db.settings.update_one(
        {"_id": "pinelabs"}, {"$set": patch}, upsert=True,
    )
    _SETTINGS_CACHE = {**(_SETTINGS_CACHE or {}), **patch}
    return _SETTINGS_CACHE


PAYMENT_MODE_MAP = {"card": "1", "upi": "10"}


class PineLabsClient:
    """Async client. Use one instance per app."""

    def __init__(self):
        self._http: Optional[httpx.AsyncClient] = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=25)
        return self._http

    async def close(self):
        if self._http is not None:
            await self._http.aclose()

    def _base_payload(self, terminal_id: Optional[str] = None) -> dict:
        return {
            "MerchantID": _s("merchant_id", "PINELABS_MERCHANT_ID"),
            "SecurityToken": _s("security_token", "PINELABS_SECURITY_TOKEN"),
            "ClientId": terminal_id or _s("terminal_id", "PINELABS_TERMINAL_ID"),
            "StoreId": _s("store_id", "PINELABS_STORE_ID"),
            "UserID": _s("user_id", "PINELABS_USER_ID") or "newdru-pos",
        }

    async def upload_billed_transaction(
        self, *, transaction_number: str, amount_paise: int, mode: str, terminal_id: Optional[str] = None
    ) -> dict:
        m = _mode()
        if m == "disabled":
            return {"status": "not_configured"}
        if m == "simulator":
            # Return a fake PTR id shaped like Pine Labs (long numeric)
            ptr_id = "SIM" + "".join(secrets.choice("0123456789") for _ in range(9))
            log.info("[pinelabs.simulator] upload txn=%s amount=%s mode=%s -> ptr=%s",
                     transaction_number, amount_paise, mode, ptr_id)
            return {
                "ResponseCode": 0,
                "ResponseMessage": "Success",
                "PlutusTransactionReferenceID": ptr_id,
                "TransactionNumber": transaction_number,
            }
        payload = {
            **self._base_payload(terminal_id),
            "TransactionNumber": transaction_number,
            "SequenceNumber": "1",
            "Amount": str(int(amount_paise)),
            "AllowedPaymentMode": PAYMENT_MODE_MAP.get(mode, "1"),
            "AutoCancelDurationInMinutes": "5",
            "ForceCancelOnBack": "TRUE",
        }
        r = await self.http.post(f"{_base_url()}/API/CloudBasedIntegration/V1/UploadBilledTransaction", json=payload)
        r.raise_for_status()
        return r.json()

    async def get_status(self, ptr_id: str, transaction_number: str, db=None) -> dict:
        m = _mode()
        if m == "disabled":
            return {"status": "not_configured"}
        if m == "simulator":
            # Status is manipulated via /simulate/{ptr_id}/approve in dev.
            # `db` is injected by the caller (route handler); this avoids importing
            # `server` here which would create a circular import.
            if db is None:
                return {"ResponseCode": 1, "ResponseMessage": "No db handle for simulator"}
            doc = await db.pinelabs_txns.find_one({"ptr_id": ptr_id}, {"_id": 0})
            if not doc:
                return {"ResponseCode": 1, "ResponseMessage": "Unknown PTR"}
            return {
                "ResponseCode": 0 if doc.get("status") == "APPROVED" else 1001,
                "ResponseMessage": doc.get("status", "OPEN"),
                "PlutusTransactionReferenceID": ptr_id,
                "TransactionNumber": transaction_number,
                "RRN": doc.get("rrn"),
                "ApprovalCode": doc.get("approval_code"),
                "MaskedPAN": doc.get("masked_pan"),
                "Acquirer": doc.get("acquirer"),
            }
        payload = {
            **self._base_payload(),
            "PlutusTransactionReferenceID": ptr_id,
            "TransactionNumber": transaction_number,
        }
        r = await self.http.post(f"{_base_url()}/API/CloudBasedIntegration/V1/GetCloudBasedTxnStatus", json=payload)
        r.raise_for_status()
        return r.json()

    async def cancel(self, ptr_id: str) -> dict:
        m = _mode()
        if m == "disabled":
            return {"status": "not_configured"}
        if m == "simulator":
            return {"ResponseCode": 0, "ResponseMessage": "Cancelled",
                    "PlutusTransactionReferenceID": ptr_id}
        payload = {**self._base_payload(), "PlutusTransactionReferenceID": ptr_id}
        r = await self.http.post(f"{_base_url()}/API/CloudBasedIntegration/V1/CancelTransaction", json=payload)
        r.raise_for_status()
        return r.json()


pinelabs = PineLabsClient()


def normalize_status(pl_status: str) -> str:
    """Map Pine Labs status strings to our internal states."""
    s = (pl_status or "").upper()
    if s in ("APPROVED", "SUCCESS", "SUCCESSFUL"): return "APPROVED"
    if s in ("DECLINED", "FAILED", "FAILURE"): return "DECLINED"
    if s in ("CANCELLED", "CANCELED", "USER_CANCELLED"): return "CANCELLED"
    if s in ("TIMEOUT", "TIMED_OUT"): return "TIMEOUT"
    if s in ("PENDING", "OPEN", "IN_PROGRESS"): return "OPEN"
    return "OPEN"


def config_summary() -> dict:
    m = _mode()
    return {
        "mode": m,
        "base_url": _base_url() if m in ("uat", "production") else None,
        "merchant_id_set": bool(_s("merchant_id", "PINELABS_MERCHANT_ID")),
        "security_token_set": bool(_s("security_token", "PINELABS_SECURITY_TOKEN")),
        "store_id_set": bool(_s("store_id", "PINELABS_STORE_ID")),
        "terminal_id_set": bool(_s("terminal_id", "PINELABS_TERMINAL_ID")),
        "credentials_source": "db" if _SETTINGS_CACHE else "env",
        "note": {
            "disabled": "Set PINELABS_MODE=simulator to test the flow with a fake terminal.",
            "simulator": "Live mode disabled. Approve payments via /api/pinelabs/simulate/{ptr_id}/approve.",
            "uat": "UAT — Pine Labs test terminal.",
            "production": "PRODUCTION — real merchant terminal.",
        }[m],
    }
