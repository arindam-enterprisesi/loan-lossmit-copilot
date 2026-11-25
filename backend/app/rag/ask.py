"""Ask the guideline assistant from the command line (reads ../.env for the provider keys).

uv run python -m app.rag.ask "How is overtime income evaluated?"
uv run python -m app.rag.ask --source-set regulation_x "An application is missing a document"
uv run python -m app.rag.ask --search-only "large deposits"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.rag.answer import NO_SUPPORT, ask
from app.rag.sources import SOURCE_SETS
from app.rag.store import get_rag_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--source-set", choices=sorted(SOURCE_SETS), default="all")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--search-only", action="store_true", help="retrieval only, no model call")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.search_only:
        for hit in get_rag_store().search(args.question, args.source_set):
            print(f"{hit.score:6.2f} {hit.coverage:4.2f} {hit.passage.id}  {hit.passage.heading}")
        return 0
    answer = asyncio.run(ask(args.question, args.source_set, provider=args.provider))
    if args.json:
        print(json.dumps(answer.public(), indent=2))
        return 0
    if answer.status != "answered":
        print(NO_SUPPORT)
    for s in answer.sentences:
        print(f"{s['text']} " + "".join(f"[{m}]" for m in s["citations"]))
    for c in answer.citations:
        print(f"  [{c['marker']}] {c['passage_id']}")
    if answer.comparison:
        print(f"Side by side: {answer.comparison['topic']} {answer.comparison['markers']}")
    if answer.removed_sentences:
        print(f"({answer.removed_sentences} sentence(s) removed by the citation checks)")
    if answer.notice:
        print(answer.notice)
    return 0


if __name__ == "__main__":
    sys.exit(main())
