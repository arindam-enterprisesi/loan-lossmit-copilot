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

Backend checks:

```bash
docker compose up -d postgres      # tests/db builds a throwaway database with the real migration
cd backend
uv sync
uv run pytest                      # tests/db skips (locally) if Postgres is not running
uv run python -m app.llm.smoke     # one real Claude call; needs ANTHROPIC_API_KEY
```

`TEST_DATABASE_URL` (default: the compose Postgres) must point at a server where the user can create databases.

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
