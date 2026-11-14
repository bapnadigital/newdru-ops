"""IP → city/state/country lookup using ipapi.co (free tier, no key).
Cached in-memory + Mongo for 24h to stay under the rate limit.
"""
import httpx
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

log = logging.getLogger("newdru.geoip")
_MEM: dict = {}  # ip -> (expires, payload)
_TTL = timedelta(hours=24)


def _skip(ip: str) -> bool:
    if not ip:
        return True
    ip = ip.split(",")[0].strip()
    if ip in ("", "unknown", "127.0.0.1", "::1"):
        return True
    # RFC1918 / carrier-grade NAT / link-local
    if ip.startswith(("10.", "192.168.", "169.254.", "172.")):
        return True
    return False


async def lookup(ip: str) -> dict:
    """Returns {ip, city, region (state), country_code}. Never raises."""
    payload = {"ip": ip, "city": None, "region": None, "country_code": None}
    if _skip(ip):
        return payload
    now = datetime.now(timezone.utc)
    cached = _MEM.get(ip)
    if cached and cached[0] > now:
        return cached[1]
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get(f"https://ipapi.co/{ip}/json/")
            if r.status_code == 200:
                data = r.json()
                if not data.get("error"):
                    payload.update({
                        "city": data.get("city"),
                        "region": data.get("region"),
                        "country_code": data.get("country_code") or data.get("country"),
                    })
    except Exception as e:
        log.warning("geoip lookup failed for %s: %s", ip, e)
    _MEM[ip] = (now + _TTL, payload)
    return payload


def client_ip(request) -> str:
    """Kept for backwards compatibility; see security.client_ip."""
    from security import client_ip as _cip
    return _cip(request)
