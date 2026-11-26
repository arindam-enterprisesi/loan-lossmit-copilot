# Loan Processing and Mortgage Loss Mitigation Copilot

A demo copilot for US mortgage professionals: loan processing and underwriting (Pillar 1) and loss mitigation (Pillar 2). Synthetic data only. It never approves, denies or offers anything; people make every decision.

Read `CLAUDE.md` first. The functional source of truth is `docs/feature-design.md`.

## Run the demo

Five steps from a clean clone. They are the real `Makefile` targets (on Windows `make` is not
installed by default: `winget install GnuWin32.Make`, or run the command beside each step).

| Step | Command | Does | Measured |
| --- | --- | --- | --- |
| 1 | `cp .env.example .env` | your settings; add keys for a model provider, and `S3_BUCKET` plus AWS credentials to upload documents | seconds |
| 2 | `make up` (`docker compose up -d --build`) | web, api, worker, postgres with pgvector, redis | first build: minutes, not timed here |
| 3 | `make migrate` (`docker compose exec api alembic upgrade head`) | the schema, migrations 0001 to 0009 | not timed here |
| 4 | `make data` (`cd backend && uv run python ../data/synthetic/generate.py`) | renders the two borrowers' documents into `data/synthetic/rendered/` | 7 s |
| 5 | `make reset-demo ARGS="--upload --fake-reader"` | empties the local database and files, seeds the demo, uploads and reads every document | 30 s without `--upload` |

Measured on 24 Nov 2026 from a fresh `git clone` (2 s) and `uv sync` (13 s with a warm cache): steps 4
and 5 as above, step 5 without `--upload` against a scratch database. Steps 2 and 3 need the Docker
images, and step 5 with `--upload` needs S3, so they are not timed here.

`ARGS` chooses how the demo is read: `--upload --fake-reader` reads the documents with the
rule-based reader (no model provider needed: it reads the generated pay stub, bank statement, credit
report, mortgage statement and application, so the budget, the credit analysis and DTI 44.70% all
show); `--upload` alone uses a model provider (`PIPELINE_LLM=auto`, see *Document pipeline*); an empty
`ARGS=` seeds the users, cases and sample reports only and needs no S3.

