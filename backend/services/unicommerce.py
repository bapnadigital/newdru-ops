"""Unicommerce (Uniware) API client — read-only.

Docs: https://documentation.unicommerce.com/docs/using-the-uniware-apis.html

Settings (Cloudflare secrets / backend .env — never in code):
    UNICOMMERCE_MODE        disabled | csv_only | live
    UNICOMMERCE_TENANT      the part before .unicommerce.com in your Uniware URL
    UNICOMMERCE_USER        a dedicated Uniware API user (Admin, access to the facilities below)
    UNICOMMERCE_PASSWORD    that user's password
    UNICOMMERCE_FACILITIES  app location = Uniware facility code, comma separated,
                            e.g. "AMAZON_FC=AMZFBA01,FLIPKART_FC=FKSMART01"
                            Only mapped locations are ever overwritten by the sync.

Reads: OAuth token, inventory snapshot, sale order search/get.
Writes: only replace_inventory(), and only when the owner runs a stock push
(UNICOMMERCE_PUSH_ENABLED=true, after a preview). Nothing else is ever changed.

Push settings:
    UNICOMMERCE_PUSH_LOCATION   app location whose stock is sent (e.g. BHIWANDI)
    UNICOMMERCE_PUSH_FACILITY   Uniware facility that receives it (e.g. bapnadigital)
    UNICOMMERCE_SHELF           Uniware shelf code to put stock on (default DEFAULT)
    UNICOMMERCE_PUSH_ENABLED    true to allow real pushes (previews always allowed)
    UNICOMMERCE_AUTO_PUSH       true to push automatically on the schedule
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Iterable, List, Optional

import httpx

log = logging.getLogger("unicommerce")

CLIENT_ID = "my-trusted-client"  # fixed value from Unicommerce's OAuth docs
SNAPSHOT_MAX_SKUS = 10_000
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class UnicommerceError(Exception):
    pass


def mode() -> str:
    m = (os.environ.get("UNICOMMERCE_MODE") or "disabled").lower()
    return m if m in ("disabled", "csv_only", "live") else "disabled"


def facility_map() -> Dict[str, str]:
    """{"AMAZON_FC": "AMZFBA01", ...} from UNICOMMERCE_FACILITIES."""
    out: Dict[str, str] = {}
    for part in (os.environ.get("UNICOMMERCE_FACILITIES") or "").split(","):
        if "=" in part:
            loc, fac = part.split("=", 1)
            if loc.strip() and fac.strip():
                out[loc.strip().upper()] = fac.strip()
    return out


def push_settings() -> Dict[str, object]:
    return {
        "location": (os.environ.get("UNICOMMERCE_PUSH_LOCATION") or "").upper() or None,
        "facility": os.environ.get("UNICOMMERCE_PUSH_FACILITY") or None,
        "shelf": os.environ.get("UNICOMMERCE_SHELF") or "DEFAULT",
        "enabled": (os.environ.get("UNICOMMERCE_PUSH_ENABLED") or "false").lower() == "true",
        "auto": (os.environ.get("UNICOMMERCE_AUTO_PUSH") or "false").lower() == "true",
    }


def configured() -> bool:
    return all(os.environ.get(k) for k in ("UNICOMMERCE_TENANT", "UNICOMMERCE_USER", "UNICOMMERCE_PASSWORD"))


class UnicommerceClient:
    def __init__(self, tenant: str, username: str, password: str,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        if not tenant or "/" in tenant or "." in tenant:
            raise UnicommerceError("UNICOMMERCE_TENANT must be just the tenant name, e.g. 'newdru'")
        self.base = f"https://{tenant}.unicommerce.com"
        self._user = username
        self._password = password
        self._transport = transport
        self._token: Optional[str] = None
        self._refresh: Optional[str] = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    @classmethod
    def from_env(cls, transport: Optional[httpx.AsyncBaseTransport] = None) -> "UnicommerceClient":
        if not configured():
            raise UnicommerceError("Unicommerce login is not set (UNICOMMERCE_TENANT / USER / PASSWORD).")
        return cls(os.environ["UNICOMMERCE_TENANT"].strip(), os.environ["UNICOMMERCE_USER"],
                   os.environ["UNICOMMERCE_PASSWORD"], transport=transport)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base, timeout=TIMEOUT, transport=self._transport)

    # ---------- auth ----------
    async def _get_token(self) -> str:
        async with self._lock:
            if self._token and time.time() < self._expires_at - 120:
                return self._token
            params: Dict[str, str]
            if self._refresh:
                params = {"grant_type": "refresh_token", "client_id": CLIENT_ID,
                          "refresh_token": self._refresh}
            else:
                params = {"grant_type": "password", "client_id": CLIENT_ID,
                          "username": self._user, "password": self._password}
            async with self._client() as c:
                r = await c.get("/oauth/token", params=params,
                                headers={"Content-Type": "application/json"})
            if r.status_code != 200 and self._refresh:
                # refresh token expired: log in again once
                self._refresh = None
                async with self._client() as c:
                    r = await c.get("/oauth/token", params={
                        "grant_type": "password", "client_id": CLIENT_ID,
                        "username": self._user, "password": self._password},
                        headers={"Content-Type": "application/json"})
            if r.status_code != 200:
                raise UnicommerceError(f"Unicommerce login failed (HTTP {r.status_code}). Check the API user and password.")
            data = r.json()
            self._token = data.get("access_token")
            self._refresh = data.get("refresh_token") or self._refresh
            self._expires_at = time.time() + int(data.get("expires_in") or 3600)
            if not self._token:
                raise UnicommerceError("Unicommerce login returned no access token.")
            return self._token

    async def _post(self, path: str, body: dict, facility: Optional[str] = None) -> dict:
        for attempt in (1, 2):
            token = await self._get_token()
            headers = {"Content-Type": "application/json", "Authorization": f"bearer {token}"}
            if facility:
                headers["Facility"] = facility
            async with self._client() as c:
                r = await c.post(path, json=body, headers=headers)
            if r.status_code == 401 and attempt == 1:
                self._token = None  # force re-login and retry once
                self._expires_at = 0
                continue
            if r.status_code >= 400:
                raise UnicommerceError(f"Unicommerce {path} failed (HTTP {r.status_code}).")
            data = r.json()
            if data.get("successful") is False:
                msgs = "; ".join((e.get("description") or e.get("message") or "") for e in data.get("errors") or [])
                raise UnicommerceError(f"Unicommerce {path}: {msgs or data.get('message') or 'request failed'}")
            return data
        raise UnicommerceError("Unicommerce authentication failed.")

    # ---------- inventory ----------
    async def inventory_snapshot(self, facility: str, skus: Iterable[str]) -> List[dict]:
        skus = [s for s in skus if s]
        out: List[dict] = []
        for i in range(0, len(skus), SNAPSHOT_MAX_SKUS):
            data = await self._post("/services/rest/v1/inventory/inventorySnapshot/get",
                                    {"itemTypeSKUs": skus[i:i + SNAPSHOT_MAX_SKUS]}, facility=facility)
            out.extend(data.get("inventorySnapshots") or [])
        return out

    async def replace_inventory(self, facility: str, items: List[dict], shelf_code: str,
                                remarks: str = "NEWDRU Ops stock sync") -> List[dict]:
        """Set GOOD_INVENTORY to an absolute quantity per SKU (adjustmentType REPLACE).
        items: [{"sku": "...", "quantity": 12}]. Returns per-item results."""
        results: List[dict] = []
        for i in range(0, len(items), 200):
            chunk = items[i:i + 200]
            body = {"inventoryAdjustments": [{
                "itemSKU": it["sku"], "quantity": int(it["quantity"]), "shelfCode": shelf_code,
                "inventoryType": "GOOD_INVENTORY", "adjustmentType": "REPLACE",
                "facilityCode": facility, "remarks": remarks[:255],
            } for it in chunk]}
            data = await self._post("/services/rest/v1/inventory/adjust/bulk", body, facility=facility)
            for it, r in zip(chunk, data.get("inventoryAdjustmentResponses") or []):
                errs = "; ".join((e.get("description") or e.get("message") or "") for e in r.get("errors") or [])
                results.append({"sku": it["sku"], "quantity": it["quantity"],
                                "ok": bool(r.get("successful")), "error": errs or None})
        return results

    # ---------- orders ----------
    async def search_orders(self, *, updated_since_minutes: Optional[int] = None,
                            from_date: Optional[str] = None, to_date: Optional[str] = None,
                            page_size: int = 100, max_pages: int = 50) -> List[dict]:
        out: List[dict] = []
        for page in range(max_pages):
            body: Dict[str, Any] = {"searchOptions": {"displayStart": page * page_size,
                                                      "displayLength": page_size}}
            if updated_since_minutes:
                body["updatedSinceInMinutes"] = int(updated_since_minutes)
            else:
                body.update({"dateType": "CREATED", "fromDate": from_date, "toDate": to_date})
            data = await self._post("/services/rest/v1/oms/saleOrder/search", body)
            rows = data.get("elements") or []
            out.extend(rows)
            if len(rows) < page_size:
                break
        return out

    async def get_order(self, code: str) -> dict:
        data = await self._post("/services/rest/v1/oms/saleorder/get", {"code": code})
        return data.get("saleOrderDTO") or {}
