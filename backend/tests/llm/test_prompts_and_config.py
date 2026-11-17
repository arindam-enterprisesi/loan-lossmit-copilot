from pathlib import Path

import pytest

from app.llm.config import load_llm_config
from app.llm.prompts import PromptError, load_prompt, parse_prompt


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


def test_repo_prompts_and_config_load() -> None:
    assert load_prompt("smoke@1").variables == {"word"}
    config = load_llm_config()
    assert config.label in {"illustrative", "authoritative"}
    classify = config.for_task("classify")
    assert classify.provider == "anthropic"
    assert classify.options["effort"] == "low"
    assert config.for_task("not-configured") == config.defaults
