"""The guideline index: every loaded passage, searchable, behind the ``PassageStore`` protocol.

Retrieval (Feature Design 5.4 steps 2 to 4) runs in code:

* a question that names a section ("B3-3.1-01", "5303.1", "1024.41(b)") gets that section first;
* the rest is BM25 over each passage's heading and text;
* a passage whose matched words carry less than ``min_coverage`` of the question's term weight is
  dropped before the model sees anything. With nothing left, the answer is "no supporting passage
  found" and no model is called.

The scores are search relevance, not money or a ratio about a borrower, so they are floats.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.rag.config import RagConfig, get_rag_config
from app.rag.sources import SOURCE_SETS, Passage, Source, load_all
from app.services.guidelines import GuidelinePassage, GuidelineSource

STOPWORDS = frozenset(
    """
    a about above after all also an and any are as at be been before being both but by can
    could did do does doing for from had has have having how i if in into is it its may me
    might more most must my no nor not of on or our out over own same shall should so some such
    than that the their them then there these they this those through to too under until up
    very was we were what when where which while who whom why will with would you your please
    tell explain describe guidance guide rule rules say says said evaluate evaluated evaluation
    consider considered treat treated handle handled work works apply applies use used using
    need needs needed require requires required requirement requirements happen happens
    """.split()  # noqa: SIM905
)
_WORD = re.compile(r"[a-z0-9]+")
_SECTION_REF = re.compile(r"\b(?:[A-Z]\d+-\d+(?:\.\d+)*(?:-\d+)?|\d{4}\.\d+(?:\([a-z]\))?)", re.I)


def stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def terms(text: str) -> list[str]:
    """Search words: lower case, stemmed, without stop words or bare numbers."""
    return [stem(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS and not w.isdigit()]


@dataclass(frozen=True)
class Hit:
    passage: Passage
    source: Source
    score: float
    coverage: float
    direct: bool = False  # the question named this section


class RagStore:
    """Every loaded passage. Implements ``app.services.guidelines.PassageStore``."""

    def __init__(
        self,
        sources: dict[str, Source],
        passages: dict[str, Passage],
        config: RagConfig | None = None,
    ) -> None:
        self.config = config or get_rag_config()
        self._sources = sources
        self._passages = passages
        # The source title is indexed with each passage: "under Sample Investor A" or "Freddie Mac"
        # then finds that source's sections.
        self._docs = {
            pid: terms(f"{sources[p.source_id].title} {p.heading} {p.text}")
            for pid, p in passages.items()
        }
        self._lengths = {pid: len(words) for pid, words in self._docs.items()}
        self._avg = sum(self._lengths.values()) / max(len(self._lengths), 1)
        df: Counter[str] = Counter()
        for words in self._docs.values():
            df.update(set(words))
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self._unseen_idf = math.log(1 + (n + 0.5) / 0.5)
        self._tf = {pid: Counter(words) for pid, words in self._docs.items()}

    # --- the PassageStore protocol (read side, used by GET /guidelines/...) -----------------

    def sources(self) -> list[GuidelineSource]:
        return [
            GuidelineSource(
                id=s.id,
                title=s.title,
                kind=s.kind,
                label=s.label,
                passage_count=sum(1 for p in self._passages.values() if p.source_id == s.id),
            )
            for s in self._sources.values()
        ]

    def passage(self, passage_id: str) -> GuidelinePassage | None:
        found = self._passages.get(passage_id)
        if found is None:
            return None
        source = self._sources[found.source_id]
        return GuidelinePassage(
            id=found.id,
            source_id=source.id,
            source_title=source.title,
            heading=found.heading,
            text=found.text,
            label=source.label,
        )

    def passage_ids(self) -> list[str]:
        return list(self._passages)

    # --- more detail for the assistant --------------------------------------------------------

    def source(self, source_id: str) -> Source:
        return self._sources[source_id]

    def raw(self, passage_id: str) -> Passage | None:
        return self._passages.get(passage_id)

    def notice(self, passage_id: str) -> str | None:
        found = self._passages.get(passage_id)
        return self._sources[found.source_id].notice if found else None

    def source_info(self) -> list[Source]:
        return list(self._sources.values())

    # --- search -------------------------------------------------------------------------------

    def _allowed(self, source_set: str) -> set[str]:
        kinds = SOURCE_SETS[source_set]
        return {
            pid for pid, p in self._passages.items() if self._sources[p.source_id].kind in kinds
        }

    def named_sections(self, question: str, allowed: Iterable[str]) -> list[str]:
        """Passages the question names by section ("B3-3.1-01", "1024.41(b)")."""
        wanted = {m.group(0).lower() for m in _SECTION_REF.finditer(question)}
        found: list[str] = []
        for pid in allowed:
            p = self._passages[pid]
            names = {p.section.lower(), p.section.split(".")[0].lower()}
            if p.source_id == "reg-x-1024-41":
                names.add(f"1024.41({p.section.lower()})")
            if names & wanted:
                found.append(pid)
        return found

    def search(self, question: str, source_set: str = "all", k: int | None = None) -> list[Hit]:
        if source_set not in SOURCE_SETS:
            raise ValueError(f"unknown source set {source_set!r}")
        k = k or self.config.top_k
        allowed = self._allowed(source_set)
        query = list(dict.fromkeys(terms(question)))
        weights = {t: self._idf.get(t, self._unseen_idf) for t in query}
        # A word no loaded source uses ("jumbo") counts against every passage. A word that only
        # other source sets use ("bank statement" when asking Regulation X) does not.
        in_set = set().union(*(self._tf[pid].keys() for pid in allowed)) if allowed else set()
        total = sum(w for t, w in weights.items() if t in in_set or t not in self._idf)
        k1, b = float(self.config.bm25_k1), float(self.config.bm25_b)
        hits: list[Hit] = []
        for pid in allowed:
            tf = self._tf[pid]
            matched = [t for t in query if tf[t]]
            if not matched:
                continue
            score = 0.0
            for t in matched:
                f = tf[t]
                norm = 1 - b + b * self._lengths[pid] / self._avg
                score += weights[t] * f * (k1 + 1) / (f + k1 * norm)
            coverage = sum(weights[t] for t in matched) / total if total else 0.0
            p = self._passages[pid]
            hits.append(Hit(p, self._sources[p.source_id], score, coverage))
        kept = [h for h in hits if h.coverage >= float(self.config.min_coverage)]
        kept.sort(key=lambda h: (-h.score, h.passage.id))
        direct_ids = self.named_sections(question, allowed)
        direct = [
            Hit(self._passages[pid], self._sources[self._passages[pid].source_id], 0.0, 1.0, True)
            for pid in direct_ids
        ]
        seen = set(direct_ids)
        return (direct + [h for h in kept if h.passage.id not in seen])[:k]


def build_store(directory: Path | None = None, config: RagConfig | None = None) -> RagStore:
    sources, passages = load_all(directory)
    return RagStore(sources, passages, config)


@lru_cache
def get_rag_store() -> RagStore:
    return build_store()
