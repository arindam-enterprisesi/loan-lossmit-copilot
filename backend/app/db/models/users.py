"""Seeded demo users (one per role). Cognito replaces this later with the same claims."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import Role
from app.db.models._common import created_at_column, enum_type, uuid_pk


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(sa.String(64), unique=True)
    name: Mapped[str] = mapped_column(sa.String(200))
    role: Mapped[Role] = mapped_column(enum_type(Role, "role"))
    password_hash: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = created_at_column()
