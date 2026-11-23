.PHONY: up down migrate seed test data reset-demo

# One command back to a clean demo: empties the (local) database and stored files, then seeds the
# users, both cases and Angela's hardship profile, and uploads and reads every demo document.
# Needs `make data` first and S3 set up in .env. Options: `make reset-demo ARGS="--upload --fake-reader"`
# (rule-based reader, when no model provider works) or `ARGS=` to skip the upload.
ARGS ?= --upload
reset-demo:
	cd backend && uv run python -m app.db.reset_demo --yes $(ARGS)

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
