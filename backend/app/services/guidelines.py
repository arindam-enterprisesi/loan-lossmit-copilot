"""Guideline sources and passages, read-only (Feature 5, read side).

Every finding and every waterfall condition cites a passage ID (rule 2), and the screen opens the
passage from it. Arindam owns the guideline index (the embeddings, the loader, search); until its
tables exist this module reads a small seeded set of illustrative passages. It is behind a protocol
so his store replaces the seeded one without touching the endpoints. The seeded set is labelled in
every response, so it is never taken for an investor's real guide.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

SEED_FILE = Path(__file__).resolve().parents[1] / "db" / "demo" / "guideline_passages.json"
SEEDED_NOTICE = "Seeded sample: an invented illustrative passage, not an investor's real guide."


@dataclass(frozen=True)
class GuidelineSource:
    id: str
    title: str
    kind: str
    label: str
    passage_count: int


@dataclass(frozen=True)
class GuidelinePassage:
    id: str
    source_id: str
    source_title: str
    heading: str
    text: str
    label: str


class PassageStore(Protocol):
    def sources(self) -> list[GuidelineSource]: ...

    def passage(self, passage_id: str) -> GuidelinePassage | None: ...

    def passage_ids(self) -> list[str]: ...


class SeededPassageStore:
    """The illustrative passages in ``app/db/demo/guideline_passages.json``."""

    def __init__(self, path: Path = SEED_FILE) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self._sources = {s["id"]: s for s in data["sources"]}
        self._passages = {p["id"]: p for p in data["passages"]}
        if len(self._passages) != len(data["passages"]):
            raise ValueError("duplicate passage id in the seeded guideline passages")
        unknown = {p["source_id"] for p in self._passages.values()} - set(self._sources)
        if unknown:
            raise ValueError(f"passages name unknown sources: {sorted(unknown)}")

    def sources(self) -> list[GuidelineSource]:
        return [
            GuidelineSource(
                id=s["id"],
                title=s["title"],
                kind=s["kind"],
                label=s["label"],
                passage_count=sum(1 for p in self._passages.values() if p["source_id"] == s["id"]),
            )
            for s in self._sources.values()
        ]

    def passage(self, passage_id: str) -> GuidelinePassage | None:
        found = self._passages.get(passage_id)
        if found is None:
            return None
        source = self._sources[found["source_id"]]
        return GuidelinePassage(
            id=found["id"],
            source_id=source["id"],
            source_title=source["title"],
            heading=found["heading"],
            text=found["text"],
            label=source["label"],
        )

    def passage_ids(self) -> list[str]:
        return list(self._passages)


@lru_cache
def get_passage_store() -> PassageStore:
    """FastAPI dependency: the guideline index (``app.rag``), which also holds the seeded
    passages under the same IDs. Tests override it."""
    from app.rag.store import get_rag_store

    return get_rag_store()
