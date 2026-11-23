"""Which version of each settings file a run used (``config_versions``, docs/database-schema.md).

A run records the version of every file it read, with a hash of the file's bytes, so that "which
settings produced this figure" is answerable later even if a file was edited without its version
being bumped. Each distinct file content is one row, however many runs used it.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ConfigKind, ConfigLabel
from app.db.models import ConfigVersion
from app.services.analysis_config import ConfigUse


async def record_config_versions(session: AsyncSession, uses: list[ConfigUse]) -> None:
    """Make sure each used version has its row, and that it is the active one for its file."""
    for use in uses:
        kind = ConfigKind(use.kind)
        row = await session.scalar(
            sa.select(ConfigVersion).where(
                ConfigVersion.kind == kind,
                ConfigVersion.name == use.name,
                ConfigVersion.version == use.version,
                ConfigVersion.content_hash == use.content_hash,
            )
        )
        if row is not None and row.active:
            continue
        await session.execute(
            sa.update(ConfigVersion)
            .where(ConfigVersion.kind == kind, ConfigVersion.name == use.name)
            .values(active=False)
        )
        if row is None:
            session.add(
                ConfigVersion(
                    kind=kind,
                    name=use.name,
                    version=use.version,
                    label=ConfigLabel(use.label),
                    source=use.source,
                    content_hash=use.content_hash,
                    active=True,
                )
            )
        else:
            row.active = True
        await session.flush()
