"""Login request and response, as in contracts/openapi.yaml."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.db.enums import Role


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginUser(BaseModel):
    id: str
    name: str
    role: Role


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: LoginUser
