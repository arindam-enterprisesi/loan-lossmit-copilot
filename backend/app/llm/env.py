"""Provider credentials from the repo's ``.env``, for every process that calls a model.

Inside docker compose the variables are already in the environment. A script run on the host
(``python -m app.db.reset_demo``, the smoke CLI, the evaluation) only has them if something loads
``.env``: pydantic-settings reads it into ``Settings`` but not into ``os.environ``, which is where
the provider SDKs look. Values already in the environment win.

A blank ``AWS_*`` value (``AWS_PROFILE=`` straight from ``.env.example``) means "not set": boto
would otherwise look for a profile named "" and fail before any request.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_loaded = False


def drop_blank_aws_env() -> None:
    for name in [n for n, v in os.environ.items() if n.startswith("AWS_") and not v.strip()]:
        del os.environ[name]


def load_provider_env(path: Path | None = None, *, force: bool = False) -> None:
    """Load ``.env`` into ``os.environ`` once (never overriding), then drop blank AWS settings."""
    global _loaded
    if _loaded and not force:
        return
    env_file = path or REPO_ROOT / ".env"
    if env_file.is_file():
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)
    drop_blank_aws_env()
    _loaded = True
