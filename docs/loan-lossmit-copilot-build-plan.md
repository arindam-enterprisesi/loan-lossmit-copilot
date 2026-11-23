# Loan Processing and Mortgage Loss Mitigation Copilot — 2-Week Team Build Plan

Nov 16, 2026 · @Someone

## Summary

We ship a working demo of the Loan Processing and Mortgage Loss Mitigation Copilot (both pillars) in 10 working days, with a management review build at the end of Day 5. Three people build it with Claude: Amogh on the frontend, Abhay on data and backend services, Arindam on the agentic backend and as reviewer and merger of every PR.

| Milestone | Date | What management sees |
|---|---|---|
| Kickoff | Mon 16 Nov | Repo, contracts and owners in place |
| v0.5 management review | Fri 20 Nov, 4:00 pm IST | Documents uploaded, read and checked; income analysis with visible working; hardship letter read into a profile; LLM provider switched live |
| Feature freeze | Thu 26 Nov, 6:00 pm IST | All P0 features merged to main |
| v1.0 release candidate | Fri 27 Nov | Both pillars end to end, with the three agents and human sign-off |
| Final delivery | Mon 30 Nov | Final demo, runbook and handover |

The build follows the AI Mortgage Copilot Feature Design (2 Nov 2026) and the two PRDs. Its four rules hold everywhere: code does all arithmetic, every finding links to its evidence, people make every decision, and no threshold is invented (every setting is configuration labelled illustrative or authoritative). All data is synthetic.

The two demo stories carry the whole plan: Daniel Reyes (Pillar 1, new loan) and Angela Whitfield (Pillar 2, hardship). Their figures in the Feature Design become our golden tests.

## Scope for two weeks

Two weeks buys a thin, end-to-end demo of both pillars on the two demo stories, not the full feature set. The Tavant effort workbook puts the Loss Mitigation POC alone at a 1,116-hour baseline (about 8 weeks for 4 people). We have about 240 hours (3 people × 10 days × 8 hours), so we build every feature only as deep as the demo stories need, and defer the rest.

