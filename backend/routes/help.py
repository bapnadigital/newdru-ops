"""Serve the on-disk USER_GUIDE.md so the in-app /help page can render it."""
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response

from auth import get_current_user

router = APIRouter(prefix="/help", tags=["help"])

# Works on Emergent (/app) and on any other host: the guide sits at repo root.
GUIDE_PATH = Path(__file__).resolve().parents[2] / "USER_GUIDE.md"


def _read_guide() -> str:
    try:
        return GUIDE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise HTTPException(404, "User guide not found on disk")


@router.get("/user-guide")
async def user_guide(user: dict = Depends(get_current_user)):
    return {"markdown": _read_guide()}


@router.get("/user-guide.md")
async def user_guide_raw(user: dict = Depends(get_current_user)):
    return Response(content=_read_guide(), media_type="text/markdown",
                    headers={"Content-Disposition": 'attachment; filename="Newdru-User-Guide.md"'})
