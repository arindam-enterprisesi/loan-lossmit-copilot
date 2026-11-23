# Hand-over: Abhay's modules (24 Nov 2026)

For whoever runs and extends the backend while Abhay is out (25 and 26 Nov). Everything below is on
the branch `feat/abhay/rules-engine` (stacked on `main` at #12). All data is synthetic. Read
`CLAUDE.md` first: code does all arithmetic, every figure links to evidence, people make every
decision, every setting lives in `backend/config` with a version and a label.

## 1. Run it

```bash
cp .env.example .env              # add provider keys; S3_BUCKET + AWS credentials to upload documents
make up                           # docker compose up -d --build   (on Windows: winget install GnuWin32.Make)
make migrate                      # docker compose exec api alembic upgrade head   (0001 to 0009)
make data                         # cd backend && uv run python ../data/synthetic/generate.py
make reset-demo ARGS="--upload --fake-reader"   # or ARGS=  to seed with no documents and no S3
```

Log in as `underwriter`, `lm_specialist` or `admin` (password `DEMO_PASSWORD`, default `demo`) with
`POST /api/v1/auth/login`; the API docs are at http://localhost:8000/docs. `--fake-reader` reads the
documents with the rule-based reader (`backend/app/services/fake_reader.py`), which needs no model
provider and shows every figure below. Without it the real model reads them (`PIPELINE_LLM=auto`).

To test: `docker compose up -d postgres`, then in `backend/`:

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy app
uv run pytest                     # 1,697 tests (24 live-provider ones are deselected); the database ones take most of the time
uv run pytest tests/golden        # the worked examples only: seconds
```

## 2. Module by module

"Golden" is the test that checks the Feature Design's worked example to the cent
(`backend/tests/golden`, reading each scenario's `expected` block in `data/synthetic/scenarios`).

| Module | Where | Run it | Test it | Worked example |
| --- | --- | --- | --- | --- |
| Document pipeline (ingest, classify, extract, validate) | `app/services/ingestion.py`, `pipeline.py`, `classification.py`, `extractor.py`, `fake_reader.py`, `validation.py`; settings `config/document_fields.yaml`, `validation.yaml`, `ingestion.yaml` | `POST /cases/{id}/documents` (needs S3), worker `process_documents` | `tests/db/test_pipeline.py`, `tests/services/test_fake_reader.py`, `tests/services/test_validation.py` | Daniel's stub net pay 2,083.61 against 2,033.61 is flagged `DI-CHK-02` |
| Income (Feature 2) | `app/services/income.py`, `income_runs.py`, `calculations.py`; `config/income_method.yaml`, `thresholds.yaml` | `POST /cases/{id}/income-analysis`, `GET .../latest`, `PATCH .../components/{id}` | `tests/golden/test_income_golden.py`, `tests/db/test_income_api.py` | base income 4,853.33, candidate 5,980.00 |
| Completeness (Feature 1) | `app/services/completeness.py`, `completeness_runs.py`; `config/checklists.yaml` | `PUT /cases/{id}/profile` first, then `POST .../completeness` | `tests/db/test_completeness_api.py` | the 2024 W-2 and return are missing |
| Assets, liabilities, DTI (Feature 3) | `app/services/assets.py`, `asset_runs.py`, `loan_scenarios.py`, `transaction_labels.py` | `PUT .../loan-scenario`, `POST .../asset-liability` | `tests/golden/test_assets_golden.py`, `tests/db/test_asset_api.py` | assets 9,226.32, shortfall 27,273.68, DTI 44.70%, with overtime 41.61% |
| Credit report (Feature 4) | `app/services/credit.py`, `credit_runs.py`; settings in `thresholds.yaml`; tables migration 0009 | `POST .../credit-analysis`, `GET .../latest` | `tests/golden/test_credit_golden.py`, `tests/db/test_credit_api.py`, `test_credit_tables.py` | score 705, Northgate 36.75%, revolving 28.00%, payments 693.00 |
| Hardship and budget (Feature 7) | `app/services/hardship.py`, `hardship_runs.py`, `budget.py`, `budget_runs.py`; `config/hardship.yaml`, `thresholds.yaml` | `POST .../hardship-assessment`, `PUT .../latest/confirmations`, `PATCH .../latest/budget/{line}` | `tests/golden/test_budget_golden.py`, `tests/db/test_hardship_budget_api.py` | income 4,200.00, deficits 70.00 and 280.00, housing 40.95%, arrears 5,160.00 |
| Loss mitigation rules (Feature 8) | `app/services/rules_config.py`, `rules_engine.py`, `recommendation_runs.py`, `waterfall_status.py`; `config/rule_sets/sample_investor_a_v1.yaml` | `POST .../lm-recommendation`, `GET .../latest`, `PUT .../conditions/{id}/override` | `tests/golden/test_rules_golden.py`, `tests/db/test_recommendation_api.py`, `tests/services/test_rules_config.py` | modification conditions met; loss 16,310.00, cost 13,893.00, advantage 2,417.00 |
| Reports, review, sign-off, audit, guidelines | `app/services/reports.py`, `report_writer.py`, `review_conditions.py`, `audit.py`, `guidelines.py`; seeds in `app/db/demo/` | `GET .../underwriting-report/latest`, `PATCH .../conditions/{id}`, `POST .../sign-off`, `GET .../audit` | `tests/db/test_report_review_api.py`, `test_report_writer_and_guidelines.py` | six conditions: five accepted, one rejected with a reason |
| Demo data and reset | `app/db/reset_demo.py`, `app/db/seed.py`, `app/db/demo/`, `data/synthetic/` | `make data`, `make reset-demo` | `tests/db/test_reset_demo.py`, `tests/data/` | two cases, seeded profile, loan record, sample reports |
| Every endpoint | `app/api/routers/`, `app/api/schemas/` | `/docs` | `tests/db/test_endpoint_matrix.py` (42 endpoints, four rules each), `tests/db/test_demo_stories.py` (both stories over HTTP) | upload to sign-off for Daniel and Angela |

How a module is built: a pure module does the arithmetic (`assets.py`, `budget.py`, `credit.py`,
`rules_engine.py`: no database, no model, every result a `Calc` with working and evidence); a
`*_runs.py` module gathers the case's documents, stores the run, and reads it back; a router calls
it; a worker function in `app/worker.py` runs the slow part. A person's change updates the row, keeps
what the system produced beside it, recalculates with no model call, and writes an audit event.

## 3. Stand-ins (the full list is `docs/build-log.md`)

| What is not real yet | Stand-in | Swap |
| --- | --- | --- |
| A model provider that works through the app (A1, X1, D4) | `PIPELINE_LLM=fake`: the rule-based reader, labeller and the seeded hardship reading | Get `python -m app.llm.smoke --provider all` passing, set `PIPELINE_LLM=auto`, `make reset-demo` without `--fake-reader` |
| The agents' reports (A6, D8) | `app/db/demo/daniel_underwriting_report.json` and `angela_lm_recommendation.json`, labelled `seeded_sample` | Arindam's graph writes through `report_writer.write_report`; the endpoints do not change |
| The rules for the agents' step 4 | done: `run_recommendation_rules(session, case_id)` | his graph calls it |
| Guideline passages (D1) | 11 seeded passages (`app/db/demo/guideline_passages.json`) | his RAG loader fills the guideline tables (their migration waits for the embedding size) |
| The servicing record | `loan_records`, synthetic, seeded from the scenario | a real source is out of scope |
| Income explanations (A3) | not wired: `explanations: []` | call `income-explain@1` and `check_figures` after the flags are stored |

## 4. Decisions made without asking (change them if wrong)

1. **Feature 4 was kept and built.** No decision to cut it was recorded and cutting it costs Daniel's
   44.70% demo. It is self-contained (migration 0009, `credit.py`, `credit_runs.py`, one router).
2. **"Hardship resolved" is `not_met` once the duration is confirmed**, because the hardship profile
   has no `resolved` value (A7). A reviewer can override it with a reason. Adding `resolved` to the
   duration categories is Arindam's call (`hardship@1`).
3. **Sign-off of the recommendation needs a report on the newest evaluation** (409 `no_report`),
   because the rules write no report and an older run's report does not describe the waterfall on
   screen. A rules-only report would need a new `reports.source` value, which is a migration.
4. **The "no earlier option's conditions are met" condition waits** (needs confirmation or not
   evaluable) while an earlier option is undecided for that reason, instead of reading as met.
5. **The rule-based reader reads more types** (credit report, mortgage statement, application, the
   stub's printed pay frequency) so the demo works without a provider. It records `provider: fake`.
6. **Seeded passage IDs use my scheme** (`sample-investor-a-v1.repayment-plan.1`); Arindam may change it.

## 5. Pull requests

The branch is one large stack. Per `CLAUDE.md` a migration goes in its own small PR, merged first:

1. Migration 0009 and its models and tests: commit `dcfd9d6` (cherry-pick it onto `main` for its own PR).
2. The contract: `docs/contract-proposal-d4.md` sections 1 to 9 are YAML for Arindam's contract PR
   (`contracts/` is not touched). Amogh's generated types wait for it.
3. Everything else: rules engine (`6199d94`), credit analysis (`7b8ee55`), integration tests and the
   rule-based reader (`6ea224e`), then this README and hand-over.

Changes made in other people's folders on D7: none. (The Bedrock adapter edit in `backend/app/llm`
was D6, commit `ad8d45e`, and is already in `main` through #12; Arindam should still review it.)

## 6. Open items

GitHub issues could not be opened from here (the `gh` command is not installed), so each is written
out to paste. Owner in brackets.

| Title | Body |
| --- | --- |
| Contract PR for D4 to D7 endpoints [Arindam] | Paste the YAML in `docs/contract-proposal-d4.md` sections 1 to 9 into `contracts/openapi.yaml`, then add a contract-alignment test as done for completeness. Amogh's types for income, assets, credit, hardship, reports and recommendation depend on it. |
| Review the Bedrock adapter change [Arindam] | `ad8d45e` switched `backend/app/llm/adapters/anthropic.py` to the bedrock-runtime client (D4 in the build log). It is in `main` through #12 without his review. |
| Reader schemas for the credit report, mortgage statement and application [Arindam] | The field names the pipeline stores are in `backend/config/document_fields.yaml` (`credit_report`, `mortgage_statement`, `mortgage_assistance_application`). His extract schemas must emit them (A8, A2) for a model to read these types. |
| Add `resolved` to the hardship duration categories? [Arindam] | Decision A7: the repayment plan and payment deferral need "hardship resolved (confirmed)" and the profile cannot say it. |
| Embedding size and the guideline tables migration [Arindam] | D1: `vector(1024)` in the schema doc against 1536 in `llm.yaml`. The tables (`guideline_sources`, `rag_chunks`, `guideline_questions`) come after migration 0009 as 0010. Then the passage-ID scheme and the real loader replace the seeded passages. |
| Agents write the underwriting report and the recommendation [Arindam] | D8: his graph writes through `report_writer.write_report` and calls `run_recommendation_rules`. Then the two `.../agents/{agent}/rerun` endpoints and `POST .../underwriting-report`, which are his. |
| A model provider that works through the app [Arindam, platform engineer] | A1 and X1: until it does, the demo uses `--fake-reader` and the seeded hardship reading. |
| Income explanations [Abhay or Arindam] | A3: wire `income-explain@1` and `check_figures`; the result says "explanations not generated". |
| Credit annotations [Abhay] | `PATCH /cases/{id}/credit-analysis/latest/items/{item}` (Feature Design 4.7) is not built. |
| A rules-only report so the recommendation can be signed off before the agents run [Abhay] | Needs a `reports.source` value (a migration). Today the sign-off answers 409 `no_report`. |
| `llm_calls` table [Arindam or Abhay] | D2: never built; the gateway only logs. |
| Screens for assets, credit, hardship budget, recommendation and review [Amogh] | The endpoints are built and answer on seeded data (M1 to M3 in the build log). `NEXT_PUBLIC_USE_MOCKS=false` needs real calls in `frontend/src/lib/api.ts`. |
