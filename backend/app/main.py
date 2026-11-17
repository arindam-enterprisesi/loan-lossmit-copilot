"""FastAPI entry point. Feature routers mount under /api/v1 from ``app.api``."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="Loan Processing and Mortgage Loss Mitigation Copilot API",
    version="0.1.0",
)


@app.get("/health", tags=["infra"])
async def health() -> dict[str, str]:
    """Liveness only. Outside the /api/v1 contract; compose uses it as a healthcheck."""
    return {"status": "ok"}
