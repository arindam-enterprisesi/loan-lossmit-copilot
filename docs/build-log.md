# Build log: where we stood in for someone else's work

Abhay's backend work often needs something Arindam (agents, LLM gateway, contract) or Amogh (frontend)
has not finished, or something outside the team (model access). When that happens we build against a
stand-in so nobody is blocked, and we write it down here so the stand-in is swapped for the real thing
and never mistaken for it. All data is synthetic.

**How to keep this log.** Add a row whenever a task uses a mock, a seed or a fake because a dependency
is not ready. Say what is real and what is not, where the stand-in lives, and exactly how to swap it.
When it is swapped, change the status to **Swapped** and add the PR; do not delete the row. Newest
dated entry goes first.

Status: **Open** (still a stand-in), **Planned** (will be a stand-in when the task is built),
**Swapped** (the real thing is in), **Decision** (not a stand-in; waiting on someone to decide).

## Waiting on Arindam

| # | Our task | What we need from him | Stand-in we use now | How to swap | Status |
|---|---|---|---|---|---|
| A1 | Classify and extract in the document pipeline (D3) | `app.llm.tasks.classify` and `extract` (merged, #1 and #7) **and a model provider that can be called**. No provider works through the app yet: Bedrock now answers for Sonnet 4.6 and Haiku 4.5 through bedrock-runtime, but the app's adapter calls the Mantle endpoint, which is still denied (see X1 and D4); Gemini on a free key is slow and failed 10 of 18 calls; OpenAI has no credit. | `PIPELINE_LLM=fake`: the rule-based `FakeClassifier` and `FakeExtractor` in `backend/app/services/fake_reader.py`. Every extraction run records `provider: fake`, so it is never taken for a model's. It does not read year-to-date per earnings line, so income uses its documented fallback (overtime 444.02 and bonus 228.74 from the current amount, not 444.41 and 228.34 from year to date). It cannot do the auto-detect of a mislabelled file (demo step 2) or switch providers (step 6). | Get one provider working (`python -m app.llm.smoke --provider all`), set `PIPELINE_LLM=auto`, re-read the demo documents with `make reset-demo` (without `--fake-reader`). Check Daniel's income gives 444.41 and 228.34. | Open |
| A2 | Hardship profile for demo step 5 (D5, read side) | `read_hardship_letter` and hardship@1 (merged, #9) **and a working provider** (A1). | A **seeded sample**: the Feature Design 7.8 reading in `backend/app/db/demo/angela_hardship_profile.json`, stored by `app/db/demo/hardship.py` as a run with `source: seeded_sample`. It is not a model's reading, but code still checks every quote against the letter's lines, so `verified` is real. A test keeps the file identical to Arindam's `angela_reply()`. | D6: a service calls `read_hardship_letter` and stores a new run with `source: model`. `GET .../hardship-assessment/latest` returns the newest run, so the seed becomes history. | Built (D6): `POST /hardship-assessment` runs `read_hardship_letter` and stores a `model` reading beside the sample; real readings still need A1 |
| A3 | Income analysis explanations (D4) | `income-explain@1` and `check_figures` (merged, #9) **and a working provider**. | Not wired. The result carries `explanations: []` and `explanations_note: "explanations not generated"` (`backend/app/api/schemas/income.py`). The flags themselves are computed in code and shown. | Call the explanation after the flags are stored, check it with `check_figures`, fill `explanations`. Needs A1. | Open |
| A4 | Contract entries for the endpoints we built (D4 and D5) | The contract has only TODO comments for income, the page image and hardship, and nothing for the completeness override or the `needs_review` values. | We built to the Feature Design paths and wrote the YAML for Arindam to paste into his own contract PR: `docs/contract-proposal-d4.md` (sections 1 and 2 from D4, 3 and 4 from D5). `contracts/` is not touched. Until it lands, Amogh's types for these cannot be generated from the contract. | Arindam merges the YAML; then compare the shapes with a contract-alignment test as done for completeness. The hardship POST, confirmations and budget YAML follow on D6. | Open |
| A5 | D6 assets analysis (Feature 3) | `label_transactions` (merged, #7) **and a working provider**. | **Built (D6, C4):** `backend/app/services/transaction_labels.py` has a `TransactionLabeller` protocol. `LlmLabeller` wraps `label_transactions` (a line still unlabelled after one retry becomes "other, needs review", as the Feature Design says). With `PIPELINE_LLM=fake`, `FakeLabeller` uses keyword rules instead: it reproduces every label in both generated scenarios (a test checks that) but has no judgement, so an unknown payee is just "other" and is never marked for review. | Same as A1: set `PIPELINE_LLM=auto` once a provider works and the run uses `LlmLabeller`. | Open (real labelling needs A1) |
| A6 | D6 HITL endpoints, read-side routers (reports, findings, agent runs) | The report, finding, condition and agent-run shapes in the contract (his D5 contract PR) and the agents themselves (D7 and D8). | **Built (D6, C6 and C7):** the endpoints and `services/report_writer.py` (the way his graph writes a report). A **seeded sample** fills them: Daniel's draft underwriting report with eight findings and six conditions (`app/db/demo/daniel_underwriting_report.json`), and Angela's waterfall, lender view and draft report (`angela_lm_recommendation.json`). Every response says `seeded_sample`, and so does the report, its agent runs and the run. The agent run log is hand-written, not an agent's. | D7 and D8: the same tables get real output through `report_writer`; the endpoints are unchanged. The waterfall and lender view now come from the rules engine (D7, C10, below); the seeded waterfall stays as history. | Open (D8: the agents' report) |
| A7 | D7 rules engine (Feature 8): "hardship resolved" and months delinquent | `hardship@1` has no `resolved` duration, and no document field carries months delinquent. | **Built (D7, C10):** "hardship resolved (confirmed)" is `not_met` once the duration is confirmed (it is `temporary`, `long_term` or `unknown`), with a note that a reviewer can override it with a reason. Months delinquent is read from `loan_records`, the simulated servicing record (`source: synthetic`, seeded from the scenario by `app/db/demo/loan_record.py` and `make reset-demo`). | Arindam adds `resolved` to the duration categories if he wants the rule to be able to meet; the statement's `payments_past_due` joins the mortgage statement schema if months should come from the document. | Open (decision) |
| A8 | D7 credit report analysis (Feature 4) | A `credit_report` extraction schema that emits the field names in `backend/config/document_fields.yaml` (scores, the full tradeline rows, inquiries, alerts). | **Built (D7, C11):** `services/credit.py` (pure), `credit_runs.py`, tables (migration 0009), `POST/GET /cases/{id}/credit-analysis`. It reads whatever fields the pipeline stored for the newest credit report; the golden and API tests seed Daniel's report as the reader would leave it. With `PIPELINE_LLM=fake` the rule-based reader does not read a credit report, so a live demo shows "Cannot compute" (`CR-I101`) and Feature 3 keeps the bank-only 658.00 and DTI 44.11%. | Arindam's `credit_report` schema emits the field names; re-read the report with `make reset-demo`. The annotation endpoint (`PATCH .../items/{item}`) is not built. | Open |

### Decisions and problems in Arindam's area (not stand-ins; we did not edit his folders)

| # | What | Why it matters | Status |
|---|---|---|---|
| D1 | `rag_chunks.embedding` is `vector(1024)` in the schema doc but `backend/config/llm.yaml` sets 1536 dimensions. | One embedding model is fixed per index. Needed before the D6 migration. | Decision |
| D2 | `llm_calls` was due on D2 and never built; the gateway only logs. | Build it in the D6 shared migration, or drop it and rely on the log. | Decision |
| D3 | A blank `AWS_PROFILE=` in `.env` (what `.env.example` produces) makes the Bedrock client fail with `ProfileNotFound: The config profile () could not be found`, before it reaches AWS. `app/storage.py` already strips blank AWS variables (`drop_blank_aws_env`); the LLM path does not. | `python -m app.llm.smoke --provider bedrock` cannot run until the line is removed from `.env`. Fix: call `drop_blank_aws_env()` before building the client. | Open |
| D4 | `BedrockClaudeAdapter` builds `AsyncAnthropicBedrockMantle` (`app/llm/adapters/anthropic.py`), and the AWS user is still denied `bedrock-mantle:CreateInference`. The SDK's runtime client (`AsyncAnthropicBedrock`, InvokeModel) works with the models the platform engineer named on 2026-11-23 (`global.anthropic.claude-sonnet-4-6`, and Haiku 4.5 under its full id `global.anthropic.claude-haiku-4-5-20251001-v1:0`; the short name is rejected). With that one client swapped in memory, the app's smoke, classify, extract, label, hardship and explain checks passed on both. | **Done in code, not yet committed (2026-11-23, at Abhay's request):** `BedrockClaudeAdapter` now builds the runtime client; its test is updated. Arindam's file, so he should review it. The app's own smoke checks then passed unpatched on Haiku 4.5 (all six) and Sonnet 4.6 (smoke, classify, label, hardship). Still to do: point the config at one of these models (Haiku 4.5 without `effort`, see D5), then set `PIPELINE_LLM=auto` so A1 to A3 can be swapped. | Swapped (uncommitted) |
| D5 | Haiku 4.5 rejects the `effort` option ("This model does not support the effort parameter"), and `llm.yaml` sends it for Bedrock and for several tasks. Sonnet 4.6 accepts it. | Any config that names Haiku 4.5 must leave `effort` out for it. | Decision |

## Waiting on Amogh

| # | Our task | What we need from him | Stand-in we use now | How to swap | Status |
|---|---|---|---|---|---|
| M1 | The frontend running against the real backend | `NEXT_PUBLIC_USE_MOCKS=false` and real calls in `frontend/src/lib/api.ts`. On main it defaults to mocks, and in real mode `getPageImage` answers "none" (a blank page). | His mock store (`frontend/src/mocks`). We checked the demo flow through the real API in a scratch walkthrough (login, documents, page image, CORS preflight, net-pay correction, income, hardship), not through the screens. | He calls `GET /cases/{id}/documents/{id}/pages/{n}` in `getPageImage` and maps `expires_at` to `expiresAt`; set mocks off; run `make reset-demo` for data. | Open |
| M2 | Income, completeness and hardship screens | Calls for them. `api.ts` on main has cases, documents, jobs, extraction, review, type change and page image only. His `feat/amogh/income-completeness` branch was not merged at last fetch, and we have not seen the hardship profile screen. | Our endpoints are built and tested (`income-analysis`, `completeness`, `hardship-assessment/latest`), and `make reset-demo` seeds Daniel's documents and Angela's profile so a screen has real data the moment it calls them. | He wires the calls; paths are in the README and `docs/contract-proposal-d4.md`. | Open |
| M3 | Login | A login screen and call. The backend `POST /api/v1/auth/login` exists; `api.ts` on main has no login call. | The seeded demo users (`underwriter`, `lm_specialist`, `admin`, password from `DEMO_PASSWORD`). | He adds the login screen and sends the bearer token on each request. | Open |

### What we have already done for Amogh

| What he asked for | Done | Where |
|---|---|---|
| CORS so the browser can call the API | 2026-11-23 | `CORS_ORIGINS`, `install_cors` in `backend/app/main.py` |
| A link to each page image | 2026-11-23 | `GET /cases/{id}/documents/{id}/pages/{n}` |
| The document endpoints on main | PR #10 merged | |
| Real or seeded data to build against | 2026-11-23 | `make reset-demo` |

## Outside the team

| # | What | State |
|---|---|---|
| X1 | AWS Bedrock access for the project's IAM user. Listing works. The models first named (Haiku 5.5, Opus 5.5) are denied on both paths and were later reported unavailable by the platform engineer, who named Sonnet 4.6 and Haiku 4.5 instead. Those two work through bedrock-runtime (checked 2026-11-23 08:00 UTC). The Mantle endpoint the app calls (`bedrock-mantle:CreateInference`) is still denied for every model. | Open. This is why A1 to A3 still use stand-ins: the app cannot use the working path until D4 is resolved. Re-run the check after any AWS change; Mantle may need more actions than the first one named. |

## Changes we made in other people's folders

CLAUDE.md rule 8: no one edits another owner's folder without being asked. Every time we do, it is
listed here with who asked, so the owner can review it.

| Owner | File | What changed | Asked by | Status |
|---|---|---|---|---|
| Arindam (`backend/app/llm`) | `backend/app/llm/adapters/anthropic.py` | `BedrockClaudeAdapter` builds the SDK's bedrock-runtime client (`AsyncAnthropicBedrock`) instead of the Mantle one (`AsyncAnthropicBedrockMantle`); docstring explains why. 14 lines added, 6 removed. See D4. | Abhay, 2026-11-23 | Uncommitted. Arindam to review. |
| Arindam's area (`backend/tests/llm`) | `backend/tests/llm/test_adapters.py` | The Mantle-client test became a runtime-client test, plus one test for the `AWS_DEFAULT_REGION` fallback. | Abhay, 2026-11-23 | Uncommitted. Arindam to review with the adapter. |
| Abhay (`backend/config`), about Arindam's LLM setup | `backend/config/llm.yaml` | Comment only: "Mantle endpoint" became "bedrock-runtime, InvokeModel". No model or option changed. | Abhay, 2026-11-23 | Uncommitted. |

Nothing has been changed in `backend/app/prompts`, `backend/app/rag`, `backend/app/agents` or
`contracts/`: contract changes are proposed as YAML in `docs/contract-proposal-d4.md` instead.
Nothing has been changed in Amogh's `frontend/`; main's version of it was merged in as it is.

## Entries

### 2026-11-24, D6 C6 to C8: review, guidelines, hardship reading and budget

- Built: condition review and sign-off (`services/review_conditions.py`), the waterfall override
  (`services/waterfall_status.py` is the one status rule the rules engine will share), the audit
  endpoint, read-only guideline routers, `services/report_writer.py`, the hardship reading job and
  confirmations (`services/hardship.py`), and the budget (`services/budget.py`, pure, and
  `budget_runs.py`). Golden tests: `tests/golden/test_budget_golden.py` against Angela's scenario.
- **Stand-ins (new):** (1) the seeded reports and waterfall above (A6); (2) **guideline passages**:
  eleven invented illustrative passages in `app/db/demo/guideline_passages.json`, behind a
  `PassageStore` protocol, until Arindam's index loads real ones (the guideline tables, migration
  0009, wait for his embedding size); (3) **passage IDs** are my provisional scheme
  (`sample-investor-a-v1.repayment-plan.1`, no `#` so they fit a URL path); (4) the hardship reading
  uses a `HardshipReader` protocol: the real one wraps `read_hardship_letter` (needs a working
  provider, A1), tests use a stub that returns his worked example.
- **Choices not in the Feature Design (flagged for review):** the observed amount of a budget line is
  the debits of the latest statement month that has one in that line, so housing 1,720.00 comes from
  July; a stated expense with no matching budget line rolls into "Other"; an adjustment replaces the
  observed amount on the observed basis and the statements' amount stays beside it; a hours-against-pay
  limit of 5 points (`pay_vs_hours_points`, illustrative) because the Feature Design shows the check
  without one; the confirmation is stored in the item's own JSON so no migration is needed; "add your
  own condition" is `POST .../conditions`; a sign-off with undecided conditions is allowed and reports
  how many were undecided; a change after a sign-off puts the report back in review, and the earlier
  sign-off stays.
- **Wording:** the Feature Design's final-terms line says "approved method"; rule 3 forbids the word,
  so it reads "the investor's own method".
- **Needs from others:** the application's expense, income and ticked-reason rows and the mortgage
  statement's `regular_monthly_payment` and `past_due_amount` must be emitted by Arindam's reader
  (field names in `docs/contract-proposal-d4.md` section 7). Until then the demo with the rule-based
  reader shows the budget as "cannot compute". The `thresholds.yaml` version was 2026-11-24.1 then (2026-11-24.2 after the credit settings).
- Contract YAML for all of it: `docs/contract-proposal-d4.md` sections 6 and 7. `contracts/` untouched.

### 2026-11-23, D6 C5: asset and liability run and API

- Built `services/asset_runs.py` (run, worker job, stored view, a person's changes, `what_if`),
  `api/routers/asset_liability.py` (`PUT` and `GET loan-scenario`, `POST asset-liability`, `GET
  .../latest`, `PATCH` a transaction, `PATCH` an obligation) and `tests/db/test_asset_api.py`.
- A change recalculates at once with no model call, keeps the system's answer (`original_category`,
  `original_counts_toward_dti`), and writes an audit event with the reason. A person's include or
  exclude of a debt is carried into later runs by creditor name.
- Choices not in the Feature Design (flagged for review): the two PATCH paths; the pay-date
  projection uses the middle of the configured frequency range (14 days for biweekly); labels belong
  to the statement line, so a new run never relabels a line a person changed.
- Stand-ins unchanged: the fake labeller (A5) and the seeded credit-report tradelines in tests (the
  live demo shows 658.00 and DTI 44.11% until the `credit_report` schema lands).
- The integration test found the fake labeller naming the rent payee "Oakmont Apartments Rent"; its
  payee rules now drop "rent", so the debt matches the credit report's name.
- Contract YAML for all of it is in `docs/contract-proposal-d4.md` section 5; `contracts/` untouched.

### 2026-11-23, D6 C4: asset analysis core

- Built `services/assets.py` (pure: payroll match, large deposits, recurring debts, credit-report
  reconciliation, assets, shortfall, front-end ratio, DTI, LTV, what-if), `services/loan_scenarios.py`
  and `services/transaction_labels.py`, with golden tests against Daniel's scenario `expected` block.
- Stand-in: the fake labeller (A5). Daniel's golden obligations of 693.00 need the credit-report
  tradelines; the golden test seeds them from the scenario, and a live demo shows bank-only 658.00
  until Arindam's `credit_report` schema lands.

### 2026-11-23, later: Bedrock re-checked with the models the platform engineer named

- Sonnet 4.6 and Haiku 4.5 (full id) answer through bedrock-runtime. Mantle is still denied (X1, D4).
- Trial with the adapter's client swapped in memory only, no repo file edited: on both models the
  smoke, classify, extract, label, hardship and explain checks ran. Haiku 4.5 needs `effort` left
  out (D5) and then passed all six, extract in 4.5 s; Sonnet 4.6 passed five and its explain check
  reported "unverified figure" (the figure guardrail doing its job), and its extract took 126 s.
- Not swapped in yet: A1 to A3 stay Open until the adapter question (D4) is settled.
- The platform engineer's follow-up said to use the complete Haiku id
  `global.anthropic.claude-haiku-4-5-20251001-v1:0`. That is the id already in use and it works on
  bedrock-runtime (checked 08:24 UTC); on Mantle it is still denied. So it confirms the working id
  but does not unblock Mantle.
- Adapter changed at Abhay's request (D4), so this is now the path the app uses. This edited a file in
  Arindam's folder; see "Changes we made in other people's folders".

### 2026-11-23 (D5 tasks, branch `feat/abhay/frontend-unblock`)

- Built CORS, the page-image link, the `hardship_profiles` table (migration 0006) with the read side
  and Angela's seeded profile, `make reset-demo`, and Tesseract OCR. Added tests for the whole broken
  set. Merged main (PR #10 and Amogh's #8) before committing.
- Stand-ins created: A1 (fake reader for the demo), A2 (seeded hardship profile), A3 (explanations
  not generated, unchanged), A4 (contract YAML proposed, not merged).
- Found: the demo with the fake reader shows overtime 444.02 and bonus 228.74, not 444.41 and 228.34
  (see A1). Not a bug; the fake reader has no year-to-date per line.
- Found: the Bedrock smoke command fails on a blank `AWS_PROFILE=` before reaching AWS (D3), and
  Bedrock itself refuses invocation (X1).
- Not run through the screens: the demo flow was checked through the real API in a scratch walkthrough
  with the fake reader and in-memory S3, because the frontend is still on mocks (M1).

### 2026-11-24, D7 C10: rules engine, lender view, recommendation endpoints

- Built `config/rule_sets/sample_investor_a_v1.yaml` (version 1, `illustrative`, every setting labelled
  with its source, numbers as quoted strings so they stay exact), `services/rules_config.py`,
  `services/rules_engine.py` (pure) and `services/recommendation_runs.py`. `POST
  /cases/{id}/lm-recommendation` queues a job; the worker applies the rules (no model) and stores a
  new `lm_recommendation` run: the waterfall, the lender view and every figure with its working.
  `run_recommendation_rules(session, case_id)` is the function for Arindam's graph step 4.
- Golden (`tests/golden/test_rules_golden.py`, from the scenario `expected` block): repayment plan,
  forbearance and deferral not met, modification met (target payment 1,470.00 below 1,720.00), short
  sale and deed-in-lieu not reached; claim 217,560.00, net recovery 201,250.00, loss 16,310.00,
  modification cost 13,893.00, advantage 2,417.00. Changing a setting changes the result (a test).
- Rules read the hardship duration and intent only once a person confirmed them; otherwise the
  condition is `needs_confirmation`. The "no earlier option met" condition now waits (needs
  confirmation or not evaluable) while an earlier option is undecided, instead of reading as met.
- Overrides carry to a new run by condition id with the rules' status beside them; one the rules have
  caught up with is dropped. Sign-off of the recommendation needs a report on the newest run (409
  `no_report`), because the rules alone write none and an older run's report would not describe the
  waterfall on screen. A rules-only report would need a new `reports.source` value (a migration).
- Stand-ins: see A7. Angela's simulated loan record is new demo data (`loan_records`, synthetic).

### 2026-11-24, D7 C11: credit report analysis (Feature 4 kept)

- No decision to cut Feature 4 was recorded, and cutting it costs Daniel's 44.70% demo, so it is
  built (the schema doc and the plan call it P1). Say if it should be cut instead; the code is
  self-contained (migration 0009, `credit.py`, `credit_runs.py`, one router).
- Built `services/credit.py` (representative score, utilization per account and in total, late
  payments by severity and the months since the last, inquiry matching, derogatory list, payments by
  account type, flags and a template summary), migration 0009 (`credit_scores`, `tradelines`,
  `credit_inquiries`), `credit_runs.py`, `POST/GET /cases/{id}/credit-analysis`, and the settings in
  `thresholds.yaml` (version 2026-11-24.2: lookback 24 months, inquiry window 120 days, match within
  30 days, utilization review level 30%).
- Golden (`tests/golden/test_credit_golden.py`, from the scenario `expected` block): representative
  score 705, Northgate 36.75%, total revolving 28.00%, one 30-day late payment 19 months before the
  report, payments 693.00, Harbor Retail matched and Orion Mortgage unmatched.
- Stand-in: see A8. The credit report's fields beyond the tradeline creditor, type, balance, limit and
  payment are new names that Arindam's schema must emit.
