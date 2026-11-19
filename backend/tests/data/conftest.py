# ruff: noqa: I001
# helpers must be imported first: it puts data/ on sys.path so `synthetic` can be imported.
from __future__ import annotations

import pytest

from tests.data import helpers  # noqa: F401
from synthetic.schema import Scenario, load_scenario

# `Rendered` and the session-wide `rendered` fixture live in tests/conftest.py (the database tests
# upload the same files); the re-export keeps `from tests.data.conftest import Rendered` working.
from tests.conftest import Rendered  # noqa: F401


@pytest.fixture(scope="session")
def daniel() -> Scenario:
    return load_scenario("daniel_reyes")


@pytest.fixture(scope="session")
def angela() -> Scenario:
    return load_scenario("angela_whitfield")