| Feature (Feature Design #) | Pillar | Priority | Done for v0.5 (Fri 20) | Done for v1.0 (Fri 27) |
|---|---|---|---|---|
| 1 Document Intelligence: upload, classify, extract, validate, review | Both | P0 | Yes, 8 doc types | Plus broken-file handling |
| 1 Completeness checklist | Both | P0 | Basic | Override with reason |
| 2 Income Analysis | 1 | P0 | Yes, with Show working | Include or exclude with reason |
| 7 Hardship and Financial Assessment | 2 | P0 | Letter profile with verified quotes | Budget on both bases |
| 3 Asset and Liability Analysis | 1 | P0 | No | Yes |
| 5 Guideline and Regulation Assistant (RAG) | Both | P0 | No | Yes, cited answers |
| 6 Underwriting Copilot (3 agents) | 1 | P0 | No | Yes |
| 8 Loss Mitigation Recommendation (waterfall, lender view, 3 agents) | 2 | P0 | No | Yes |
| HITL: confirm, correct, override, sign-off; audit log | Both | P0 | Field corrections | All actions |
| 4 Credit Report Analysis | 1 | P1 | No | Kept or cut at the end of D6; if kept, built on D7 and run on D8 if time allows |
| 9 Case Summary and Communication drafts | 2 | P2 | No | Deferred |

**Deferred to Phase 2:** multi-tenant Row-Level Security, AWS deployment (ECS, SQS, Cognito), the OCR provider bake-off, handwriting and poor scans, FHA or a second investor, scheduled runs, UI polish beyond the demo screens.

**Never built:** approving, denying or offering anything; sending letters; real borrower data; live bureau, bank, DU or LPA connections.

## Architecture and stack

One Next.js app, one FastAPI API, one Python worker and one PostgreSQL database, all started with a single `docker compose up`. The backend is split into service modules (the Feature Design's CPS-01 to CPS-11) with clean interfaces, so any of them can become its own deployable service later without rewriting it. Separate network services would cost us days of plumbing we don't have.

The API and the worker reach a model only through the gateway, so switching provider is a config change.

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js 15, TypeScript, Tailwind, shadcn/ui; screens designed first in Claude Design | Matches the Feature Design; Claude Code writes it well |
| API | FastAPI, Python 3.12, Pydantic v2, SQLAlchemy 2, Alembic | Already our stack; OpenAPI comes for free |
| Background jobs | arq worker on Redis (extraction, analysis and agent runs) | Long jobs never block the API; the UI polls status |
| Database | PostgreSQL 16 with pgvector | One store for data, vectors and audit; replaces a separate ChromaDB |
| File storage | Amazon S3, one shared bucket on our AWS account, a prefix per developer and one for the demo | Same storage as production would use; page images served by 5-minute presigned links |
| Reading PDFs | pypdfium2 page images plus the PDF text layer first; Tesseract OCR (open source, runs locally) for pages with no text layer; numbered lines with boxes either way | Free, and document text never leaves our machine; behind an OCR interface so Mistral OCR or Document AI can replace it later |
| Agents | LangGraph: Researcher, Writer, Critic with typed shared state | As designed for Features 6 and 8 |
| LLM providers | One LLM Gateway with four adapters: Bedrock (Claude), Claude API, Google Gemini, OpenAI | Provider and model chosen per task in config, no code change |
| Auth | Seeded JWT with three demo roles (processor/underwriter, LM specialist, admin) | Cognito later, same claims |
| Quality | ruff, mypy, pytest; eslint, tsc; GitHub Actions on every PR | Gate for merging |

**LLM Gateway rules (Arindam owns).** Every AI call goes through `app/llm/gateway.py`: a named, versioned prompt (for example `extract-paystub@1`), a Pydantic output schema, temperature 0, one retry on schema failure, and a log of provider, model, tokens and latency. Provider and model per task live in `config/llm.yaml`, for example `classify: gemini`, `agents.writer: bedrock-claude`. The gateway uses LangChain chat-model integrations (`langchain-aws`, `langchain-anthropic`, `langchain-google-genai`, `langchain-openai`) with structured output. The embedding model is fixed per index and recorded on every vector row, because vectors from two models can't be mixed.

**Contract first.** `contracts/openapi.yaml` and the shared Pydantic schemas are the source of truth. Amogh generates TypeScript types from them and builds against mocks until each endpoint is real. Only Arindam merges contract changes.

**Database.** 34 tables in five groups, each with its owner and the day its migration is due: see the *Database schema* document.

## Who owns what

Each person owns whole modules, so PRs rarely touch the same files. Abhay owns everything deterministic (data, files, calculations, rules); Arindam owns everything that calls a model; Amogh owns everything the user sees.

| Owner | Owns (Feature Design service) | Folders |
|---|---|---|
| Arindam: agentic backend, tech lead, PR reviewer | LLM Gateway (CPS-02), Schema Registry and extraction prompts (CPS-03), RAG Service (CPS-06), Agent Layer (CPS-07), agent narrative in Report Builder (CPS-10), guardrails, evaluation | `backend/app/llm`, `backend/app/agents`, `backend/app/rag`, `backend/app/prompts`, `contracts/` |
| Abhay: data and backend services | Ingestion (CPS-01), Calculations (CPS-04), Rules and Config (CPS-05), Evidence Model (CPS-08), Human Review (CPS-09), Audit Store (CPS-11); DB schema, migrations, auth, jobs, REST endpoints, synthetic data generator | `backend/app/db`, `backend/app/services`, `backend/app/api`, `backend/config`, `data/` |
| Amogh: frontend | All screens in Claude Design then Next.js: app shell, Document Intelligence, Income, Assets and Liabilities, Credit, Guideline assistant, Underwriting copilot, Hardship and budget, Recommendation, HITL actions, Settings (LLM provider) | `frontend/` |

**Hand-offs that matter.** Arindam's LLM calls return Pydantic objects; Abhay's code checks them (value appears in the cited line, arithmetic, page counts) and stores them. Abhay's calculations return a value plus its working; Arindam's agents only read stored results and never compute. Amogh never calls a model directly; everything goes through the API. To let Abhay build the HITL and credit endpoints before the agents exist, Arindam opens one contract PR at the end of D5 for Features 4, 6 and 8, the HITL actions and the audit view, including the report, finding, condition and agent-run shapes. Abhay opens the table migration on the morning of D6, and both merge in the 1:00 pm window that day. Abhay builds the HITL endpoints against seeded conditions on D6 and D7. Three groups of routers belong to nobody else in this plan, so they are split here: Abhay builds the read side on D6 and D7 on seeded data (reports, findings and agent runs; guideline passages and sources), and Arindam writes the endpoints that start a model run (guideline question, run or re-run an agent) himself. For those new router files only, Arindam may edit `backend/app/api` from D7; this paragraph is the written permission. From D8, Arindam checks the HITL endpoints end to end on real agent output and may edit Abhay's folders to fix them.

## Repo and PR workflow

One monorepo, `main` protected, and every change lands through a PR that Arindam reviews and squash-merges.

```
loan-lossmit-copilot/
  CLAUDE.md                 # rules every Claude Code session reads first
  docker-compose.yml        # web, api, worker, postgres+pgvector, redis (files go to S3)
  contracts/openapi.yaml    # API contract (Arindam merges changes)
  docs/                     # Feature Design, PRDs, FSDs, ADRs, demo scripts
  frontend/                 # Next.js app (Amogh)
  backend/
    app/api/                # FastAPI routers, one per feature (Abhay)
    app/services/           # ingestion, calculations, rules, evidence, review, audit, report (Abhay)
    app/db/                 # SQLAlchemy models + Alembic migrations (Abhay)
    app/llm/                # gateway + 4 provider adapters (Arindam)
    app/prompts/            # versioned prompts + output schemas (Arindam)
    app/rag/                # chunking, embeddings, hybrid search, citation checks (Arindam)
    app/agents/             # LangGraph graphs: underwriting, loss_mitigation (Arindam)
    app/worker.py           # arq jobs
    config/                 # checklists, income method, thresholds, rule sets, llm.yaml
    tests/golden/           # Daniel Reyes + Angela Whitfield expected figures
  data/synthetic/           # scenario JSON + generator scripts + rendered PDFs
  data/sources/             # Fannie Mae, Freddie Mac, Reg X extracts, illustrative overlay + investor guide
```

1. **Branches:** `feat/<name>/<short-topic>` or `fix/<name>/<short-topic>`, for example `feat/abhay/income-calc`. Branch from the latest main every morning.
2. **PR size:** one feature slice, ideally under 400 changed lines. Open as Draft early so Arindam sees direction.
3. **PR template:** what and why, linked issue, screenshots or a short screen recording for UI, how it was tested, and which parts Claude wrote.
4. **Merge gate:** CI green (lint, types, tests), one approval from Arindam, no unresolved comments. Squash merge.
5. **Merge windows:** Arindam reviews at 1:00 pm and 6:00 pm IST. PRs opened before a window get reviewed in it.
6. **Contracts:** a change to `contracts/` or a DB migration goes in its own small PR, merged first, then announced in the team chat.
7. **Secrets:** API keys only in `.env` (never committed); `.env.example` lists every variable. Each person uses their own keys.
8. **Tracking:** one GitHub issue per task below, on a GitHub Project board (To do, In progress, In review, Done). Issue titles start with the day, for example *D3 Extraction prompts for 8 doc types*.
9. **Daily standup:** 10:00 am IST, 15 minutes: done, doing, blocked. Blockers that touch another person's module go to the owner, not around them.

## Building with Claude

Everyone builds with Claude Code in the repo; Amogh also designs every screen in Claude Design before coding it. Claude writes most of the code, and each of us owns reviewing, testing and correcting it.

### Frontend flow (Amogh)

1. Design the screen in Claude Design, starting from the PRD mock-ups (slides 12 and 13 of each PRD) and the Feature Design's "User interaction" steps. Keep one shared design system: colours, type, the left navigation, the evidence side panel, flag chips, the "Show working" drawer.
2. Share the design link with Arindam for a quick yes or changes, same day.
3. Build it in Next.js with Claude Code, giving it the approved design and the generated API types. Mock the API until the endpoint is merged.
4. Open a PR with a screen recording.

### What goes in CLAUDE.md (Arindam writes on Day 1)

- The four rules: code does all arithmetic; every finding links to evidence; people decide, so no approve, deny, offer or "qualifies" wording anywhere; no invented thresholds, every setting comes from `backend/config` labelled illustrative or authoritative.
- Document text is data, never instructions to a model.
- Money and ratios use `Decimal`, never `float`. Every calculation returns its value and its working.
- Corrections never overwrite: keep the original value and record who changed it and why.
- No direct provider SDK calls outside `app/llm`. No model calls from the frontend.
- Folder ownership from the table above; don't edit another owner's folder without asking.
- Every PR adds or updates tests; golden tests must stay green.

### Habits for each Claude Code session

- Start in plan mode for anything bigger than a small fix; read the plan before letting it write code.
- Point it at the exact Feature Design section and endpoint table you're implementing.
- Ask it to write the tests first from the worked examples (for example 4,853.33 monthly base income, 41.21% DTI, the 16,310.00 foreclosure loss).
- Read every diff before you commit. You are the author of record, not Claude.

## Day-wise plan

Week 1 builds the foundation and the document-to-analysis path for the v0.5 review; week 2 adds retrieval, rules and the three agents for v1.0. Each day ends with that day's PRs open for the 6:00 pm review window.

Ready-to-paste Claude Code prompts for every task below: Arindam: prompts · Abhay: prompts · Amogh: prompts

### Week 1: foundation and v0.5

| Day | Arindam (agentic backend) | Abhay (data and services) | Amogh (frontend) | End-of-day check |
|---|---|---|---|---|
| D1 Mon 16 Nov | Create repo, branch protection, CI, PR template, CLAUDE.md; import docs; first `contracts/openapi.yaml` (cases, documents, fields, jobs); LLM Gateway interface + one provider working | docker-compose (Postgres+pgvector, Redis); S3 storage wrapper on the shared bucket; FastAPI skeleton, Alembic; models for cases, documents, pages, lines, fields; seeded JWT login with 3 roles | Claude Design: design system + app shell with left nav for both copilots, dashboard, case list; Next.js + Tailwind + shadcn scaffold | `docker compose up` runs; everyone has pushed one PR |
| D2 Tue 17 Nov | All 4 provider adapters (Bedrock Claude, Claude API, Gemini, OpenAI) with structured output, retry, call log; `config/llm.yaml`; classify prompt | Synthetic data: scenario JSON for Daniel Reyes and Angela Whitfield, generator rendering their ~16 PDFs; upload endpoint to S3, page images, text-layer lines with boxes | Claude Design: Document Intelligence (upload, review with document beside fields, case overview); login, case list built against mocks; TS types from OpenAPI | Same prompt returns valid output on all 4 providers; demo PDFs generated |
| D3 Wed 18 Nov | Extraction schemas + prompts for 8 doc types; classify-then-extract job; transaction labelling prompt (Feature 3) | arq worker and job status; code checks: value in cited line, earnings and net-pay arithmetic, page counts; PATCH field keeps original; audit table | Upload screen with status polling; review screen: page image, field list, click field to highlight its box, confirm or correct | A Daniel Reyes pay stub goes upload to reviewed fields |
| D4 Thu 19 Nov | Hardship letter prompt with quote and line IDs (Feature 7); quote verification hook; income explanation prompt (Feature 2) | Income calculations with working + golden tests (4,853.33 sample; 5,980.00 Daniel); completeness checklist from config; config loader with labels | Income Analysis screen with Show working and flags; completeness screen; Claude Design for Hardship and budget | Income tab shows Daniel's figures from real data |
| D5 Fri 20 Nov | Morning: integration and fixes. 1:00 pm code freeze, tag v0.5. Rehearse, then run the 4:00 pm management demo; log feedback as issues. After the demo: open the contract PR for Features 4, 6 and 8, the HITL actions and the audit view, with the report, finding, condition and agent-run shapes (Abhay reviews) | Fix integration bugs; reset-and-seed script for a clean demo. After the freeze: Tesseract OCR behind the OCR interface; broken-file handling and tests with the generated broken set (password, corrupt, duplicate, unsupported) | Hardship profile screen (letter beside profile, quotes highlighted); demo polish on the 4 shown screens | v0.5 demo done; feedback triaged; contract PR open |

### Week 2: agents, rules and v1.0

| Day | Arindam (agentic backend) | Abhay (data and services) | Amogh (frontend) | End-of-day check |
|---|---|---|---|---|
| D6 Mon 23 Nov | Merge the contract PR first. Triage review feedback (10:30 am). RAG: load Fannie Mae, Freddie Mac and Reg X extracts plus illustrative overlay and investor guide; section chunking, embeddings in pgvector, hybrid search; cited answers with citation check (Feature 5) | Table migration first (own PR, merged first): reports, findings, agent_runs, waterfall_results, lender_views, conditions, sign_offs. Then in this order, because Arindam's D7 graph needs DTI: (1) assets and liabilities: payroll match, large deposits, recurring debts, funds to close, DTI, LTV + golden tests (Feature 3); (2) HITL endpoints on seeded data: condition accept/edit/reject, condition override with reason, sign-off, audit view; (3) read-side routers on seeded data: reports, findings, agent runs, guideline passages and sources; (4) hardship budget on both bases (Feature 7), last, and the first thing on D7 if it slips. End of D6: decide whether Feature 4 stays or is cut | Assets and Liabilities screen (summary strip, transactions with category chips, obligations include or exclude); Hardship budget tab | Guideline question returns a cited answer; Daniel's DTI = 44.70%; HITL endpoints answer on seeded data; Feature 4 kept or cut |
| D7 Tue 24 Nov | Underwriting graph in LangGraph: findings from code, then Researcher, Writer, Critic (one loop back); typed state, run log, per-agent status; re-run one agent; writes agent_runs, reports, findings and conditions in the merged shapes; credit report extraction schema and prompt (Feature 4, only if kept at the end of D6), registered in the schema registry | Loss-mitigation rule engine: waterfall from versioned YAML (Sample Investor A), target payment, lender view + golden tests (16,310.00 loss, 2,417.00 advantage); only if Feature 4 is kept at the end of D6: credit tables migration (own PR, merged first); credit analysis in code with golden tests (representative score 705, Northgate utilization 36.75%, total revolving 28.00%, monthly payments 693.00); POST and GET credit-analysis; API integration tests for every endpoint built so far; README one-command setup; every PR open by 1:00 pm so review comments are fixed before the 6:00 pm window; all work merged by the 6:00 pm window | Guideline assistant: chat, citation markers opening passages, "no supporting passage" state; Claude Design for Underwriting copilot and Recommendation | Daniel's draft report generated end to end; all of Abhay's D8 and D9 work merged |
| D8 Wed 25 Nov | Loss-mitigation graph reusing the 3 agents with Pillar 2 tools; code guardrails: blocked decision words, every figure equals a stored result, every citation resolves; run the HITL endpoints end to end on real agent output (conditions from the underwriting graph through accept, edit, reject, override and sign-off) and fix issues in Abhay's HITL code; credit report: run Daniel's sample report through the pipeline and credit analysis and store the results (if time) | Out of office; D8 and D9 work done by D7 | Underwriting copilot screen (agent progress, findings by priority, conditions with accept/edit/reject, sign-off) | Angela's waterfall shows modification Met; Daniel's conditions can be accepted, edited and rejected on real agent output |
| D9 Thu 26 Nov | Evaluation: both stories on all 4 providers; prompt-injection document test; provider comparison table; fix failures. 6:00 pm feature freeze. API integration tests for the agent endpoints (reports, agent runs, conditions, sign-off); add the LLM-provider steps to the README one-command setup and run it on a clean machine with the agents | Out of office; D8 and D9 work done by D7 | Recommendation screen (waterfall cards, lender view, override, sign-off); Settings: LLM provider per task; loading, empty and error states | All P0 rows in Scope are merged |
| D10 Fri 27 Nov | Tag v1.0-rc; final demo script; record a backup demo video; architecture note in `docs/` | Bug fixes only; data reset verified on a clean machine; review the changes made in the API, services and database folders on D8 and D9 | Bug fixes only; visual pass across all screens | Clean-machine run of both stories passes |
| D11 Mon 30 Nov | Final demo to management; handover | Runbook walkthrough | Demo driver for the UI | Final delivery |

### Abhay's hand-over by end of D7 (out of office Wed 25 and Thu 26 Nov)

Everything below is merged to main by the 6:00 pm window on D7 with CI green. Arindam's and Amogh's D8 and D9 work reads from it, so nothing on those days waits on Abhay. Anything not finished goes into a GitHub issue by 6:00 pm on D7 that says what is missing, so nobody finds a gap on D8.

| Delivered | What it is | Who uses it, and when |
|---|---|---|
| Income analysis and completeness | Done on D4: stored income results with working; completeness with override | Underwriting graph reads the stored results (D7); Amogh's Income screen |
| Assets and liabilities, DTI, LTV | Feature 3 service, endpoints and golden tests (D6) | Underwriting graph (D7); Amogh's Assets and Liabilities screen |
| Table migration | reports, findings, agent_runs, waterfall_results, lender_views, conditions, sign_offs (D6) | Arindam writes agent output to them from D7 |
| HITL endpoints | Condition accept, edit, reject; condition override with reason; sign-off; audit view, on seeded data (D6 and D7) | Arindam's end-to-end check on real agent output (D8); Amogh's Underwriting screen (D8) |
| Read-side routers | GET reports, findings and agent runs; GET guideline passages and sources | Amogh's Guideline assistant, citations opening passages (D7); Underwriting screen (D8) |
| Hardship budget on both bases | Feature 7 service and endpoints with golden tests (D6, or the morning of D7 if late) | Loss-mitigation graph (D8); Amogh's Hardship budget tab |
| Loss-mitigation waterfall and lender view | Rule engine from versioned YAML with golden tests: 16,310.00 loss, 2,417.00 advantage (D7) | Loss-mitigation graph (D8); Amogh's Recommendation screen (D9) |
| Credit analysis, only if Feature 4 is kept | Credit tables migration, calculations, POST and GET credit-analysis (D7) | Arindam's credit report run (D8, if time) |
| Tests and README | API integration tests for every endpoint built so far; README one-command setup (D7) | Everyone; Arindam adds the LLM-provider steps on D9 |

While Abhay is out, Arindam fixes bugs in Abhay's folders himself; on D10 Abhay reviews those changes.

## Demos, done criteria and risks

### v0.5 demo script (Fri 20 Nov, about 15 minutes)

1. Log in as underwriter; open case for Daniel Reyes; upload his documents with type on Auto-detect.
2. Show a bank statement uploaded as a tax return being recognised and switched.
3. Open the pay stub: the code check flags net pay 2,083.61 (gross 3,070.50 minus deductions 1,036.89 is 2,033.61); correct it and show the original is kept.
4. Run income analysis: base pay 5,980.00 a month, overtime and bonus excluded with the reason, Show working.
5. Switch to Angela Whitfield: hardship letter read into reason, onset, duration and intent, each quote highlighted on its line.
6. Change the classify task's provider in config (for example Gemini to Bedrock Claude) and re-run to show provider flexibility.

### v1.0 demo adds

- **Daniel:** DTI 44.70% (41.61% if overtime counted), cited guideline answer on overtime, three agents drafting the report, underwriter accepts five conditions, rejects one with a reason, signs off.
- **Angela:** budget deficit 70.00 stated versus 280.00 observed, waterfall with modification Met, lender view (2,417.00 cheaper than foreclosure), Reg X citation on the missing statement, sign-off that is not a decision.

### Definition of done for any task

- Merged to main through a reviewed PR with CI green.
- Tests added; golden figures from the Feature Design pass to the cent.
- No arithmetic in prompts or agent output; no decision words; every shown figure traces to evidence or a stored calculation.
- Works from a fresh `docker compose up` with the seed script.

### Risks

| Risk | Effect | What we do |
|---|---|---|
| Scope is about 4 times our capacity per the effort workbook | Late or shallow features | Hold the P0/P1/P2 cut; build only what the two stories need; cut Feature 4 before anything P0 |
| Arindam is both builder and only reviewer | PRs queue up and block Abhay and Amogh | Two fixed review windows; small PRs; Arindam's own PRs reviewed by Abhay |
| Provider access (Bedrock model access, API keys) not ready | Gateway work stalls on Day 2 | Request Bedrock model access and all four keys today; build against whichever works first |
| Agent output varies between providers | Flaky demo | Temperature 0, schema checks, code guardrails, recorded backup video, default to the provider that passes evaluation |
| Synthetic PDFs too clean or too messy | Extraction looks fake or fails | Generate from one scenario file per borrower; add 3 or 4 deliberately degraded copies only |
| Guideline source text is large | Slow ingestion, weak retrieval | Load only the income, assets, liabilities and credit chapters and Reg X Subpart C |

## What we need from the AWS admin (by Tue 17 Nov)

- [ ] S3 bucket in one region, ideally the same region we use for Bedrock: Block Public Access on, default encryption on, versioning on, a lifecycle rule that aborts incomplete multipart uploads after 1 day. Prefixes: `dev/arindam/`, `dev/abhay/`, `dev/amogh/`, `demo/`.
- [ ] Credentials per person, never one shared key: IAM Identity Center (short-lived) if available, otherwise one IAM user and access key each, deleted after the project.
- [ ] IAM policy limited to this project: `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on the bucket's objects and `s3:ListBucket` on the bucket; `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` (the Converse API uses these); read-only `bedrock:ListFoundationModels` and `bedrock:ListInferenceProfiles` for debugging.
- [ ] Bedrock model access enabled in that region for the Claude models we'll use and one embedding model (Amazon Titan Text Embeddings V2 or Cohere Embed). Newer Claude models may need to be called through a cross-region inference profile, so the admin should share the exact model or profile IDs.
- [ ] Bedrock quotas checked for the chosen Claude model (tokens and requests per minute), with an increase requested before the Day 9 evaluation runs.
- [ ] Budget alert on the account at an amount the admin sets, so a runaway loop shows up the same day.
- [ ] Optional, for a shared demo URL: one small EC2 instance to run the stack with Docker Compose. Without it we demo from a laptop.

Only synthetic documents go in the bucket. Gemini, OpenAI and Claude API keys come from those providers, not AWS.

## Decisions I've made (say by Tuesday if you disagree)

- pgvector instead of ChromaDB, so there is one database.
- PDF text layer first, Tesseract for scanned pages and images, low-confidence lines flagged for review; no paid OCR in the MVP, and OCR stays behind an interface.
- One API plus one worker, structured as service modules, instead of separately deployed microservices.
- Files in Amazon S3 and Claude through Bedrock on our AWS account; Postgres, Redis, the API and the worker run in Docker on our laptops for both reviews. Hosting the app on AWS (ECS, RDS) is Phase 2.

## Open questions

- [ ] Which provider and model is the default for the management demo?
- [ ] Does management want both pillars at v0.5, or is Pillar 1 enough?
- [ ] Who outside the team reviews the illustrative rule sets and thresholds?
