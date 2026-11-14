"""Integration status (stubs)."""
from fastapi import APIRouter, Depends
from auth import get_current_user, require_roles
from models import ROLE_OWNER
from services.integrations import PineLabsService, UnicommerceService, MessagingService

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/status")
async def status(user: dict = Depends(get_current_user)):
    return {
        "pinelabs": {"enabled": PineLabsService.enabled, "note": "Stub — plug in Pine Labs credentials later"},
        "unicommerce": {"enabled": UnicommerceService.enabled, "note": "Stub — Amazon/Flipkart FC sync"},
        "messaging": {"enabled": MessagingService.enabled, "note": "Stub — WhatsApp/SMS/Omnisend"},
    }


@router.post("/unicommerce/pull")
async def unicommerce_pull(user: dict = Depends(require_roles(ROLE_OWNER))):
    return UnicommerceService.pull_inventory()
