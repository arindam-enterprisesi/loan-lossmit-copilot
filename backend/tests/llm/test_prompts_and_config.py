from pathlib import Path

import pytest

from app.llm.config import ConfigError, load_llm_config
from app.llm.prompts import PromptError, load_prompt, parse_prompt

from .fakes import fake_config


def test_render_is_strict() -> None:
    template = parse_prompt("t@1", "## system\nS {{a}}\n## user\nU {{ b }}")
    rendered = template.render({"a": 1, "b": "two"})
    assert (rendered.system, rendered.user) == ("S 1", "U two")
    with pytest.raises(PromptError, match="unused"):
        template.render({"a": 1, "b": 2, "c": 3})


def test_user_section_required() -> None:
    with pytest.raises(PromptError, match="user"):
        parse_prompt("t@1", "## system\nonly system")


@pytest.mark.parametrize("bad", ["classify", "classify@0", "Classify@1", "../x@1", "a/b@1"])
def test_prompt_id_must_be_versioned_and_safe(bad: str, tmp_path: Path) -> None:
    with pytest.raises(PromptError):
        load_prompt(bad, tmp_path)


def test_task_resolution_order() -> None:
    config = fake_config(
        pinned={"model": "pinned-model", "max_tokens": 50, "temperature": 0.5},
        elsewhere={"provider": "other", "options": {"effort": "high"}},
    )
    # Unknown task: default provider and its defaults.
    plain = config.for_task("unknown")
    assert (plain.provider, plain.model, plain.temperature) == ("fake", "fake-model", 0.0)
    assert plain.max_tokens == 16000
    assert plain.options == {"effort": "low"}

    pinned = config.for_task("pinned")
    assert (pinned.model, pinned.max_tokens, pinned.temperature) == ("pinned-model", 50, 0.5)

    # A task's model applies only on its own provider.
    switched = config.for_task("pinned", provider="other")
    assert (switched.provider, switched.model) == ("other", "other-default")

    elsewhere = config.for_task("elsewhere")
    assert (elsewhere.provider, elsewhere.model, elsewhere.temperature) == (
        "other",
        "other-default",
        None,
    )
    assert elsewhere.options == {"effort": "high"}

    with pytest.raises(ConfigError):
        config.for_task("unknown", provider="nope")


def test_repo_prompts_and_config_load() -> None:
    assert load_prompt("smoke@1").variables == {"word"}
    assert load_prompt("classify@1").variables == {"type_descriptions", "numbered_lines"}
    config = load_llm_config()
    assert config.label in {"illustrative", "authoritative"}
    assert set(config.providers) == {"anthropic", "bedrock", "gemini", "openai"}
    for provider in config.providers:
        config.for_task("classify", provider=provider)  # every provider resolves
    classify = config.for_task("classify")
    assert classify.provider == "anthropic"
    assert classify.options["effort"] == "low"
    assert config.embeddings is not None
