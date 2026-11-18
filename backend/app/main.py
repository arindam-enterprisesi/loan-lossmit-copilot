"""FastAPI entry point. Feature routers mount under /api/v1 (the contract's server URL)."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.routers import auth, cases

API_PREFIX = "/api/v1"

app = FastAPI(
    title="Loan Processing and Mortgage Loss Mitigation Copilot API",
    version="0.1.0",
)
register_error_handlers(app)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(cases.router, prefix=API_PREFIX)


@app.get("/health", tags=["infra"])
async def health() -> dict[str, str]:
    """Liveness only. Outside the /api/v1 contract; compose uses it as a healthcheck."""
    return {"status": "ok"}
