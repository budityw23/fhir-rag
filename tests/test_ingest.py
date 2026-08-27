import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.ingestion.chunker import FHIRChunk
from src.ingestion.ingest import ingest_bundles, store_chunks


def _chunk(resource_id: str) -> FHIRChunk:
    return FHIRChunk(
        resource_id=resource_id,
        resource_type="Observation",
        patient_ref="Patient/abc-123",
        resource_date=datetime(2024, 6, 15),
        codes=[{"system": "http://loinc.org", "code": "4548-4", "display": "HbA1c"}],
        references=["Patient/abc-123"],
        text_content="Hemoglobin A1c: 7.2 %.",
    )


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


def test_store_chunks_uses_pgvector_and_upserts_embeddings():
    connection = Mock()
    connection.executemany = AsyncMock()
    pool = Mock()
    pool.acquire.return_value = _Acquire(connection)
    chunks = [_chunk("Observation/a"), _chunk("Observation/b")]

    with patch("src.ingestion.ingest.register_vector", new=AsyncMock()) as register:
        stored = asyncio.run(store_chunks(pool, chunks, [[0.1] * 384, [0.2] * 384]))

    assert stored == 2
    register.assert_awaited_once_with(connection)
    connection.executemany.assert_awaited_once()
    query, records = connection.executemany.await_args.args
    # Re-ingestion must refresh embeddings in place. DO NOTHING would silently
    # keep vectors produced by a previously configured embedding backend.
    assert "ON CONFLICT (resource_id) DO UPDATE SET" in query
    assert "embedding = EXCLUDED.embedding" in query
    assert "text_content = EXCLUDED.text_content" in query
    assert records[0][0] == "Observation/a"
    assert '"code": "4548-4"' in records[0][4]

@pytest.mark.asyncio
async def test_empty_directory_returns_zero_stats_without_model_or_database(tmp_path):
    with patch("src.ingestion.ingest.Embedder") as embedder, patch(
        "src.ingestion.ingest.asyncpg.create_pool", new=AsyncMock()
    ) as create_pool:
        stats = await ingest_bundles(tmp_path, "postgresql://unused")

    assert stats == {"bundles": 0, "resources": 0, "chunks_stored": 0}
    embedder.assert_not_called()
    create_pool.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingestion_batches_embeddings_and_closes_pool(tmp_path):
    (tmp_path / "bundle.json").write_text("{}", encoding="utf-8")
    resources = [Mock(resource_json={}, resource_type="Observation") for _ in range(33)]
    chunks = [_chunk(f"Observation/{index}") for index in range(33)]
    embedder_instance = Mock()
    embedder_instance.embed_texts.side_effect = [
        [[0.1] * 384 for _ in range(32)],
        [[0.2] * 384],
    ]
    pool = Mock()
    pool.close = AsyncMock()

    with patch("src.ingestion.ingest.parse_all_bundles", return_value=resources), patch(
        "src.ingestion.ingest.chunk_resource", side_effect=chunks
    ), patch("src.ingestion.ingest.Embedder", return_value=embedder_instance), patch(
        "src.ingestion.ingest.asyncpg.create_pool", new=AsyncMock(return_value=pool)
    ), patch("src.ingestion.ingest.store_chunks", new=AsyncMock(return_value=33)) as store:
        stats = await ingest_bundles(tmp_path, "postgresql://unused")

    assert stats == {"bundles": 1, "resources": 33, "chunks_stored": 33}
    assert [call.args[0] for call in embedder_instance.embed_texts.call_args_list] == [
        [chunk.text_content for chunk in chunks[:32]],
        [chunk.text_content for chunk in chunks[32:]],
    ]
    store.assert_awaited_once_with(pool, chunks, [[0.1] * 384 for _ in range(32)] + [[0.2] * 384])
    pool.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_store_chunks_rejects_mismatched_embeddings():
    with pytest.raises(ValueError, match="one embedding per chunk"):
        await store_chunks(Mock(), [_chunk("Observation/a")], [])
