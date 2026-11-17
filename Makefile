.PHONY: up down migrate seed test data

up:
	docker compose up -d --build

down:
	docker compose down

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python -m app.db.seed

test:
	cd backend && uv run pytest

data:
	cd backend && uv run python ../data/synthetic/generate.py
