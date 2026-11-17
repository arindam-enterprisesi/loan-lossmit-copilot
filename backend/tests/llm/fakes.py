from dataclasses import dataclass, field

from app.llm.config import LLMConfig, ProviderDefaults
from app.llm.types import AdapterRequest, AdapterResponse


@dataclass
class FakeAdapter:
    """Returns queued responses in order and records every request."""

    responses: list[AdapterResponse | Exception]
    name: str = "fake"
    requests: list[AdapterRequest] = field(default_factory=list)

    async def complete(self, request: AdapterRequest) -> AdapterResponse:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def fake_config(**tasks: dict[str, object]) -> LLMConfig:
    return LLMConfig.model_validate(
        {
            "version": "test",
            "label": "illustrative",
            "default_provider": "fake",
            "providers": {
                "fake": ProviderDefaults(model="fake-model", options={"effort": "low"}),
                "other": ProviderDefaults(model="other-default", temperature=None),
            },
            "tasks": tasks,
        }
    )
