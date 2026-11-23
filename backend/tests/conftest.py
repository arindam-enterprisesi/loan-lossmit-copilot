"""Fixtures shared by every test folder."""

from __future__ import annotations

import os

# No test may call a real model. Tests that want the real classify task pass their own gateway.
os.environ.setdefault("PIPELINE_LLM", "fake")
# Nor does any test need the tesseract program: OCR tests build the adapter themselves.
os.environ.setdefault("OCR_ENGINE", "none")

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


@dataclass(frozen=True)
class Rendered:
    out: Path
    manifest: dict[str, Any]

    def path(self, relative: str) -> Path:
        return self.out / relative

    def entry(self, relative: str) -> dict[str, Any]:
        return next(f for f in self.manifest["files"] if f["path"] == relative)

    def read(self, relative: str) -> bytes:
        return self.path(relative).read_bytes()


@pytest.fixture(scope="session")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> Rendered:
    """Every document and the broken set, rendered once for the whole test session."""
    # helpers puts data/ on sys.path so the generator (outside the backend package) imports.
    from tests.data import helpers  # noqa: F401, I001

    from synthetic.generate import generate

    out = tmp_path_factory.mktemp("synthetic")
    return Rendered(out, generate(out))
