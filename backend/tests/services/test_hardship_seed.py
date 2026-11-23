"""The seeded hardship profile for Angela Whitfield (Feature Design 7.8): no model, checked in code.

The demo shows her letter read into a profile before any model provider works. The reading is a data
file; these tests keep it identical to Arindam's worked example, make sure every quote in it is on
the line it cites, and make sure those line IDs are the ones ingestion gives the generated letter.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.db.demo.hardship import load_seed_profile
from app.llm.checks import verify_quotes
from app.llm.samples import load_lines
from app.prompts.schemas.hardship import hardship_profile_model, load_hardship_config
from app.services.ingestion import parse_pdf
from tests.conftest import Rendered
from tests.llm.test_hardship import angela_reply

SEED_FILE = (
    Path(__file__).resolve().parents[2] / "app" / "db" / "demo" / "angela_hardship_profile.json"
)
LETTER = "angela_whitfield/hardship_letter.pdf"


def test_the_seed_is_arindams_worked_example_exactly() -> None:
    # If the reading changes in tests/llm/test_hardship.py, the demo must change with it.
    assert json.loads(SEED_FILE.read_text(encoding="utf-8"))["profile"] == angela_reply()


def test_the_seed_loads_into_the_profile_model_for_the_configured_categories() -> None:
    config = load_hardship_config()

    profile = load_seed_profile(config)

    assert isinstance(profile, hardship_profile_model(config.keys))
    assert profile.primary_reason.category == "reduction_in_income"
    assert (profile.onset.month, profile.duration.category, profile.intent.category) == (
        "2026-07",
        "unknown",
        "keep",
    )


def test_every_quote_in_the_seed_is_on_the_line_it_cites() -> None:
    config = load_hardship_config()

    checks = verify_quotes(
        load_seed_profile(config),
        load_lines("angela_hardship_letter"),
        max_quote_chars=config.max_quote_chars,
    )

    assert len(checks) == 9
    assert [c.path for c in checks if not c.verified] == []


def test_the_sample_letter_lines_are_what_ingestion_reads_from_the_generated_letter(
    rendered: Rendered,
) -> None:
    # The seed is checked against the sample lines when the letter is not uploaded; this proves
    # those lines (and so the line IDs in the profile) match what ingestion stores.
    parsed = parse_pdf(rendered.read(LETTER), dpi=50)

    read = [(p.page_no, n, line.text) for p in parsed.pages for n, line in enumerate(p.lines, 1)]

    assert read == [(ln.page, ln.line, ln.text) for ln in load_lines("angela_hardship_letter")]
