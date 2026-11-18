"""Background job queue: arq on Redis. The API enqueues; the worker runs ``app.worker`` functions.

Kept behind a tiny protocol so the API can be tested without Redis.
"""

from __future__ import annotations

from typing import Any, Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.settings import get_settings

INGEST_FUNCTION = "ingest_documents"


class JobQueue(Protocol):
    async def enqueue(self, function: str, *args: Any, job_id: str) -> None:
        """Queue ``function(*args)``. ``job_id`` makes a repeat enqueue of the same job a no-op."""
        ...


class ArqQueue:
    """The real queue. The Redis connection is opened on first use, not at import."""

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url or get_settings().redis_url
        self._pool: ArqRedis | None = None

    async def enqueue(self, function: str, *args: Any, job_id: str) -> None:
        if self._pool is None:
            redis = RedisSettings.from_dsn(self._redis_url)
            redis.conn_retries = 1  # fail fast: this runs inside an upload request
            self._pool = await create_pool(redis)
        await self._pool.enqueue_job(function, *args, _job_id=job_id)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None


_queue: ArqQueue | None = None


def get_queue() -> JobQueue:
    """FastAPI dependency: the shared queue (tests override it)."""
    global _queue
    if _queue is None:
        _queue = ArqQueue()
    return _queue


async def close_queue() -> None:
    if _queue is not None:
        await _queue.close()
