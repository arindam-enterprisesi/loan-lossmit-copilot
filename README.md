# Loan Processing and Mortgage Loss Mitigation Copilot

A demo copilot for US mortgage professionals: loan processing and underwriting (Pillar 1) and loss mitigation (Pillar 2). Synthetic data only. It never approves, denies or offers anything; people make every decision.

Read `CLAUDE.md` first. The functional source of truth is `docs/feature-design.md`.

## Start

```bash
cp .env.example .env      # add your own keys
docker compose up         # web, api, worker, postgres+pgvector, redis  (lands D1, Abhay)
```

Until `docker-compose.yml` lands, run the backend checks directly:

```bash
cd backend
uv sync
uv run pytest
uv run python -m app.llm.smoke     # one real Claude call; needs ANTHROPIC_API_KEY
```

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
