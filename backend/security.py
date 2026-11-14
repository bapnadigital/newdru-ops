"""Shared security helpers: real client IP, rate limiting, security headers."""
from __future__ import annotations

import csv
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


# ---- Spreadsheet formula injection ----
# A customer can type "=HYPERLINK(...)" as their name on the public warranty form.
# When the owner opens an export in Excel that would run as a formula. Prefix
# such cells with an apostrophe so Excel shows them as plain text.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v):
    if isinstance(v, str) and v.startswith(_FORMULA_START):
        return "'" + v
    return v


class _SafeWriter:
    def __init__(self, w):
        self._w = w

    def writerow(self, row):
        return self._w.writerow([safe_cell(c) for c in row])

    def writerows(self, rows):
        for r in rows:
            self.writerow(r)


class _SafeDictWriter(csv.DictWriter):
    def writerow(self, rowdict):
        return super().writerow({k: safe_cell(v) for k, v in rowdict.items()})


def safe_csv_writer(f, *a, **kw):
    return _SafeWriter(csv.writer(f, *a, **kw))


def SafeDictWriter(f, *a, **kw):  # noqa: N802 - mirrors csv.DictWriter
    return _SafeDictWriter(f, *a, **kw)


# ---- Request size cap ----
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_BYTES", str(6 * 1024 * 1024)))


class MaxBodySizeMiddleware:
    """Reject requests bigger than MAX_BODY_BYTES (6 MB) before reading them."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for k, v in scope.get("headers") or []:
            if k == b"content-length":
                try:
                    if int(v) > MAX_BODY_BYTES:
                        return await _too_large(send)
                except ValueError:
                    return await _too_large(send)
        received = 0

        async def limited_receive():
            nonlocal received
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > MAX_BODY_BYTES:
                    raise _TooLarge()
            return msg

        try:
            return await self.app(scope, limited_receive, send)
        except _TooLarge:
            return await _too_large(send)


class _TooLarge(Exception):
    pass


async def _too_large(send):
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": b'{"detail":"File or request too large (max 6 MB)."}'})


# Content Security Policy for the web app: only our own scripts may run.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob: https:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")

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
        else:
            response.headers.setdefault("Content-Security-Policy", CSP)
        return response
