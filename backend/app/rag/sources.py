"""Guideline sources: read the source files into sources and passages (Feature Design 5.3, 5.5).

A source file is Markdown with a front-matter block and one ``## <section id> | <heading>`` block
per passage (``data/sources/README.md``). A passage keeps its source's structure: one section is
one passage, so a citation points at a section a person can find in the source. The Sample
Investor A passages that Feature 8's rules cite are read from the seeded JSON, with their IDs
unchanged; a Markdown source with the same ID replaces a seeded one.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SEEDED_PASSAGES = BACKEND_ROOT / "app" / "db" / "demo" / "guideline_passages.json"

_HEADING = re.compile(r"^## +(?P<section>[^|]+?) *\| *(?P<heading>.+?) *$", re.MULTILINE)
_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Which source kinds each source set answers from (Feature Design 5.2 step 1).
SOURCE_SETS: dict[str, frozenset[str]] = {
    "guidelines": frozenset({"agency_guide", "lender_overlay", "investor_guide"}),
    "regulation_x": frozenset({"regulation"}),
    "all": frozenset({"agency_guide", "lender_overlay", "investor_guide", "regulation"}),
}


class SourceError(ValueError):
    """A source file that cannot be loaded as written."""


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    kind: str
    label: str  # "illustrative" or "authoritative"
    version: str | None
    publisher: str | None
    url: str | None
    notice: str | None


@dataclass(frozen=True)
class Passage:
    id: str  # "<source id>.<section id>"
    source_id: str
    section: str
    heading: str
    text: str
    page: int | None = None


def sources_dir() -> Path:
    """``RAG_SOURCES_DIR``, else ``data/sources`` beside ``backend/``, else ``/data/sources``."""
    configured = os.environ.get("RAG_SOURCES_DIR")
    if configured:
        return Path(configured)
    local = BACKEND_ROOT.parent / "data" / "sources"
    return local if local.is_dir() else Path("/data/sources")


def parse_source(text: str, *, name: str = "<source>") -> tuple[Source, list[Passage]]:
    if not text.startswith("---"):
        raise SourceError(f"{name}: no front-matter block")
    try:
        _, front, body = text.split("---", 2)
    except ValueError as exc:
        raise SourceError(f"{name}: front-matter block is not closed") from exc
    meta: dict[str, Any] = yaml.safe_load(front) or {}
    for key in ("id", "title", "kind", "label"):
        if not meta.get(key):
            raise SourceError(f"{name}: front matter needs {key!r}")
    if not _ID.match(str(meta["id"])):
        raise SourceError(f"{name}: id {meta['id']!r} must be lower-case letters, digits and -")
    if meta["label"] not in ("illustrative", "authoritative"):
        raise SourceError(f"{name}: label must be illustrative or authoritative")
    if meta["kind"] not in SOURCE_SETS["all"]:
        raise SourceError(f"{name}: unknown kind {meta['kind']!r}")
    source = Source(
        id=str(meta["id"]),
        title=str(meta["title"]),
        kind=str(meta["kind"]),
        label=str(meta["label"]),
        version=_opt(meta.get("version")),
        publisher=_opt(meta.get("publisher")),
        url=_opt(meta.get("url")),
        notice=_opt(meta.get("notice")),
    )
    heads = list(_HEADING.finditer(body))
    if not heads:
        raise SourceError(f"{name}: no '## <section> | <heading>' passages")
    passages: list[Passage] = []
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        content = " ".join(body[head.end() : end].split())
        if not content:
            raise SourceError(f"{name}: section {head['section']} is empty")
        section = head["section"].strip()
        passages.append(
            Passage(
                id=f"{source.id}.{section}",
                source_id=source.id,
                section=section,
                heading=head["heading"].strip(),
                text=content,
            )
        )
    ids = [p.id for p in passages]
    if len(ids) != len(set(ids)):
        raise SourceError(f"{name}: duplicate section id")
    return source, passages


def _opt(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def load_seeded(path: Path = SEEDED_PASSAGES) -> tuple[list[Source], list[Passage]]:
    """The Sample Investor A passages (and anything else) seeded for Feature 8."""
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = [
        Source(
            id=s["id"],
            title=s["title"],
            kind=s["kind"],
            label=s["label"],
            version=s.get("version"),
            publisher=None,
            url=None,
            notice="Seeded sample: an invented illustrative passage, not an investor's real guide.",
        )
        for s in data["sources"]
    ]
    passages = [
        Passage(
            id=p["id"],
            source_id=p["source_id"],
            section=p["id"].removeprefix(p["source_id"] + "."),
            heading=p["heading"],
            text=p["text"],
        )
        for p in data["passages"]
    ]
    return sources, passages


def load_all(directory: Path | None = None) -> tuple[dict[str, Source], dict[str, Passage]]:
    """Every source: the Markdown files, then the seeded ones whose IDs no file uses."""
    directory = directory or sources_dir()
    sources: dict[str, Source] = {}
    passages: dict[str, Passage] = {}
    files = sorted(directory.glob("*.md")) if directory.is_dir() else []
    for file in files:
        if file.name.lower() == "readme.md":
            continue
        source, found = parse_source(file.read_text(encoding="utf-8"), name=file.name)
        if source.id in sources:
            raise SourceError(f"{file.name}: source id {source.id!r} is used twice")
        sources[source.id] = source
        passages.update({p.id: p for p in found})
    seeded_sources, seeded_passages = load_seeded()
    for source in seeded_sources:
        if source.id not in sources:
            sources[source.id] = source
    for passage in seeded_passages:
        if passage.source_id in sources and passage.id not in passages:
            owner = sources[passage.source_id]
            if owner.notice and owner.notice.startswith("Seeded sample"):
                passages[passage.id] = passage
    return sources, passages
