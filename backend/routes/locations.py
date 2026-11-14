"""Location routes."""
from fastapi import APIRouter, Depends
from auth import get_current_user

router = APIRouter(prefix="/api/locations", tags=["locations"])


@router.get("")
async def list_locations(user: dict = Depends(get_current_user)):
    from server import db
    return await db.locations.find({}, {"_id": 0}).to_list(100)
