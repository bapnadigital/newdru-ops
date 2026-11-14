"""WhatsApp (Gupshup) + SMS (MSG91) messaging.

Modes (per-provider):
- GUPSHUP_MODE      : disabled | simulator | live
- MSG91_MODE        : disabled | simulator | live

`simulator` records every message in the DB but never calls the provider.
`live` calls the provider HTTP endpoints when credentials are set.
"""
from __future__ import annotations
import os
import logging
import httpx
from datetime import datetime, timezone
from typing import Optional, Literal

log = logging.getLogger("messaging")

Channel = Literal["whatsapp", "sms"]


def _mode(kind: str) -> str:
    v = (os.environ.get(f"{kind}_MODE") or "simulator").lower()
    return v if v in ("disabled", "simulator", "live") else "disabled"


def _clean_phone(p: Optional[str]) -> Optional[str]:
    if not p: return None
    d = "".join(c for c in p if c.isdigit())
    # 91-prefix for India if not already
    if len(d) == 10: d = "91" + d
    return d or None


# ============================================================
# Gupshup WhatsApp
# ============================================================
async def send_whatsapp(to_phone: str, body: str, *, template_name: Optional[str] = None,
                        params: Optional[list] = None) -> dict:
    m = _mode("GUPSHUP")
    to = _clean_phone(to_phone)
    if not to: return {"status": "invalid_phone"}
    if m == "disabled":
        return {"status": "not_configured", "provider": "gupshup"}
    if m == "simulator":
        log.info("[gupshup.simulator] to=%s tpl=%s body=%s", to, template_name, body[:80])
        return {"status": "queued", "provider": "gupshup", "mode": "simulator", "to": to}
    api_key = os.environ.get("GUPSHUP_API_KEY")
    source = os.environ.get("GUPSHUP_SOURCE_NUMBER")
    app_name = os.environ.get("GUPSHUP_APP_NAME")
    if not (api_key and source and app_name):
        return {"status": "misconfigured", "provider": "gupshup",
                "note": "Set GUPSHUP_API_KEY, GUPSHUP_SOURCE_NUMBER, GUPSHUP_APP_NAME"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            "https://api.gupshup.io/wa/api/v1/msg",
            headers={"apikey": api_key, "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "channel": "whatsapp", "source": source, "destination": to,
                "message": '{"type":"text","text":"' + body.replace('"', '\\"') + '"}',
                "src.name": app_name,
            },
        )
        return {"status": "sent" if r.status_code == 200 else "error",
                "provider": "gupshup", "http": r.status_code, "response": r.text[:400]}


# ============================================================
# MSG91 SMS
# ============================================================
async def send_sms(to_phone: str, body: str, *, flow_id: Optional[str] = None,
                   variables: Optional[dict] = None) -> dict:
    m = _mode("MSG91")
    to = _clean_phone(to_phone)
    if not to: return {"status": "invalid_phone"}
    if m == "disabled":
        return {"status": "not_configured", "provider": "msg91"}
    if m == "simulator":
        log.info("[msg91.simulator] to=%s flow=%s body=%s", to, flow_id, body[:80])
        return {"status": "queued", "provider": "msg91", "mode": "simulator", "to": to}
    auth_key = os.environ.get("MSG91_AUTH_KEY")
    sender = os.environ.get("MSG91_SENDER_ID")
    if not auth_key:
        return {"status": "misconfigured", "provider": "msg91", "note": "Set MSG91_AUTH_KEY"}
    async with httpx.AsyncClient(timeout=15) as c:
        if flow_id:
            r = await c.post(
                "https://control.msg91.com/api/v5/flow/",
                headers={"authkey": auth_key, "Content-Type": "application/json"},
                json={"flow_id": flow_id, "sender": sender,
                      "recipients": [{"mobiles": to, **(variables or {})}]},
            )
        else:
            r = await c.get(
                "https://api.msg91.com/api/v5/sendhttp.php",
                params={"authkey": auth_key, "mobiles": to, "message": body,
                        "sender": sender or "NEWDRU", "route": "4", "country": "91"},
            )
        return {"status": "sent" if r.status_code == 200 else "error",
                "provider": "msg91", "http": r.status_code, "response": r.text[:400]}


# ============================================================
# High-level helpers used by routes
# ============================================================
async def send_receipt(customer: dict, sale: dict, channel: Channel = "whatsapp") -> dict:
    phone = customer.get("phone")
    if not phone: return {"status": "no_phone"}
    # Respect consent — the field is set by the CRM import + can be edited later.
    consent_key = "consent_whatsapp" if channel == "whatsapp" else "consent_sms"
    if customer.get(consent_key) is False:
        return {"status": "no_consent", "channel": channel}
    body = (
        f"Hi {customer.get('name') or 'there'}, thanks for shopping at Newdru!\n"
        f"Invoice {sale.get('invoice_no')} · Total ₹{sale.get('total'):.2f}\n"
        f"Show this at the store for any queries."
    )
    if channel == "whatsapp":
        return await send_whatsapp(phone, body)
    return await send_sms(phone, body)


async def send_payment_reminder(customer: dict, order: dict, channel: Channel = "whatsapp") -> dict:
    phone = customer.get("phone")
    if not phone: return {"status": "no_phone"}
    consent_key = "consent_whatsapp" if channel == "whatsapp" else "consent_sms"
    if customer.get(consent_key) is False:
        return {"status": "no_consent", "channel": channel}
    outstanding = order.get("outstanding") or 0
    due = (order.get("due_date") or "")[:10]
    body = (
        f"Hi {customer.get('name') or customer.get('company') or 'partner'}, this is a friendly reminder "
        f"from Newdru. Invoice {order.get('invoice_no') or order.get('order_no')} of ₹{float(order.get('total') or 0):.2f} "
        f"is due on {due}. Outstanding: ₹{float(outstanding):.2f}. Thanks!"
    )
    if channel == "whatsapp":
        return await send_whatsapp(phone, body)
    return await send_sms(phone, body)


def config_summary() -> dict:
    return {
        "gupshup": {"mode": _mode("GUPSHUP"),
                    "configured": all(os.environ.get(k) for k in
                                       ("GUPSHUP_API_KEY", "GUPSHUP_SOURCE_NUMBER", "GUPSHUP_APP_NAME"))},
        "msg91": {"mode": _mode("MSG91"),
                  "configured": bool(os.environ.get("MSG91_AUTH_KEY"))},
    }
