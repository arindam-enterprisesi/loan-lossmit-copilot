"""CLAUDE.md rule 7: only backend/app/llm may import a model provider SDK."""

import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2] / "app"
LLM_DIR = APP_DIR / "llm"

PROVIDER_IMPORT = re.compile(
    r"^\s*(from|import)\s+(anthropic|openai|google\.genai|google\.generativeai|"
    r"langchain_[a-z_]+|mistralai|cohere)\b",
    re.MULTILINE,
)


def test_no_provider_sdk_outside_llm_package() -> None:
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if LLM_DIR not in path.parents and PROVIDER_IMPORT.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"provider SDK imported outside app/llm: {offenders}"
