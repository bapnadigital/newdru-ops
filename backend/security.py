"""Shared security helpers: real client IP, rate limiting, security headers."""
from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware


def client_ip(request: Request) -> str:
    """Best-effort real client IP.

    Behind Cloudflare the edge sets CF-Connecting-IP and clients cannot forge it,
    because the app is only reachable through Cloudflare. X-Forwarded-For is only
    used when TRUST_X_FORWARDED_FOR=true (e.g. a trusted ingress), never by default,
    because anyone can send that header and dodge lockouts.
    """
    cf = request.headers.get("cf-connecting-ip", "").strip()
    if cf:
        return cf
    if os.environ.get("TRUST_X_FORWARDED_FOR", "false").lower() == "true":
        xff = request.headers.get("x-forwarded-for", "")
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


async def rate_limit(db, key: str, limit: int, window_seconds: int) -> None:
    """Fixed-window limiter stored in MongoDB. Raises 429 when exceeded."""
    now = datetime.now(timezone.utc)
    window_start = int(now.timestamp()) // window_seconds * window_seconds
    doc_id = f"{key}:{window_start}"
    res = await db.rate_limits.find_one_and_update(
        {"_id": doc_id},
        {"$inc": {"n": 1},
         "$setOnInsert": {"expires_at": now + timedelta(seconds=window_seconds * 2)}},
        upsert=True, return_document=True,
    )
    if res and res.get("n", 0) > limit:
        raise HTTPException(429, "Too many requests. Please wait a few minutes and try again.")


def secret_matches(provided: str | None, expected: str | None) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
