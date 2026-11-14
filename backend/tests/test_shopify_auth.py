"""Shopify client-credentials token: fetched once, cached, sent on API calls."""
import asyncio
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_client_credentials_token_cached(monkeypatch):
    from mongomock_motor import AsyncMongoMockClient
    from services import shopify
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("SHOPIFY_SHOP_DOMAIN", "c2d881-f5.myshopify.com")
    monkeypatch.setenv("SHOPIFY_MODE", "pull_only")
    monkeypatch.delenv("SHOPIFY_ACCESS_TOKEN", raising=False)
    shopify._TOKEN_CACHE.clear()
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        if req.url.path == "/admin/oauth/access_token":
            assert b"grant_type=client_credentials" in req.content
            return httpx.Response(200, json={"access_token": "tok-24h", "expires_in": 86399})
        assert req.headers["x-shopify-access-token"] == "tok-24h"
        return httpx.Response(200, json={"orders": [{"id": 1}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(shopify.httpx, "AsyncClient",
                        lambda *a, **k: real(*a, transport=httpx.MockTransport(handler), **{x: y for x, y in k.items() if x != "transport"}))
    db = AsyncMongoMockClient()["shop_t"]

    async def go():
        r1 = await shopify.fetch_orders(db)
        r2 = await shopify.fetch_orders(db)
        return r1, r2, await shopify.get_config(db)

    r1, r2, cfg = asyncio.new_event_loop().run_until_complete(go())
    assert r1["ok"] and r2["ok"]
    assert sum(1 for c in calls if c.url.path == "/admin/oauth/access_token") == 1
    assert cfg["ready"] and cfg["client_credentials_set"]
