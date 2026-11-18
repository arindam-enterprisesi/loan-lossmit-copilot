-- Runs once, when the postgres volume is first created.
-- The first Alembic migration should also CREATE EXTENSION IF NOT EXISTS, for existing volumes.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
