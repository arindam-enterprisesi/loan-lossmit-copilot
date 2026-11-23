# Loan Processing and Mortgage Loss Mitigation Copilot

A demo copilot for US mortgage professionals: loan processing and underwriting (Pillar 1) and loss mitigation (Pillar 2). Synthetic data only. It never approves, denies or offers anything; people make every decision.

Read `CLAUDE.md` first. The functional source of truth is `docs/feature-design.md`.

## Start

```bash
cp .env.example .env      # add your own keys
docker compose up         # web, api, worker, postgres+pgvector, redis
```

API on :8000 (`/health`), web placeholder on :3000. Optional `make` shortcuts (on Windows, `make` is not installed by default: `winget install GnuWin32.Make`, or run the commands from the `Makefile` directly):

| Command | Runs |
| --- | --- |
| `make up` / `make down` | `docker compose up -d --build` / `docker compose down` |
| `make migrate` | `alembic upgrade head` inside the api container |
| `make seed` | seed script (a stub until the synthetic data task lands) |
| `make test` | `cd backend && uv run pytest` |
| `make reset-demo` | empties the local database and stored files, then rebuilds the demo (see *Demo reset*) |

First run: `docker compose exec api alembic upgrade head` then `docker compose exec api python -m app.db.seed` (`make migrate`, `make seed`). The seed creates three demo users, all with the password from `DEMO_PASSWORD` (default `demo`), and two empty cases:

| Username | Role | Sees |
| --- | --- | --- |
| `underwriter` | underwriter | Pillar 1 (`underwriting`) cases, e.g. Daniel Reyes |
| `lm_specialist` | lm_specialist | Pillar 2 (`loss_mitigation`) cases, e.g. Angela Whitfield |
| `admin` | admin | both |

Log in with `POST /api/v1/auth/login` (`{"username", "password"}`) and send the token as `Authorization: Bearer <token>`. Interactive docs: http://localhost:8000/docs.

Backend checks:

```bash
docker compose up -d postgres      # tests/db builds a throwaway database with the real migration
cd backend
uv sync
uv run pytest                      # tests/db skips (locally) if Postgres is not running
uv run python -m app.llm.smoke --provider all   # real calls on each provider with a key in .env
```

`TEST_DATABASE_URL` (default: the compose Postgres) must point at a server where the user can create databases.

## Synthetic data

`data/synthetic/scenarios/daniel_reyes.json` and `angela_whitfield.json` hold every figure for the two demo borrowers (the Feature Design worked examples), and `data/synthetic/generate.py` renders their documents from those files only, so a number is the same everywhere it appears:

```bash
make data        # or: cd backend && uv run python ../data/synthetic/generate.py
```

It writes `data/synthetic/rendered/` (git-ignored): `daniel_reyes/` (7 documents), `daniel_reyes/withheld/` (the 2024 W-2 and return the case is meant to be missing), `angela_whitfield/` (8 documents), `broken/` (a password-protected PDF, a corrupt PDF, an unsupported CSV, a duplicate and two degraded scans) and `manifest.json` (type, role, pages, SHA-256, expected behaviour for each file). Known defects are built in: Daniel's stub prints net pay 2,083.61 (true 2,033.61) and his August statement says "Page 1 of 3" with two pages. Each scenario file separates `documented`, `derived` and `invented` values in its `provenance` block. All people and accounts are invented.

## Document upload

`POST /api/v1/cases/{case_id}/documents` (multipart: `files`, optional `declared_type`) takes PDF, PNG or JPEG up to the size in `backend/config/ingestion.yaml` (25 MiB). The type comes from the file's own bytes. The original is stored unchanged in S3 under `{S3_PREFIX}cases/{case_id}/documents/{document_id}/original` (IDs only, never the file name), the row and an audit event are written, and one `document_ingest` job is queued for the worker. The worker (`app/services/ingestion.py`) renders each page to PNG at the configured DPI and stores the text layer as numbered lines (`p1-L31`) with boxes. A file that is already in the case is accepted and carries the warning flag `DI-W206`. Locked, corrupt and image-only files end as `failed` with the reason in the job's `error`; there is no OCR yet (`OcrAdapter` is a stub). `GET` on the same path lists the case's documents.

Uploading needs `S3_BUCKET` (and AWS credentials) in `.env`; without it the endpoint answers 503 `storage_unavailable`. Tests use moto, so they need neither S3 nor Redis.

## Document pipeline

The worker takes each uploaded document through five stages, each safe to run twice and alone: **ingest** (pages and numbered lines), **classify** (the type, from the lines only), **extract** (a new run of fields, each with the lines it came from), **validate** (the checks in code: every value really appears in its cited lines, amounts and dates normalised, identifiers cut to their last four digits, pay stub and bank statement arithmetic, printed "Page X of Y" against the pages uploaded) and **ready** (status and a template summary). Each failed check is a row in `flags` with a template message, its evidence lines and its working. Poll `GET /api/v1/jobs/{job_id}`; read the result with `GET .../documents/{doc}/extraction` (flagged fields first). A person confirms, corrects or rejects a value with `PATCH .../fields/{name}` (the original is kept, a correction needs a reason, the checks re-run with no model call) and changes a type with `PUT .../type`.

`PIPELINE_LLM` chooses the reader: `auto` (default) uses Arindam's `app.llm.tasks.classify` and `extract` when they exist and the rule-based fake otherwise; `fake` always uses the fake (offline work, and what the tests use). `LlmExtractor` (`app/services/extractor.py`) flattens his nested lists (earnings lines, transactions, Box 12 entries) into indexed fields such as `earnings_001_hours`. Every extraction run records its provider, so a fake result is never mistaken for a model's. Settings: `backend/config/validation.yaml` (tolerance and every flag message) and `backend/config/document_fields.yaml` (the field list, roles, repeating rows and summaries), both versioned and labelled illustrative. A real model call can take minutes, so the worker allows `WORKER_JOB_TIMEOUT` seconds a job (default 1800) and `WORKER_MAX_JOBS` at once (default 4).

