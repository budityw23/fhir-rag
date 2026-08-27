from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from src.retrieval.hybrid_search import ARM_OVERFETCH, RRF_K, hybrid_search


def _row(resource_id: str, similarity: float) -> dict:
    return {
        "resource_id": resource_id,
        "resource_type": "Observation",
        "patient_ref": "Patient/abc-123",
        "resource_date": datetime(2024, 6, 15, tzinfo=timezone.utc),
        "codes": [{"system": "http://loinc.org", "code": "4548-4", "display": "HbA1c"}],
        "references": ["Patient/abc-123"],
        "text_content": f"Observation {resource_id}",
        "similarity": similarity,
    }


def _pool(rows: list[dict]) -> tuple[Mock, Mock]:
    """Build a pool whose acquire()/transaction() async context managers work."""
    connection = Mock()
    connection.fetch = AsyncMock(return_value=rows)
    connection.execute = AsyncMock()
    connection.transaction = Mock(return_value=AsyncMock())

    acquired = AsyncMock()
    acquired.__aenter__ = AsyncMock(return_value=connection)
    acquired.__aexit__ = AsyncMock(return_value=False)

    pool = Mock()
    pool.acquire = Mock(return_value=acquired)
    return pool, connection


@pytest.mark.asyncio
async def test_hybrid_search_passes_all_optional_filters_as_parameters():
    pool, connection = _pool([_row("Observation/a", 0.91), _row("Observation/b", 0.82)])
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 12, 31, tzinfo=timezone.utc)

    results = await hybrid_search(
        pool,
        [0.1] * 384,
        query_text="hba1c result",
        patient_ref="Patient/abc-123",
        resource_types=["Observation", "Condition"],
        date_start=start,
        date_end=end,
        top_k=5,
    )

    assert [result.resource_id for result in results] == ["Observation/a", "Observation/b"]
    query, *parameters = connection.fetch.await_args.args
    assert "<=>" in query
    assert "ANY($3::text[])" in query
    assert "resource_date >= $4::timestamptz" in query
    assert "resource_date <= $5::timestamptz" in query
    assert "ORDER BY embedding <=> $1" in query
    assert "Patient/abc-123" in parameters
    assert ["Observation", "Condition"] in parameters
    assert start in parameters and end in parameters and 5 in parameters
    assert "Patient/abc-123" not in query


@pytest.mark.asyncio
async def test_hybrid_search_supports_no_filters_and_zero_results():
    pool, connection = _pool([])

    results = await hybrid_search(pool, [0.0] * 384)

    assert results == []
    _, *parameters = connection.fetch.await_args.args
    assert parameters[1:] == [None, None, None, None, 10, 10 * ARM_OVERFETCH, None, RRF_K]


@pytest.mark.asyncio
async def test_hybrid_search_runs_both_arms_and_fuses_by_rrf():
    pool, connection = _pool([_row("Observation/a", 0.5)])

    await hybrid_search(pool, [0.1] * 384, query_text="immunization schedule", top_k=4)

    query, *parameters = connection.fetch.await_args.args
    # Both retrieval arms must be present, joined so a hit from either survives.
    assert "vector_arm" in query and "lexical_arm" in query
    assert "websearch_to_tsquery" in query
    assert "FULL OUTER JOIN" in query
    assert "immunization schedule" in parameters
    # Each arm over-fetches relative to the caller's top_k before fusion.
    assert 4 * ARM_OVERFETCH in parameters


@pytest.mark.asyncio
async def test_hybrid_search_disables_index_scan_only_for_patient_scoped_queries():
    pool, connection = _pool([])
    await hybrid_search(pool, [0.0] * 384, patient_ref="Patient/abc-123")
    assert connection.execute.await_args.args[0] == "SET LOCAL enable_indexscan = off"

    pool, connection = _pool([])
    await hybrid_search(pool, [0.0] * 384)
    connection.execute.assert_not_awaited()
