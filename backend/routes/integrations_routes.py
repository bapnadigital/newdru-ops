"""Integration status (stubs)."""
from fastapi import APIRouter, Depends
from auth import get_current_user, require_roles
from models import ROLE_OWNER
from services.integrations import PineLabsService, UnicommerceService, MessagingService
from services import unicommerce as uc

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/status")
async def status(user: dict = Depends(get_current_user)):
    return {
        "pinelabs": {"enabled": PineLabsService.enabled, "note": "Stub — plug in Pine Labs credentials later"},
        "unicommerce": {"enabled": uc.mode() == "live" and uc.configured(), "mode": uc.mode(),
                        "note": "Live stock + order sync; see Integrations page"},
        "messaging": {"enabled": MessagingService.enabled, "note": "Stub — WhatsApp/SMS/Omnisend"},
    }


@router.post("/unicommerce/pull")
async def unicommerce_pull(user: dict = Depends(require_roles(ROLE_OWNER))):
    # Kept for old clients; the real sync is POST /api/fc-sync/pull
    from fastapi import HTTPException
    raise HTTPException(410, "Use POST /api/fc-sync/pull")