API on :8000 (`/health`, docs at http://localhost:8000/docs), web placeholder on :3000. The seed
creates three demo users, all with the password from `DEMO_PASSWORD` (default `demo`), and two cases:

| Username | Role | Sees |
| --- | --- | --- |
| `underwriter` | underwriter | Pillar 1 (`underwriting`) cases, e.g. Daniel Reyes |
| `lm_specialist` | lm_specialist | Pillar 2 (`loss_mitigation`) cases, e.g. Angela Whitfield |
| `admin` | admin | both, read only: the administrator makes no case decisions |

Log in with `POST /api/v1/auth/login` (`{"username", "password"}`) and send the token as
`Authorization: Bearer <token>`. `make seed` (`python -m app.db.seed`) adds only the users and the
two empty cases, without the reset.

Other `make` targets: `make down` (`docker compose down`), `make test` (`cd backend && uv run pytest`).
`docs/handover-abhay.md` says how to run and test each module.

Backend checks:

```bash
docker compose up -d postgres      # tests/db builds a throwaway database with the real migration
cd backend
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy app
uv run pytest                      # tests/db skips (locally) if Postgres is not running
uv run python -m app.llm.smoke --provider all   # real calls on each provider with a key in .env
```

`TEST_DATABASE_URL` (default: the compose Postgres) must point at a server where the user can create
databases. The golden tests (`backend/tests/golden`) check every worked example of the Feature Design
to the cent and must stay green.

## Model providers (the LLM steps)

Every model call goes through the LLM Gateway (`backend/app/llm/gateway.py`): a named prompt
(`backend/app/prompts/<name>@<version>.md`), a Pydantic output model, one retry on a schema failure,
and a log line with IDs and token counts only. The provider and model per task are in
`backend/config/llm.yaml`; switch a task's provider there, no code change.

| Provider | `.env` | Model in `llm.yaml` | Checked |
| --- | --- | --- | --- |
| `anthropic` (Claude API, the default) | `ANTHROPIC_API_KEY` | `claude-opus-5-5` | 6/6 checks, `docs/provider-evaluation.md` |
| `bedrock` (Claude on Amazon Bedrock) | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` (leave `AWS_PROFILE` blank or set it) | `global.anthropic.claude-sonnet-4-6` (an inference profile your IAM user may invoke) | 6/6 checks |
| `gemini`, `openai` | `GOOGLE_API_KEY`, `OPENAI_API_KEY` | see `llm.yaml` | not evaluated: no keys on this project |

Scripts run on the host (`reset_demo`, smoke, evaluation) read the repo `.env` themselves
(`app/llm/env.py`); inside docker compose it comes from `env_file`. Blank `AWS_*` values count as unset.

```bash
cd backend
uv run python -m app.llm.smoke --provider anthropic     # smoke + classify + extract + label + hardship + explain
uv run python -m app.llm.evaluate --provider anthropic bedrock --out ../docs/provider-evaluation.md
uv run pytest -m live                                     # the live provider tests; each skips without a key
```

`PIPELINE_LLM=auto` (default) uses the model for reading documents, labelling transactions, income
explanations and the agents; `PIPELINE_LLM=fake` uses the rule-based reader and skips every model call
(the tests run that way).

## Synthetic data

`data/synthetic/scenarios/daniel_reyes.json` and `angela_whitfield.json` hold every figure for the two demo borrowers (the Feature Design worked examples), and `data/synthetic/generate.py` renders their documents from those files only, so a number is the same everywhere it appears:

```bash
make data        # or: cd backend && uv run python ../data/synthetic/generate.py
```

It writes `data/synthetic/rendered/` (git-ignored): `daniel_reyes/` (7 documents), `daniel_reyes/withheld/` (the 2024 W-2 and return the case is meant to be missing), `angela_whitfield/` (8 documents), `broken/` (a password-protected PDF, a corrupt PDF, an unsupported CSV, a duplicate and two degraded scans) and `manifest.json` (type, role, pages, SHA-256, expected behaviour for each file). Known defects are built in: Daniel's stub prints net pay 2,083.61 (true 2,033.61) and his August statement says "Page 1 of 3" with two pages. Each scenario file separates `documented`, `derived` and `invented` values in its `provenance` block. All people and accounts are invented.

## Document upload

`POST /api/v1/cases/{case_id}/documents` (multipart: `files`, optional `declared_type`) takes PDF, PNG or JPEG up to the size in `backend/config/ingestion.yaml` (25 MiB). The type comes from the file's own bytes. The original is stored unchanged in S3 under `{S3_PREFIX}cases/{case_id}/documents/{document_id}/original` (IDs only, never the file name), the row and an audit event are written, and one `document_ingest` job is queued for the worker. The worker (`app/services/ingestion.py`) renders each page to PNG at the configured DPI and stores the text layer as numbered lines (`p1-L31`) with boxes. A file that is already in the case is accepted and carries the warning flag `DI-W206`. Locked and corrupt files end as `failed` with the reason in the job's `error`. Pages with no usable text layer (fewer than `ocr.min_text_chars` characters, and every PNG or JPEG) are read by Tesseract: the page image is scaled to about 300 dpi, lightly denoised, straightened and thresholded (`app/services/ocr.py`, settings in `backend/config/ingestion.yaml`), and the words become the same numbered lines with boxes plus a confidence from 0 to 1. A line below `min_line_confidence` (`validation.yaml`) lowers the certainty of the fields cited from it, so a reviewer sees them first, and the engine and version are recorded in the `document.ingested` audit event. Without the `tesseract` program (or with `OCR_ENGINE=none`) such pages fail with the reason, as before; the worker image and CI install it, and the tests that run the real engine skip when it is missing. `GET` on the same path lists the case's documents.

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

**Hardship profile (read side).** `GET /api/v1/cases/{id}/hardship-assessment/latest` returns the borrower's letter read into a profile: primary and other reasons, onset, duration, intent, a timeline and the enclosed documents, each with its quote, the line IDs it came from and `verified` (code found the quote in those lines). A quote that fails the check also raises a flag. Until a model provider is used for it, the profile is a seeded sample (`source: seeded_sample`, the Feature Design 7.8 reading in `app/db/demo/angela_hardship_profile.json`), checked in code against the letter's lines; reading the letter, confirming values and the budget are in the next section. The table is `hardship_profiles` (migration 0006).

## Assets, liabilities and DTI (Feature 3)

`PUT/GET /api/v1/cases/{id}/loan-scenario` takes the sample loan by hand (nothing is priced).
`POST .../asset-liability` queues a run (poll `GET /jobs/{id}`), `GET .../asset-liability/latest` reads
it, and `PATCH .../asset-liability/latest/transactions/{id}` and `.../obligations/{id}` reclassify a
line, mark a deposit sourced, or include or exclude a debt, each with a reason, recalculating at once
with no model call. The statement lines are labelled once (`app/services/transaction_labels.py`: the
model through `app.llm.tasks.label_transactions`, or `FakeLabeller` with `PIPELINE_LLM=fake`); after
that everything is plain code in `app/services/assets.py` (all `Decimal`, every figure a row in
`calculations` with working and evidence): payroll matches, large deposits, recurring debts reconciled
with the credit report's liabilities, documented assets against the funds needed, front-end ratio,
DTI (and with overtime), LTV and `what_if` for the agents. Daniel's worked example: assets 9,226.32,
shortfall 27,273.68, obligations 693.00, front-end 33.11%, DTI 44.70%, LTV 90.00%.

## Credit report analysis (Feature 4)

`POST /api/v1/cases/{id}/credit-analysis` (poll the job) and `GET .../credit-analysis/latest`. No model
is called: the pipeline already read the report into fields (`score_NNN_*`, `tradeline_NNN_*`,
`inquiry_NNN_*`), and `app/services/credit.py` computes the representative score (the middle of three,
the lower of two), utilization per revolving account and in total, late payments by severity within
the 24-month lookback and the months since the last one, inquiries matched to a new account, the
derogatory list and the monthly payments by account type, each with its working and the report lines
it came from. Flags (`CR-W101` and so on) are templates and the summary is a template filled from the
stored results. Daniel's report: score 705, Northgate 36.75%, total revolving 28.00%, payments 693.00.
The tables are `credit_scores`, `tradelines` and `credit_inquiries` (migration 0009).

## Hardship reading, confirmations and the budget (Feature 7)

`POST /api/v1/cases/{id}/hardship-assessment` queues a reading of the letter (the model, behind a
`HardshipReader`; the seeded sample stays as history) and builds the budget from the case's
documents, which is plain code (`app/services/budget.py`). `PUT .../hardship-assessment/latest/confirmations`
confirms or corrects the reason, onset, duration and intent with a reason: the reading is never
overwritten, the confirmation sits beside it labelled "reviewer-confirmed", and only the loss
mitigation specialist may do it. `PATCH .../latest/budget/{line_id}` counts a different observed amount
for a line (a one-off), with a reason. The budget has a stated side (the application) and an observed
side (the statements: per line, the latest statement month with a debit in it), the surplus or deficit
on both, the housing ratio, arrears, liquid assets, and consistency checks. Angela's worked example:
income 4,200.00, expenses 3,420.00 stated and 3,630.00 observed, deficits 70.00 and 280.00, housing
40.95%, arrears 5,160.00.

## Loss mitigation rules and the lender view (Feature 8)

`POST /api/v1/cases/{id}/lm-recommendation` (specialist only, poll the job) applies the investor's
rule set in code and stores a new run; `GET .../lm-recommendation/latest` shows the waterfall (each
option with its status, its conditions, the values used and the passage cited), the lender view with
its working, the rule set with its "illustrative" banner, any overrides and the report once the agents
have written one. The rule set is `backend/config/rule_sets/sample_investor_a_v1.yaml` (versioned and
labelled; every number a quoted string); `app/services/rules_engine.py` evaluates it. A judgement
nobody has confirmed (hardship duration, intent to keep the home) is reported as needing confirmation
and never used; the waterfall stops at the first option whose conditions are met (`met` says the
conditions are met and nothing more). `PUT .../latest/conditions/{id}/override` changes a condition
with a reason and the statuses recompute, with the rules' own answer beside it; overrides carry to the
next evaluation. Angela's worked example: modification conditions met (target payment 1,470.00 below
1,720.00), foreclosure loss 16,310.00, modification cost 13,893.00, advantage 2,417.00. Months
delinquent comes from `loan_records`, the simulated servicing record that `make reset-demo` seeds.

## Reports, review, sign-off, audit and guidelines

`GET .../underwriting-report/latest` and `.../lm-recommendation/latest` read the newest report with its
findings, conditions and agent runs; `app/services/report_writer.py` is how Arindam's agents write
them. Until the agents run, a seeded sample fills them and every response says `seeded_sample`. The
underwriter accepts, edits or rejects each condition (the agents' text stays beside the edit) or adds
their own, and signs off; the loss mitigation specialist overrides conditions and signs off. A
sign-off records that a person reviewed a version of the report: "Records a review. Not a decision."
The recommendation's sign-off needs a report on the newest evaluation (409 `no_report` otherwise).
`GET .../audit` lists a case's events newest first (filters `action`, `entity_type`, paging with
`before`); `GET /api/v1/guidelines/sources` and `/guidelines/passages/{id}` read the cited passages.

## Guideline assistant (Feature 5)

`data/sources/*.md` holds the sources: Fannie Mae and Freddie Mac sections on income, assets,
liabilities and credit, a sample lender overlay, and 12 CFR 1024.41. **All are illustrative
paraphrases written for the demo**, not the publishers' text (`data/sources/README.md` says how to
load the real text). The Sample Investor A passages that Feature 8 cites are loaded with them.
Retrieval is BM25 in code with a coverage threshold and direct lookup of a named section
(`backend/config/rag.yaml`); with no passage above the threshold the answer is "no supporting
passage found" and no model is called. The answer (`answer@1`) cites a passage in every sentence, and
code removes any sentence whose citation, quotation or figure is not supported, or that uses decision
wording. Regulation X answers carry "Not legal advice; confirm with your compliance team."

```bash
cd backend
uv run python -m app.rag.ask "How is overtime income evaluated?"
uv run python -m app.rag.ask --source-set regulation_x "The application is missing a document. What must the servicer do?"
uv run python -m app.rag.evaluate            # 16 questions: retrieval hit rate and no-support accuracy
uv run python -m app.rag.evaluate --answers  # also answers each one (provider calls)
```

`POST /api/v1/guidelines/ask` (`question`, `source_set` = `guidelines` | `regulation_x` | `all`,
optional `case_id` to attach the case's facts) and `POST /guidelines/answers/{id}/feedback`; both are
in the audit log.

## Agents: underwriting copilot and LM recommendation (Features 6 and 8)

`backend/app/agents`: code builds the dossier (every stored figure with its working, the open flags,
the checklist gaps), the findings list and the snapshot; then the **Researcher** asks the guideline
assistant about each kind of finding, the **Writer** drafts the narrative only, and the **Critic**
runs code checks (every figure must equal a stored result, no decision wording, every ref resolves)
and a reading check, and returns the draft once. Whatever still fails is removed and recorded in the
report's `guardrail_results`. A failed agent leaves its section "not available"; the report still
completes. Settings (review priority per flag code, research topics, blocked words) are in
`backend/config/agents.yaml`.

| Endpoint | Does |
| --- | --- |
| `POST /cases/{id}/underwriting-report` | starts the three agents in the worker (202 and a job) |
| `POST /cases/{id}/underwriting-report/latest/agents/{researcher,writer,critic}/rerun` | runs one agent again (and the steps after it); writes the next report version |
| `POST /cases/{id}/lm-recommendation` | applies the rules in code, then the agents write the report on the same run |
| `POST /cases/{id}/lm-recommendation/latest/agents/{agent}/rerun` | as above, for the recommendation |

Each workflow takes about a minute with Claude. With `PIPELINE_LLM=fake` the agents are not run and
the seeded sample reports stay.

## API tests

`backend/tests/db/test_endpoint_matrix.py` holds every endpoint to the same four rules (no token is a
401, a role that may not act is a 403, the other pillar's case is a 404, an invalid body is a 422) and
fails if an endpoint is added without a row. `backend/tests/db/test_demo_stories.py` runs both demo
stories through the HTTP API only, upload to sign-off, with the rule-based reader and stubs standing
in for the models and the agents.

## Demo reset

`make reset-demo` (`cd backend && uv run python -m app.db.reset_demo --yes --upload`) puts the demo
back to a clean state: it undoes and redoes the migrations (which also clears the append-only audit
history), removes the stored files, seeds the three users, both cases with their profiles, Angela's
simulated loan record and hardship profile, and the sample reports to review (labelled
`seeded_sample`), then uploads and reads every demo document in the same process, with no worker, and
builds Angela's budget. Run `make data` first and have S3 set up in `.env`. `--fake-reader` reads
with the rule-based reader when no model provider works; leave `--upload` off to skip the documents.
It needs `--yes` and refuses any database that is not local, because it empties the database it is
pointed at.

## Layout

| Path | What | Owner |
| --- | --- | --- |
| `contracts/openapi.yaml` | API contract (source of truth for the frontend types) | Arindam |
| `backend/app/llm` | LLM Gateway and provider adapters | Arindam |
| `backend/app/prompts` | Versioned prompts (`name@version.md`) and output schemas | Arindam |
| `backend/app/rag`, `backend/app/agents` | Guideline retrieval and answers; the three agents (plain asyncio) | Arindam |
| `backend/app/api`, `services`, `db` | REST endpoints, calculations, rules, storage | Abhay |
| `backend/config` | Checklists, methods, thresholds, `llm.yaml` | Abhay (`llm.yaml`: Arindam) |
| `data/` | Synthetic scenarios (Abhay) and guideline sources in `data/sources` (Arindam) | Abhay, Arindam |
| `frontend/` | Next.js app | Amogh |
| `docs/` | Feature Design, FSD, ADRs, demo scripts | All |

## Workflow

Branch `feat/<name>/<topic>` from the latest `main`, open a draft PR early, and fill in the PR template. CI (ruff, mypy, pytest, contract lint, frontend lint/types/build) must be green, with one approval. Squash merge. Review windows: 1:00 pm and 6:00 pm IST.
