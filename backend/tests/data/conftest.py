# ruff: noqa: I001
# helpers must be imported first: it puts data/ on sys.path so `synthetic` can be imported.
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.data import helpers  # noqa: F401
from synthetic.generate import generate
from synthetic.schema import Scenario, load_scenario


@dataclass(frozen=True)
class Rendered:
    out: Path
    manifest: dict[str, Any]

    def path(self, relative: str) -> Path:
        return self.out / relative

    def entry(self, relative: str) -> dict[str, Any]:
        return next(f for f in self.manifest["files"] if f["path"] == relative)


@pytest.fixture(scope="session")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> Rendered:
    """Every document and the broken set, rendered once for the whole test session."""
    out = tmp_path_factory.mktemp("synthetic")
    return Rendered(out, generate(out))


@pytest.fixture(scope="session")
def daniel() -> Scenario:
    return load_scenario("daniel_reyes")


@pytest.fixture(scope="session")
def angela() -> Scenario:
    return load_scenario("angela_whitfield")
