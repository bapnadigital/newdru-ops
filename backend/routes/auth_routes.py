"""Auth routes: login, logout, me, refresh."""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Response, HTTPException, Depends
import jwt

from models import LoginIn, now_iso
from security import client_ip, rate_limit
from auth import (
    verify_password, create_access_token, create_refresh_token,
    set_auth_cookies, clear_auth_cookies, get_current_user, audit,
    get_jwt_secret, JWT_ALGORITHM, ACCESS_TTL_MIN, COOKIE_SAMESITE,
    hash_password, KNOWN_PUBLIC_PASSWORDS,
)
from pydantic import BaseModel, Field

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_ATTEMPTS = 5            # per IP + email
MAX_ATTEMPTS_PER_EMAIL = 15  # across all IPs, stops distributed guessing
LOCKOUT_MIN = 15


def _sanitize(user: dict) -> dict:
    return {k: v for k, v in user.items() if k not in {"_id", "password_hash"}}


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response):
    db = request.app.state.db
    email = body.email.lower().strip()
    real_ip = client_ip(request)
    # Hard cap on login calls per IP, whatever email is tried.
    await rate_limit(db, f"login-ip:{real_ip}", 30, LOCKOUT_MIN * 60)
    identifiers = [(f"{real_ip}:{email}", MAX_ATTEMPTS), (f"email:{email}", MAX_ATTEMPTS_PER_EMAIL)]
    identifier = identifiers[0][0]

    now = datetime.now(timezone.utc)
    attempts = {}
    for ident, limit in identifiers:
        a = await db.login_attempts.find_one({"identifier": ident})
        attempts[ident] = a
        if a and a.get("count", 0) >= limit and a.get("locked_until"):
            if now < datetime.fromisoformat(a["locked_until"]):
                raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")
            # lock expired: start counting again
            await db.login_attempts.delete_one({"identifier": ident})
            attempts[ident] = None

    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        for ident, limit in identifiers:
            a = attempts[ident]
            count = (a.get("count", 0) if a else 0) + 1
            lock_until = (now + timedelta(minutes=LOCKOUT_MIN)).isoformat() if count >= limit else None
            await db.login_attempts.update_one(
                {"identifier": ident},
                {"$set": {"count": count, "locked_until": lock_until, "updated_at": now_iso()}},
                upsert=True,
            )
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.get("active", True):
        raise HTTPException(status_code=403, detail="Account disabled")

    for ident, _ in identifiers:
        await db.login_attempts.delete_one({"identifier": ident})
    if body.password in KNOWN_PUBLIC_PASSWORDS and not user.get("must_change_password"):
        await db.users.update_one({"id": user["id"]}, {"$set": {"must_change_password": True}})
        user["must_change_password"] = True
    tv = int(user.get("token_version", 0))
    at = create_access_token(user["id"], user["email"], user["role"], tv)
    rt = create_refresh_token(user["id"], tv)
    set_auth_cookies(response, at, rt)
    await audit(db, user, "login", "user", user["id"])
    return {"user": _sanitize(user), "token": at}


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


@router.post("/change-password")
async def change_password(body: ChangePasswordIn, request: Request, response: Response,
                          user: dict = Depends(get_current_user)):
    db = request.app.state.db
    await rate_limit(db, f"pwchange:{user['id']}", 10, 15 * 60)
    full = await db.users.find_one({"id": user["id"]})
    if not full or not verify_password(body.current_password, full["password_hash"]):
        raise HTTPException(400, "Current password is wrong")
    if body.new_password in KNOWN_PUBLIC_PASSWORDS or body.new_password == body.current_password:
        raise HTTPException(400, "Choose a new password you haven't used before")
    await db.users.update_one({"id": user["id"]}, {
        "$set": {"password_hash": hash_password(body.new_password), "updated_at": now_iso()},
        "$unset": {"must_change_password": ""},
        "$inc": {"token_version": 1}})          # signs out every other device
    tv = int(full.get("token_version", 0)) + 1
    at = create_access_token(full["id"], full["email"], full["role"], tv)
    rt = create_refresh_token(full["id"], tv)
    set_auth_cookies(response, at, rt)           # this device stays signed in
    await audit(db, user, "user.password_change", "user", user["id"])
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    return {"ok": True, "token": at, "user": _sanitize(fresh)}


@router.post("/logout")
async def logout(response: Response, request: Request, user: dict = Depends(get_current_user)):
    db = request.app.state.db
    clear_auth_cookies(response)
    await audit(db, user, "logout", "user", user["id"])
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return user


@router.post("/verify-admin")
async def verify_admin(body: LoginIn, request: Request,
                       actor: dict = Depends(get_current_user)):
    """Owner-password verification used by the POS below-COGS override.
    Returns the owner's id/name on success so the caller can attach it to the sale."""
    db = request.app.state.db
    # Without this, any logged-in cashier could guess the owner password endlessly.
    await rate_limit(db, f"verify-admin:{actor['id']}", 5, 15 * 60)
    email = body.email.lower().strip()
    admin = await db.users.find_one({"email": email})
    if (not admin
        or admin.get("role") != "owner"
        or not admin.get("active", True)
        or not verify_password(body.password, admin["password_hash"])):
        raise HTTPException(status_code=401, detail="Admin credentials rejected")
    await audit(db, actor, "admin.override_verify", "user", admin["id"],
                {"requested_by": actor.get("email")})
    return {"ok": True, "admin_id": admin["id"], "admin_email": admin["email"], "admin_name": admin["name"]}


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")
    db = request.app.state.db
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not user or not user.get("active", True):
        raise HTTPException(status_code=401, detail="User not found or inactive")
    if int(payload.get("tv", 0)) != int(user.get("token_version", 0)):
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    at = create_access_token(user["id"], user["email"], user["role"], int(user.get("token_version", 0)))
    response.set_cookie(
        key="access_token", value=at, httponly=True, secure=True, samesite=COOKIE_SAMESITE,
        max_age=ACCESS_TTL_MIN * 60, path="/",
    )
    return {"ok": True}
