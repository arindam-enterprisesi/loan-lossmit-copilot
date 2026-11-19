"""Provider-neutral types shared by the gateway and every provider adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class AdapterRequest:
    """One structured-output call, already rendered from a prompt template."""

    model: str
    system: str
    messages: list[Message]
    output_model: type[BaseModel]
    max_tokens: int
    temperature: float | None  # None: do not send a temperature
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterResponse:
    """What a provider returned. The gateway, not the adapter, validates ``text``."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    refused: bool = False
    truncated: bool = False


class ProviderCallError(Exception):
    """The provider call itself failed (network, auth, rate limit, server error)."""

    def __init__(self, provider: str, reason: str, *, retryable: bool = False) -> None:
        super().__init__(f"{provider}: {reason}")
        self.provider = provider
        self.reason = reason
        self.retryable = retryable


@runtime_checkable
class ProviderAdapter(Protocol):
    """One implementation per model provider. Only ``app.llm.adapters`` implements it."""

    name: str

    async def complete(self, request: AdapterRequest) -> AdapterResponse: ...
