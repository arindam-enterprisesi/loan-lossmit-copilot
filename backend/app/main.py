"""FastAPI entry point. Feature routers mount under /api/v1 (the contract's server URL)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.routers import auth, cases, completeness, documents, income, jobs
from app.services.queue import close_queue

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await close_queue()  # the job queue's Redis connection is opened on first use


app = FastAPI(
    title="Loan Processing and Mortgage Loss Mitigation Copilot API",
    version="0.1.0",
    lifespan=lifespan,
)
register_error_handlers(app)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(cases.router, prefix=API_PREFIX)
app.include_router(documents.router, prefix=API_PREFIX)
app.include_router(jobs.router, prefix=API_PREFIX)
app.include_router(income.router, prefix=API_PREFIX)
app.include_router(completeness.router, prefix=API_PREFIX)


@app.get("/health", tags=["infra"])
async def health() -> dict[str, str]:
    """Liveness only. Outside the /api/v1 contract; compose uses it as a healthcheck."""
    return {"status": "ok"}
