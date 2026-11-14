"""User management (owner-only)."""
from fastapi import APIRouter, Request, HTTPException, Depends
from models import UserCreate, UserUpdate, ROLE_OWNER, ALL_ROLES, gen_id, now_iso
from auth import hash_password, require_roles, audit

router = APIRouter(prefix="/users", tags=["users"])


def _sanitize(u: dict) -> dict:
    return {k: v for k, v in u.items() if k not in {"_id", "password_hash"}}


@router.get("")
async def list_users(request: Request, user: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    docs = await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(1000)
    return docs


@router.post("")
async def create_user(body: UserCreate, request: Request, actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    if body.role not in ALL_ROLES:
        raise HTTPException(400, "Invalid role")
    email = body.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(409, "Email already exists")
    doc = {
        "id": gen_id(),
        "email": email,
        "password_hash": hash_password(body.password),
        "name": body.name, "role": body.role, "active": body.active,
        "created_at": now_iso(),
    }
    await db.users.insert_one(doc)
    await audit(db, actor, "user.create", "user", doc["id"], {"email": email, "role": body.role})
    return _sanitize(doc)


@router.patch("/{user_id}")
async def update_user(user_id: str, body: UserUpdate, request: Request,
                      actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "role" in updates and updates["role"] not in ALL_ROLES:
        raise HTTPException(400, "Invalid role")
    if "password" in updates:
        updates["password_hash"] = hash_password(updates.pop("password"))
    if not updates:
        raise HTTPException(400, "Nothing to update")
    updates["updated_at"] = now_iso()
    # Changing password, role or active status logs the user out everywhere.
    bump = {"token_version": 1} if ({"password_hash", "role", "active"} & updates.keys()) else None
    res = await db.users.update_one({"id": user_id}, {"$set": updates, **({"$inc": bump} if bump else {})})
    if res.matched_count == 0:
        raise HTTPException(404, "User not found")
    await audit(db, actor, "user.update", "user", user_id, {k: v for k, v in updates.items() if k != "password_hash"})
    doc = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    return doc


@router.delete("/{user_id}")
async def delete_user(user_id: str, request: Request, actor: dict = Depends(require_roles(ROLE_OWNER))):
    db = request.app.state.db
    if user_id == actor["id"]:
        raise HTTPException(400, "Cannot delete your own account")
    res = await db.users.delete_one({"id": user_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "User not found")
    await audit(db, actor, "user.delete", "user", user_id)
    return {"ok": True}
