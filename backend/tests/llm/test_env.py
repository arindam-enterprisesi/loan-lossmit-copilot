"""Host-run scripts read provider keys from .env; blank AWS settings mean "not set"."""

from pathlib import Path

import pytest
from botocore.exceptions import NoCredentialsError, ProfileNotFound

from app.llm import env
from app.llm.adapters.anthropic import BedrockClaudeAdapter
from app.llm.types import AdapterRequest, Message, ProviderCallError
from app.prompts.schemas.fields import Schema


def test_env_file_is_loaded_without_overriding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / ".env"
    file.write_text("COPILOT_TEST_KEY=from-file\nCOPILOT_TEST_KEEP=from-file\nAWS_PROFILE=\n")
    monkeypatch.delenv("COPILOT_TEST_KEY", raising=False)
    monkeypatch.setenv("COPILOT_TEST_KEEP", "from-shell")
    monkeypatch.delenv("AWS_PROFILE", raising=False)

    env.load_provider_env(file, force=True)

    import os

    assert os.environ["COPILOT_TEST_KEY"] == "from-file"
    assert os.environ["COPILOT_TEST_KEEP"] == "from-shell"
    assert "AWS_PROFILE" not in os.environ
    monkeypatch.delenv("COPILOT_TEST_KEY")


def test_blank_aws_values_are_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_PROFILE", "  ")
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    env.drop_blank_aws_env()
    import os

    assert "AWS_PROFILE" not in os.environ
    assert os.environ["AWS_REGION"] == "ap-south-1"


class _Out(Schema):
    ok: bool


class _Raising:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

        class _Messages:
            async def create(inner, **_: object) -> None:
                raise self.exc

        self.messages = _Messages()


@pytest.mark.parametrize(
    "exc", [ProfileNotFound(profile=""), NoCredentialsError()], ids=["profile", "credentials"]
)
async def test_botocore_errors_become_provider_errors(exc: Exception) -> None:
    adapter = BedrockClaudeAdapter(client=_Raising(exc))
    request = AdapterRequest(
        model="m",
        system=None,
        messages=[Message("user", "hi")],
        output_model=_Out,
        max_tokens=10,
        temperature=None,
        options={},
    )
    with pytest.raises(ProviderCallError) as raised:
        await adapter.complete(request)
    assert raised.value.reason == f"AWS: {type(exc).__name__}"
