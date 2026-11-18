"""Column helpers shared by the models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

TIMESTAMPTZ = sa.DateTime(timezone=True)


def enum_type(enum_cls: type[StrEnum], name: str) -> sa.Enum:
    """VARCHAR + CHECK column type storing the enum's *values* (not its member names).

    ``name`` names the CHECK constraint, so it must be unique within a table.
    """
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [m.value for m in members],
    )


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        sa.Uuid,
        primary_key=True,
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
    )


def created_at_column(**kwargs: Any) -> Mapped[datetime]:
    return mapped_column(TIMESTAMPTZ, server_default=sa.func.now(), nullable=False, **kwargs)
