from unittest.mock import AsyncMock, patch

import pytest

import src.database as database


@pytest.mark.asyncio
async def test_init_pool_registers_pgvector_for_each_connection():
    database.pool = None
    created_pool = AsyncMock()

    with patch("src.database.asyncpg.create_pool", new=AsyncMock(return_value=created_pool)) as create_pool:
        result = await database.init_pool("postgresql://test")

    assert result is created_pool
    create_pool.assert_awaited_once_with(
        "postgresql://test",
        init=database._initialize_connection,
    )
    database.pool = None
