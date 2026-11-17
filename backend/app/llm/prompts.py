"""Versioned prompt templates in backend/app/prompts/<name>@<version>.md.

File format::

    ---
    description: one line on what the prompt does
    ---
    ## system
    ...system text...
    ## user
    ...user text with {{variable}} placeholders...

Rendering is strict: a missing or unused variable is an error, so a typo in a
caller or a template never silently sends a half-filled prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

PROMPT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(\.[a-z0-9-]+)*@[1-9][0-9]*$")
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_SECTION_RE = re.compile(r"^##\s+(system|user)\s*$", re.MULTILINE)


class PromptError(Exception):
    """A prompt id, file or variable set is invalid."""


@dataclass(frozen=True)
class RenderedPrompt:
    prompt_id: str
    system: str
    user: str


@dataclass(frozen=True)
class PromptTemplate:
    prompt_id: str
    system: str
    user: str

    @property
    def variables(self) -> set[str]:
        return set(_PLACEHOLDER_RE.findall(self.system)) | set(_PLACEHOLDER_RE.findall(self.user))

    def render(self, variables: dict[str, Any]) -> RenderedPrompt:
        expected = self.variables
        missing = expected - variables.keys()
        unused = variables.keys() - expected
        if missing:
            raise PromptError(f"{self.prompt_id}: missing variables {sorted(missing)}")
        if unused:
            raise PromptError(f"{self.prompt_id}: unused variables {sorted(unused)}")

        def substitute(text: str) -> str:
            return _PLACEHOLDER_RE.sub(lambda m: str(variables[m.group(1)]), text)

        return RenderedPrompt(self.prompt_id, substitute(self.system), substitute(self.user))


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end == -1:
            raise PromptError("unterminated frontmatter")
        return text[end + 4 :]
    return text


def parse_prompt(prompt_id: str, text: str) -> PromptTemplate:
    body = _strip_frontmatter(text.replace("\r\n", "\n"))
    parts = _SECTION_RE.split(body)
    # parts = [preamble, name1, text1, name2, text2, ...]
    sections: dict[str, str] = {}
    for name, content in zip(parts[1::2], parts[2::2], strict=True):
        if name in sections:
            raise PromptError(f"{prompt_id}: duplicate '## {name}' section")
        sections[name] = content.strip()
    if "user" not in sections:
        raise PromptError(f"{prompt_id}: a '## user' section is required")
    return PromptTemplate(prompt_id, sections.get("system", ""), sections["user"])


def load_prompt(prompt_id: str, prompts_dir: Path | None = None) -> PromptTemplate:
    if not PROMPT_ID_RE.fullmatch(prompt_id):
        raise PromptError(f"invalid prompt id {prompt_id!r}; expected e.g. 'classify@1'")
    path = (prompts_dir or PROMPTS_DIR) / f"{prompt_id}.md"
    if not path.is_file():
        raise PromptError(f"prompt file not found: {path.name}")
    return parse_prompt(prompt_id, path.read_text(encoding="utf-8"))
