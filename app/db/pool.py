"""asyncpg pool lifecycle and schema application."""

from collections.abc import AsyncIterator
from importlib import resources

import asyncpg
from fastapi import Request
from pgvector.asyncpg import register_vector

# Arbitrary constant: serializes schema application when several API processes start at once.
_SCHEMA_LOCK_ID = 7_301_001


def _schema_sql() -> str:
    return resources.files("app.db").joinpath("schema.sql").read_text(encoding="utf-8")


async def apply_schema(dsn: str) -> None:
    """Apply schema.sql (idempotent). Runs before the pool exists, so the vector type is known."""
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("SELECT pg_advisory_lock($1)", _SCHEMA_LOCK_ID)
        try:
            await conn.execute(_schema_sql())
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", _SCHEMA_LOCK_ID)
    finally:
        await conn.close()


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


async def create_pool(dsn: str) -> asyncpg.Pool:
    await apply_schema(dsn)
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10, init=_init_connection)
    assert pool is not None
    return pool


async def get_db(request: Request) -> AsyncIterator[asyncpg.Connection]:
    """FastAPI dependency: one pooled connection per request."""
    pool: asyncpg.Pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        yield conn
