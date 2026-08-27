"""Async PostgreSQL connection-pool lifecycle helpers."""

import asyncpg
from pgvector.asyncpg import register_vector

from .config import settings


pool: asyncpg.Pool | None = None


async def _initialize_connection(connection: asyncpg.Connection) -> None:
    """Register pgvector codecs on each pooled database connection."""
    await register_vector(connection)


async def init_pool(database_url: str | None = None) -> asyncpg.Pool:
    """Create and return the application-wide asyncpg connection pool."""
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(
            database_url or settings.database_url,
            init=_initialize_connection,
        )
    return pool


async def close_pool() -> None:
    """Close the application pool when it has been initialized."""
    global pool
    if pool is not None:
        await pool.close()
        pool = None


def get_pool() -> asyncpg.Pool:
    """Return the initialized pool, raising a clear lifecycle error otherwise."""
    if pool is None:
        raise RuntimeError("Database pool has not been initialized")
    return pool