## Income analysis and completeness

**Income** (Feature 2): `POST /api/v1/cases/{id}/income-analysis` queues a run (poll `GET /jobs/{id}`), `GET .../income-analysis/latest` reads it, and `PATCH .../income-analysis/latest/components/{component}` includes or excludes a component with a reason. Plain code in `app/services/income.py` and `calculations.py` (all `Decimal`): earnings lines are grouped into base, overtime, bonus and commission; base pay is rate x regular hours x pay periods per year / 12; overtime and bonus are the year-to-date average a month and count only with 24 months of history (otherwise excluded, with the reason); W-2 Box 5, 1040 wages, employer, Box 12 deferrals, the trend, year-to-date pay and the pay frequency are cross-checked. Every figure is a row in `calculations` with its formula, inputs, working and the document fields it came from; a check that cannot run says so (an info flag) and never guesses. Including or excluding recalculates the candidate at once, with no model call, keeps what the system decided beside the person's change, and writes an audit event. Settings: `backend/config/income_method.yaml` and `thresholds.yaml` (every setting carries `value`, `label` and `source`; each run records the version and hash of the files it used in `config_versions`). The one AI call of this feature (possible explanations of the flags) is not wired yet: the result says "explanations not generated".

**Completeness** (Feature 1): `POST /api/v1/cases/{id}/completeness` with `{"checklist_id": "pillar1-wage-earner@1"}` (the case profile must have borrower names and a reference date), `GET .../completeness/latest`, and `PATCH .../completeness/latest/items/{item_id}` to override an item with a written reason (or clear it). Code decides every status (`app/services/completeness.py`, FSD section 7): documents are matched to the borrower by name, date ranges are merged (adjacent days are one span), coverage, recency and missing tax years are measured, and messages are templates such as "14 of 30 days of pay stubs found". An override counts as satisfied and never replaces the computed status. Checklists: `backend/config/checklists.yaml`, illustrative.

## Browser access, page images and the hardship profile

**CORS.** The frontend (http://localhost:3000) and the API (:8000) are different origins to a browser, so the API answers their preflight requests. `CORS_ORIGINS` (comma-separated, default `http://localhost:3000`, no wildcards) lists the allowed origins; the methods are GET, POST, PUT, PATCH, DELETE and OPTIONS, the headers `Authorization` and `Content-Type`, and cookies stay off because the token is a bearer header.

**Page images.** `GET /api/v1/cases/{id}/documents/{doc}/pages/{n}` returns `{page, url, expires_at, width, height}`: a 5-minute link to the stored page image and its size in pixels. Evidence boxes are fractions of that image (0 to 1, origin top left), so a viewer multiplies by `width` and `height`. A hidden case, unknown document or page that is not there is a 404; storage down is a 503. If the frontend reads the image with `fetch` or a canvas instead of an `<img>` tag, the S3 bucket needs its own CORS rule in AWS.

**Hardship profile (read side).** `GET /api/v1/cases/{id}/hardship-assessment/latest` returns the borrower's letter read into a profile: primary and other reasons, onset, duration, intent, a timeline and the enclosed documents, each with its quote, the line IDs it came from and `verified` (code found the quote in those lines). A quote that fails the check also raises a flag. Until a model provider is used for it, the profile is a seeded sample (`source: seeded_sample`, the Feature Design 7.8 reading in `app/db/demo/angela_hardship_profile.json`), checked in code against the letter's lines; running a reading, confirming values and the budget come later. The table is `hardship_profiles` (migration 0006).

## Demo reset

`make reset-demo` (`cd backend && uv run python -m app.db.reset_demo --yes --upload`) puts the demo back to a clean state: it undoes and redoes the migrations (which also clears the append-only audit history), removes the stored files, seeds the three users, both cases with their profiles and Angela's hardship profile, then uploads and reads every demo document in the same process, with no worker. Run `make data` first and have S3 set up in `.env`. `--fake-reader` reads with the rule-based reader when no model provider works; leave `--upload` off to skip the documents. It needs `--yes` and refuses any database that is not local, because it empties the database it is pointed at.

## Layout

| Path | What | Owner |
| --- | --- | --- |
| `contracts/openapi.yaml` | API contract (source of truth for the frontend types) | Arindam |
| `backend/app/llm` | LLM Gateway and provider adapters | Arindam |
| `backend/app/prompts` | Versioned prompts (`name@version.md`) and output schemas | Arindam |
| `backend/app/rag`, `backend/app/agents` | Retrieval and LangGraph agents | Arindam |
| `backend/app/api`, `services`, `db` | REST endpoints, calculations, rules, storage | Abhay |
| `backend/config` | Checklists, methods, thresholds, `llm.yaml` | Abhay (`llm.yaml`: Arindam) |
| `data/` | Synthetic scenarios and guideline sources | Abhay |
| `frontend/` | Next.js app | Amogh |
| `docs/` | Feature Design, FSD, ADRs, demo scripts | All |

## Workflow

Branch `feat/<name>/<topic>` from the latest `main`, open a draft PR early, and fill in the PR template. CI (ruff, mypy, pytest, contract lint, frontend lint/types/build) must be green, with one approval. Squash merge. Review windows: 1:00 pm and 6:00 pm IST.
