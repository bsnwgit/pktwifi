"""
/api/users/* — user management (admin) + self-service password change.
"""
from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import CurrentUser, AdminUser
from app.auth.local import hash_password, verify_password

router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    email: str
    password: str
    role: str = "viewer"


class UpdateUserRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def _user_out(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "auth_provider": row["auth_provider"],
        "created_at": row["created_at"],
        "last_login": row["last_login"],
        "has_password": bool(row["hashed_password"]) if "hashed_password" in row.keys() else True,
    }


@router.get("/me")
async def get_me(user: CurrentUser, db: aiosqlite.Connection = Depends(get_db)):
    if user.get("_via_suite"):
        return {
            "id": 0, "username": user["username"], "email": user["email"], "role": user["role"],
            "is_active": True, "auth_provider": "suite", "created_at": user["created_at"],
            "last_login": None, "has_password": False,
        }
    async with db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)) as cur:
        row = await cur.fetchone()
    return _user_out(row)


@router.get("")
async def list_users(user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute(
        "SELECT id, username, email, role, is_active, auth_provider, created_at, last_login "
        "FROM users ORDER BY username"
    ) as cur:
        rows = await cur.fetchall()
    return [_user_out(r) for r in rows]


@router.post("", status_code=201)
async def create_user(body: CreateUserRequest, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    if body.role not in ("admin", "analyst", "viewer"):
        raise HTTPException(status_code=400, detail="Invalid role")
    try:
        cur = await db.execute(
            "INSERT INTO users (username, email, hashed_password, role) VALUES (?, ?, ?, ?) RETURNING *",
            (body.username, body.email, hash_password(body.password), body.role),
        )
        row = await cur.fetchone()
        await db.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="Username or email already exists")
    return _user_out(row)


@router.patch("/{user_id}")
async def update_user(user_id: int, body: UpdateUserRequest, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cur:
        existing = await cur.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="User not found")

    role = body.role if body.role is not None else existing["role"]
    is_active = int(body.is_active) if body.is_active is not None else existing["is_active"]
    if role not in ("admin", "analyst", "viewer"):
        raise HTTPException(status_code=400, detail="Invalid role")

    await db.execute("UPDATE users SET role = ?, is_active = ? WHERE id = ?", (role, is_active, user_id))
    await db.commit()
    async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    return _user_out(row)


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: int, user: AdminUser, db: aiosqlite.Connection = Depends(get_db)):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    await db.commit()


@router.post("/me/change-password")
async def change_my_password(body: ChangePasswordRequest, user: CurrentUser, db: aiosqlite.Connection = Depends(get_db)):
    if user.get("_via_suite"):
        raise HTTPException(status_code=400, detail="Password managed by pktHub for suite-authenticated sessions")
    async with db.execute("SELECT hashed_password FROM users WHERE id = ?", (user["id"],)) as cur:
        row = await cur.fetchone()
    if not row or not row["hashed_password"] or not verify_password(body.current_password, row["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    await db.execute(
        "UPDATE users SET hashed_password = ? WHERE id = ?",
        (hash_password(body.new_password), user["id"]),
    )
    await db.commit()
    return {"status": "ok"}
