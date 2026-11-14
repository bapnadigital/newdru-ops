"""Shopify Admin API client — pull orders + push inventory levels.

Modes (env `SHOPIFY_MODE`):
  disabled | pull_only | full
Credentials come from env or `db.settings["shopify"]` (owner-set via UI).
Never raises to callers — always returns a status dict.
"""
import os
import logging
from typing import Optional
import httpx

log = logging.getLogger("newdru.shopify")

API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-10")

# Since Jan 2026 Shopify apps are made in the Dev Dashboard. For our own store we
# use the client credentials grant: Client ID + Client secret -> a 24-hour token,
# fetched and renewed automatically. A static SHOPIFY_ACCESS_TOKEN still works.
_TOKEN_CACHE: dict = {}


async def _client_credentials_token(domain: str) -> str:
    cid = (os.environ.get("SHOPIFY_CLIENT_ID") or "").strip()
    secret = (os.environ.get("SHOPIFY_CLIENT_SECRET") or "").strip()
    if not (cid and secret and domain):
        return ""
    import time
    hit = _TOKEN_CACHE.get(domain)
    if hit and hit[1] - time.time() > 120:
        return hit[0]
    d = domain.replace("https://", "").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"https://{d}/admin/oauth/access_token",
                             data={"grant_type": "client_credentials", "client_id": cid, "client_secret": secret},
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
        if r.status_code != 200:
            log.warning("shopify client-credentials token failed: HTTP %s", r.status_code)
            return ""
        data = r.json()
        tok = data.get("access_token") or ""
        if tok:
            _TOKEN_CACHE[domain] = (tok, time.time() + int(data.get("expires_in") or 3600))
        return tok
    except Exception as e:  # never raise to callers
        log.warning("shopify client-credentials token error: %s", e)
        return ""


async def _raw_settings(db) -> dict:
    doc = await db.settings.find_one({"_id": "shopify"}) or {}
    return {
        "shop_domain": (doc.get("shop_domain") or os.environ.get("SHOPIFY_SHOP_DOMAIN") or "").strip(),
        "access_token": (doc.get("access_token") or os.environ.get("SHOPIFY_ACCESS_TOKEN") or "").strip(),
        "location_id": (doc.get("location_id") or os.environ.get("SHOPIFY_LOCATION_ID") or "").strip(),
        "mode": (doc.get("mode") or os.environ.get("SHOPIFY_MODE") or "disabled").strip(),
        "webhook_secret": (doc.get("webhook_secret") or os.environ.get("SHOPIFY_WEBHOOK_SECRET") or "").strip(),
    }


async def _get_settings(db) -> dict:  # noqa: F811 - wraps the raw settings with a live token
    s = await _raw_settings(db)
    if not s["access_token"]:
        s["access_token"] = await _client_credentials_token(s["shop_domain"])
        s["auth"] = "client_credentials" if s["access_token"] else "none"
    else:
        s["auth"] = "static_token"
    return s


async def get_config(db) -> dict:
    s = await _raw_settings(db)
    has_cc = bool(os.environ.get("SHOPIFY_CLIENT_ID") and os.environ.get("SHOPIFY_CLIENT_SECRET"))
    return {
        "mode": s["mode"],
        "shop_domain": s["shop_domain"] or None,
        "location_id_set": bool(s["location_id"]),
        "access_token_set": bool(s["access_token"]) or has_cc,
        "client_credentials_set": has_cc,
        "webhook_secret_set": bool(s["webhook_secret"]),
        "ready": bool(s["shop_domain"] and (s["access_token"] or has_cc)) and s["mode"] != "disabled",
    }


async def save_settings(db, patch: dict) -> dict:
    """Owner sets shop_domain / access_token / location_id / mode / webhook_secret."""
    allowed = {"shop_domain", "access_token", "location_id", "mode", "webhook_secret"}
    clean = {k: (v or "").strip() for k, v in patch.items() if k in allowed and v is not None}
    if not clean:
        return await get_config(db)
    await db.settings.update_one({"_id": "shopify"}, {"$set": clean}, upsert=True)
    return await get_config(db)


def _headers(token: str) -> dict:
    return {"X-Shopify-Access-Token": token, "Content-Type": "application/json", "Accept": "application/json"}


def _base(domain: str) -> str:
    d = domain.replace("https://", "").rstrip("/")
    return f"https://{d}/admin/api/{API_VERSION}"


async def fetch_orders(db, since_iso: Optional[str] = None, limit: int = 50) -> dict:
    """Pull most recent orders from Shopify (since given ISO date). Read-only."""
    s = await _get_settings(db)
    if s["mode"] == "disabled":
        return {"ok": False, "reason": "disabled", "orders": []}
    if not s["shop_domain"] or not s["access_token"]:
        return {"ok": False, "reason": "not_configured", "orders": []}
    params = {"limit": min(int(limit), 250), "status": "any", "order": "created_at desc"}
    if since_iso:
        params["updated_at_min"] = since_iso
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{_base(s['shop_domain'])}/orders.json",
                            headers=_headers(s["access_token"]), params=params)
            if r.status_code != 200:
                return {"ok": False, "reason": f"http_{r.status_code}", "body": r.text[:200], "orders": []}
            return {"ok": True, "orders": r.json().get("orders", [])}
    except Exception as e:
        log.exception("shopify.fetch_orders failed: %s", e)
        return {"ok": False, "reason": f"exception:{e}", "orders": []}


async def push_inventory(db, sku: str, quantity: int) -> dict:
    """Set absolute inventory for a SKU at the configured Shopify location.
    Requires access to inventory_levels/set (needs write_inventory scope).
    """
    s = await _get_settings(db)
    if s["mode"] != "full":
        return {"ok": False, "reason": "mode_not_full"}
    if not (s["shop_domain"] and s["access_token"] and s["location_id"]):
        return {"ok": False, "reason": "not_configured"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            # 1) SKU → inventory_item_id (via variants.json?sku=)
            r = await c.get(f"{_base(s['shop_domain'])}/variants.json",
                            headers=_headers(s["access_token"]), params={"sku": sku})
            if r.status_code != 200:
                return {"ok": False, "reason": f"variant_lookup_http_{r.status_code}"}
            variants = r.json().get("variants", [])
            if not variants:
                return {"ok": False, "reason": "sku_not_found"}
            inv_item_id = variants[0].get("inventory_item_id")
            if not inv_item_id:
                return {"ok": False, "reason": "no_inventory_item"}
            # 2) POST inventory_levels/set
            r = await c.post(
                f"{_base(s['shop_domain'])}/inventory_levels/set.json",
                headers=_headers(s["access_token"]),
                json={"location_id": int(s["location_id"]),
                      "inventory_item_id": int(inv_item_id),
                      "available": int(quantity)},
            )
            if r.status_code not in (200, 201):
                return {"ok": False, "reason": f"set_http_{r.status_code}", "body": r.text[:200]}
            return {"ok": True, "sku": sku, "available": int(quantity)}
    except Exception as e:
        log.exception("shopify.push_inventory failed: %s", e)
        return {"ok": False, "reason": f"exception:{e}"}
