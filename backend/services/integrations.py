"""Stubbed external-integration services. Real credentials plug in later.

Every function logs its call and returns a status='not_configured' payload.
"""
import logging
from datetime import datetime, timezone

log = logging.getLogger("integrations")


class PineLabsService:
    """Card / UPI acceptance via Pine Labs. NOT IMPLEMENTED YET."""
    enabled = False

    @staticmethod
    def initiate_payment(amount: float, order_ref: str) -> dict:
        log.info("[STUB] PineLabs.initiate_payment amount=%s ref=%s", amount, order_ref)
        return {"status": "not_configured", "reference": order_ref}

    @staticmethod
    def poll_status(reference: str) -> dict:
        return {"status": "not_configured", "reference": reference}


class UnicommerceService:
    """Amazon/Flipkart FC inventory sync. NOT IMPLEMENTED YET."""
    enabled = False

    @staticmethod
    def pull_inventory() -> dict:
        log.info("[STUB] Unicommerce.pull_inventory")
        return {"status": "not_configured", "synced_at": datetime.now(timezone.utc).isoformat()}


class MessagingService:
    """WhatsApp / SMS / Omnisend outbound. NOT IMPLEMENTED YET."""
    enabled = False

    @staticmethod
    def send_receipt(channel: str, to: str, invoice_url: str) -> dict:
        log.info("[STUB] Messaging.send_receipt channel=%s to=%s", channel, to)
        return {"status": "not_configured", "channel": channel}
