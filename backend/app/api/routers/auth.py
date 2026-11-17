"""POST /auth/login: seeded demo users now, Amazon Cognito later with the same claims."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.schemas.auth import LoginRequest, LoginResponse, LoginUser
from app.db.models import User
from app.db.session import get_session
from app.services.auth_config import get_auth_config
from app.services.security import (
    CurrentUser,
    create_access_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@lru_cache
def _dummy_hash() -> str:
    return hash_password("not-a-real-password")


@router.post("/login", response_model=LoginResponse, operation_id="login")
async def login(
    body: LoginRequest, session: Annotated[AsyncSession, Depends(get_session)]
) -> LoginResponse:
    user = (
        await session.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    # Always run a hash check, so an unknown username takes as long as a wrong password
    # and the two cannot be told apart. The hash is slow, so keep it off the event loop.
    stored = user.password_hash if user is not None else _dummy_hash()
    password_ok = await asyncio.to_thread(verify_password, body.password, stored)
    if user is None or not password_ok:
        raise ApiError(401, "invalid_credentials", "Incorrect username or password")

    current = CurrentUser(id=str(user.id), name=user.name, role=user.role)
    return LoginResponse(
        access_token=create_access_token(current),
        expires_in=get_auth_config().access_token_minutes * 60,
        user=LoginUser(id=current.id, name=current.name, role=current.role),
    )
