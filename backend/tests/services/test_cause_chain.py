"""What the worker logs when a model call fails: class names only, never a message."""

from __future__ import annotations

import pytest

from app.llm.gateway import GatewayError
from app.services.pipeline import cause_chain


class ProviderCallError(Exception):
    pass


def test_the_chain_names_each_cause_from_the_top() -> None:
    try:
        try:
            raise PermissionError("User: arn:aws:iam::123:user/someone is not authorized")
        except PermissionError as inner:
            raise ProviderCallError("bedrock: HTTP 403") from inner
    except ProviderCallError as middle:
        try:
            raise GatewayError("classify", "classify@1", "provider call failed") from middle
        except GatewayError as outer:
            chain = cause_chain(outer)
    assert chain == "GatewayError <- ProviderCallError <- PermissionError"


def test_messages_never_reach_the_log() -> None:
    secret = "Gross pay 3,070.50 Daniel Reyes ssn 4821"  # stands for quoted document text
    try:
        raise GatewayError("classify", "classify@1", secret)
    except GatewayError as exc:
        assert secret not in cause_chain(exc)


def test_a_cycle_or_a_very_long_chain_ends() -> None:
    first, second = ValueError("a"), ValueError("b")
    first.__cause__, second.__cause__ = second, first
    assert cause_chain(first) == "ValueError <- ValueError"

    error: BaseException = KeyError("0")
    for n in range(20):
        wrapper = RuntimeError(str(n))
        wrapper.__cause__ = error
        error = wrapper
    assert len(cause_chain(error).split(" <- ")) == 6


@pytest.mark.parametrize("exc", [ValueError("x"), GatewayError("classify", "classify@1", "y")])
def test_a_single_error_is_just_its_name(exc: BaseException) -> None:
    assert cause_chain(exc) == type(exc).__name__
