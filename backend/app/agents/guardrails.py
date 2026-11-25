"""The final guardrails, in code (Feature Design 6.5 and 8.5).

Run on every draft before the Critic reads it and again on the final draft:

* every number in the text must be one in the dossier (or a cited passage): "unverified figure";
* no decision wording (rule 3), including the configured extra words;
* every evidence ref, finding ID and passage ID must resolve.

``strip`` then removes whatever still fails from the final draft, item by item (or sentence by
sentence in a paragraph), and the removals are stored with the report.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from decimal import Decimal
from typing import Any

from app.llm.checks import check_figures, decision_words

Issue = dict[str, str]
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def iter_texts(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Every string in a draft with its path: ``conditions[2].text``."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in ("evidence_refs", "finding_ids", "priority"):
                continue
            yield from iter_texts(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from iter_texts(item, f"{path}[{i}]")


def blocked_words(text: str, extra: Iterable[str]) -> list[str]:
    found = decision_words(text)
    lowered = text.lower()
    found += [w for w in extra if re.search(rf"\b{re.escape(w.lower())}\b", lowered)]
    return list(dict.fromkeys(found))


def check_draft(
    draft: dict[str, Any],
    *,
    allowed: set[Decimal],
    extra_words: Iterable[str],
    known_refs: set[str] | None = None,
    known_findings: set[str] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    extra = list(extra_words)
    for path, text in iter_texts(draft):
        unverified = check_figures(text, allowed)
        if unverified:
            issues.append(
                {
                    "where": path,
                    "kind": "unverified figure",
                    "problem": "figures not in the evidence: " + ", ".join(unverified),
                }
            )
        words = blocked_words(text, extra)
        if words:
            issues.append(
                {"where": path, "kind": "decision wording", "problem": "uses " + ", ".join(words)}
            )
    for i, conflict in enumerate(draft.get("conflicts") or []):
        unknown = [
            r
            for r in conflict.get("evidence_refs", [])
            if known_refs is not None and r not in known_refs
        ]
        if unknown or not conflict.get("evidence_refs"):
            issues.append(
                {
                    "where": f"conflicts[{i}]",
                    "kind": "unresolved evidence",
                    "problem": "evidence refs missing or unknown: "
                    + ", ".join(unknown or ["none"]),
                }
            )
    for i, condition in enumerate(draft.get("conditions") or []):
        ids = condition.get("finding_ids", [])
        unknown = [f for f in ids if known_findings is not None and f not in known_findings]
        if unknown or not ids:
            issues.append(
                {
                    "where": f"conditions[{i}]",
                    "kind": "unresolved evidence",
                    "problem": "finding IDs missing or unknown: " + ", ".join(unknown or ["none"]),
                }
            )
    return issues


def _top(path: str) -> tuple[str, int | None]:
    m = re.match(r"^(\w+)(?:\[(\d+)\])?", path)
    assert m is not None
    return m.group(1), int(m.group(2)) if m.group(2) is not None else None


def strip(
    draft: dict[str, Any], issues: list[Issue], recheck: Callable[[str], bool]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Remove failing items; in a paragraph, only the failing sentences. ``recheck(text)`` says
    whether a sentence still fails."""
    removed: list[dict[str, str]] = []
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in draft.items()}
    drop: dict[str, set[int]] = {}
    for issue in issues:
        section, index = _top(issue["where"])
        if index is not None:
            drop.setdefault(section, set()).add(index)
        elif isinstance(paragraph := out.get(section), str):
            kept = []
            for sentence in _SENTENCE.split(paragraph):
                if recheck(sentence):
                    removed.append({"where": section, "text": sentence, "reason": issue["kind"]})
                else:
                    kept.append(sentence)
            out[section] = " ".join(kept)
    for section, indexes in drop.items():
        items = out.get(section) or []
        for i in sorted(indexes):
            if i < len(items):
                reason = next(x["kind"] for x in issues if _top(x["where"]) == (section, i))
                text = (
                    items[i]
                    if isinstance(items[i], str)
                    else items[i].get("text") or items[i].get("title", "")
                )
                removed.append({"where": f"{section}[{i}]", "text": str(text), "reason": reason})
        out[section] = [item for i, item in enumerate(items) if i not in indexes]
    return out, removed
