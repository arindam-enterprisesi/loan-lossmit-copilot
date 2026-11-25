# Guideline sources (Feature Design 5.3)

The guideline assistant (`backend/app/rag`) loads every `*.md` file here, plus the Sample Investor A
passages seeded in `backend/app/db/demo/guideline_passages.json` (Feature 8 cites them).

Each file starts with a front-matter block (`id`, `title`, `kind`, `label`, `version`, `publisher`,
`url`, `notice`), then one `## <section id> | <heading>` block per passage. A passage's ID is
`<file id>.<section id>`, and that ID is what answers, findings and conditions cite.

**Every file here is labelled `illustrative`.** They are short paraphrases written for the demo from
the publishers' public guides, not the publishers' text, so no figure in them may be relied on.
To replace one with the publisher's text: download it, keep its section structure, set
`label: authoritative` and its real `version` (or "as of" date), and keep the section IDs where the
topic is the same. The evaluation (`uv run python -m app.rag.evaluate`) checks that the expected
sections are still found.
