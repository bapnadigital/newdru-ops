"""Auth & RBAC helpers for Newdru."""
import os
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from fastapi import Request, HTTPException, Depends
from typing import Optional

JWT_ALGORITHM = "HS256"
ACCESS_TTL_MIN = 60 * 8
REFRESH_TTL_DAYS = 7


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# Same-site cookies: the app and API share one domain in production, so "lax"
# blocks cross-site request forgery. Set COOKIE_SAMESITE=none only for a split
# frontend/backend setup (e.g. the old Emergent preview).
COOKIE_SAMESITE = os.environ.get("COOKIE_SAMESITE", "lax").lower()


def create_access_token(user_id: str, email: str, role: str, token_version: int = 0) -> str:
    payload = {
        "sub": user_id, "email": email, "role": role, "type": "access", "tv": token_version,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TTL_MIN),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, token_version: int = 0) -> str:
    payload = {
        "sub": user_id, "type": "refresh", "tv": token_version,
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_TTL_DAYS),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def _get_db(request: Request):
    return request.app.state.db


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    db = _get_db(request)
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="User account disabled")
    # Password change / deactivation / "log out everywhere" bumps token_version,
    # which kills every token issued before it.
    if int(payload.get("tv", 0)) != int(user.get("token_version", 0)):
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    # Signed in with the old public demo password: only allowed to set a new one.
    if user.get("must_change_password") and request.url.path not in MUST_CHANGE_ALLOWED:
        raise HTTPException(status_code=403, detail="Please set a new password first.")
    return user


# Passwords that were ever public (old demo / docs). Never accepted as a working password.
KNOWN_PUBLIC_PASSWORDS = {"Newdru@2026"}
MUST_CHANGE_ALLOWED = {"/api/auth/me", "/api/auth/change-password", "/api/auth/logout"}


def require_roles(*roles: str):
    async def _dep(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail=f"Requires role: {', '.join(roles)}")
        return user
    return _dep


def can_see_cost(user: dict) -> bool:
    from models import COST_HIDDEN_ROLES
    return user.get("role") not in COST_HIDDEN_ROLES


def set_auth_cookies(response, access_token: str, refresh_token: str):
    response.set_cookie(
        key="access_token", value=access_token, httponly=True,
        secure=True, samesite=COOKIE_SAMESITE, max_age=ACCESS_TTL_MIN * 60, path="/",
    )
    response.set_cookie(
        key="refresh_token", value=refresh_token, httponly=True,
        secure=True, samesite=COOKIE_SAMESITE, max_age=REFRESH_TTL_DAYS * 86400, path="/",
    )


def clear_auth_cookies(response):
    response.delete_cookie("access_token", path="/", secure=True, httponly=True, samesite=COOKIE_SAMESITE)
    response.delete_cookie("refresh_token", path="/", secure=True, httponly=True, samesite=COOKIE_SAMESITE)


async def audit(db, user: Optional[dict], action: str, entity: str,
                entity_id: Optional[str] = None, details: Optional[dict] = None):
    from models import gen_id, now_iso
    entry = {
        "id": gen_id(),
        "user_id": user.get("id") if user else None,
        "user_name": user.get("name") if user else None,
        "action": action, "entity": entity, "entity_id": entity_id,
        "details": details, "created_at": now_iso(),
    }
    await db.audit_logs.insert_one(entry)


def log_export(name: str):
    """Dependency: record who downloaded which export (owner sees it in Audit)."""
    async def _dep(request: Request, user: dict = Depends(get_current_user)) -> None:
        params = {k: v for k, v in request.query_params.items() if k not in ("token",)}
        await audit(request.app.state.db, user, f"export.{name}", "export", None,
                    {"params": params, "ip": request.headers.get("cf-connecting-ip")})
    return _dep
