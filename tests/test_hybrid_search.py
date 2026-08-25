from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from src.retrieval.hybrid_search import hybrid_search


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


@pytest.mark.asyncio
async def test_hybrid_search_passes_all_optional_filters_as_parameters():
    pool = Mock()
    pool.fetch = AsyncMock(return_value=[_row("Observation/a", 0.91), _row("Observation/b", 0.82)])
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 12, 31, tzinfo=timezone.utc)

    results = await hybrid_search(
        pool,
        [0.1] * 384,
        patient_ref="Patient/abc-123",
        resource_types=["Observation", "Condition"],
        date_start=start,
        date_end=end,
        top_k=5,
    )

    assert [result.resource_id for result in results] == ["Observation/a", "Observation/b"]
    query, *parameters = pool.fetch.await_args.args
    assert "<=>" in query
    assert "ANY($3)" in query
    assert "resource_date >= $4" in query
    assert "resource_date <= $5" in query
    assert "ORDER BY embedding <=> $1" in query
    assert "Patient/abc-123" in parameters
    assert ["Observation", "Condition"] in parameters
    assert start in parameters and end in parameters and 5 in parameters
    assert "Patient/abc-123" not in query


@pytest.mark.asyncio
async def test_hybrid_search_supports_no_filters_and_zero_results():
    pool = Mock()
    pool.fetch = AsyncMock(return_value=[])

    results = await hybrid_search(pool, [0.0] * 384)

    assert results == []
    _, *parameters = pool.fetch.await_args.args
    assert parameters[1:] == [None, None, None, None, 10]

