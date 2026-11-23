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
| A1 | Classify and extract in the document pipeline (D3) | `app.llm.tasks.classify` and `extract` (merged, #1 and #7) **and a model provider that can be called**. No provider works yet: Bedrock returns 403 (the IAM user has no permission to invoke; see X1), Gemini on a free key is slow and failed 10 of 18 calls, OpenAI has no credit. | `PIPELINE_LLM=fake`: the rule-based `FakeClassifier` and `FakeExtractor` in `backend/app/services/fake_reader.py`. Every extraction run records `provider: fake`, so it is never taken for a model's. It does not read year-to-date per earnings line, so income uses its documented fallback (overtime 444.02 and bonus 228.74 from the current amount, not 444.41 and 228.34 from year to date). It cannot do the auto-detect of a mislabelled file (demo step 2) or switch providers (step 6). | Get one provider working (`python -m app.llm.smoke --provider all`), set `PIPELINE_LLM=auto`, re-read the demo documents with `make reset-demo` (without `--fake-reader`). Check Daniel's income gives 444.41 and 228.34. | Open |
| A2 | Hardship profile for demo step 5 (D5, read side) | `read_hardship_letter` and hardship@1 (merged, #9) **and a working provider** (A1). | A **seeded sample**: the Feature Design 7.8 reading in `backend/app/db/demo/angela_hardship_profile.json`, stored by `app/db/demo/hardship.py` as a run with `source: seeded_sample`. It is not a model's reading, but code still checks every quote against the letter's lines, so `verified` is real. A test keeps the file identical to Arindam's `angela_reply()`. | D6: a service calls `read_hardship_letter` and stores a new run with `source: model`. `GET .../hardship-assessment/latest` returns the newest run, so the seed becomes history. | Open (D6) |
| A3 | Income analysis explanations (D4) | `income-explain@1` and `check_figures` (merged, #9) **and a working provider**. | Not wired. The result carries `explanations: []` and `explanations_note: "explanations not generated"` (`backend/app/api/schemas/income.py`). The flags themselves are computed in code and shown. | Call the explanation after the flags are stored, check it with `check_figures`, fill `explanations`. Needs A1. | Open |
| A4 | Contract entries for the endpoints we built (D4 and D5) | The contract has only TODO comments for income, the page image and hardship, and nothing for the completeness override or the `needs_review` values. | We built to the Feature Design paths and wrote the YAML for Arindam to paste into his own contract PR: `docs/contract-proposal-d4.md` (sections 1 and 2 from D4, 3 and 4 from D5). `contracts/` is not touched. Until it lands, Amogh's types for these cannot be generated from the contract. | Arindam merges the YAML; then compare the shapes with a contract-alignment test as done for completeness. The hardship POST, confirmations and budget YAML follow on D6. | Open |
| A5 | D6 assets analysis (Feature 3) | `label_transactions` (merged, #7) **and a working provider**. | Planned: a line still unlabelled after one retry becomes "other, needs review", as the Feature Design says. | Same as A1. | Planned |
| A6 | D6 HITL endpoints, read-side routers (reports, findings, agent runs) | The report, finding, condition and agent-run shapes in the contract (his D5 contract PR) and the agents themselves (D7). | Planned: endpoints built on seeded data (a draft report for Daniel, a waterfall result for Angela), in the merged contract shapes. | D7 and D8: the same endpoints return real agent output; run the HITL flow end to end on it. | Planned |

### Decisions and problems in Arindam's area (not stand-ins; we did not edit his folders)

| # | What | Why it matters | Status |
|---|---|---|---|
| D1 | `rag_chunks.embedding` is `vector(1024)` in the schema doc but `backend/config/llm.yaml` sets 1536 dimensions. | One embedding model is fixed per index. Needed before the D6 migration. | Decision |
| D2 | `llm_calls` was due on D2 and never built; the gateway only logs. | Build it in the D6 shared migration, or drop it and rely on the log. | Decision |
| D3 | A blank `AWS_PROFILE=` in `.env` (what `.env.example` produces) makes the Bedrock client fail with `ProfileNotFound: The config profile () could not be found`, before it reaches AWS. `app/storage.py` already strips blank AWS variables (`drop_blank_aws_env`); the LLM path does not. | `python -m app.llm.smoke --provider bedrock` cannot run until the line is removed from `.env`. Fix: call `drop_blank_aws_env()` before building the client. | Open |

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
| X1 | AWS Bedrock access for the project's IAM user. Listing models and inference profiles works, but invoking a Claude model returns 403: `bedrock-mantle:CreateInference` (the endpoint the app calls) and `bedrock:InvokeModel` are not allowed, and the plain model id says "not available for this account". | Checked 2026-11-23 and the exact errors collected; a message for the AWS account handler is drafted. Update this row when it is sent and when they reply. This is why A1 to A3 use stand-ins. Re-run the check after they reply; Mantle may need more actions than the first one named. |

## Entries

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
