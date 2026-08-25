from unittest.mock import AsyncMock, Mock

import pytest

from src.retrieval.context_builder import build_context
from src.retrieval.hybrid_search import SearchResult
from src.retrieval.reference_resolver import resolve_references


def _result(resource_id: str, references: list[str], similarity: float = 0.8) -> SearchResult:
    return SearchResult(
        resource_id=resource_id,
        resource_type="Condition",
        patient_ref="Patient/abc-123",
        resource_date=None,
        codes=[],
        references=references,
        text_content=f"Text for {resource_id}.",
        similarity=similarity,
    )


def _row(resource_id: str, resource_type: str, references: list[str]) -> dict:
    return {
        "resource_id": resource_id,
        "resource_type": resource_type,
        "patient_ref": "Patient/abc-123",
        "resource_date": None,
        "codes": [],
        "references": references,
        "text_content": f"Text for {resource_id}.",
    }


@pytest.mark.asyncio
async def test_resolve_references_follows_two_hops_and_deduplicates():
    pool = Mock()
    pool.fetch = AsyncMock(side_effect=[
        [_row("Observation/a", "Observation", ["MedicationRequest/med-1"]),
         _row("Condition/primary", "Condition", [])],
        [_row("MedicationRequest/med-1", "MedicationRequest", ["Patient/abc-123"]),
         _row("Patient/abc-123", "Patient", [])],
    ])
    primary = [_result("Condition/primary", ["Observation/a", "Condition/primary"])]

    supplementary = await resolve_references(pool, primary, max_hops=2)

    assert [result.resource_id for result in supplementary] == [
        "Observation/a", "MedicationRequest/med-1", "Patient/abc-123"
    ]
    assert all(result.similarity == 0.0 for result in supplementary)
    assert pool.fetch.await_count == 2
    for call in pool.fetch.await_args_list:
        assert "<=>" not in call.args[0]
        assert "resource_id = ANY($1)" in call.args[0]


@pytest.mark.asyncio
async def test_resolve_references_caps_hops_and_handles_empty_results():
    pool = Mock()
    pool.fetch = AsyncMock()

    assert await resolve_references(pool, [_result("Condition/a", ["Observation/a"])], max_hops=0) == []
    assert await resolve_references(pool, [], max_hops=2) == []
    pool.fetch.assert_not_awaited()


def test_context_builder_separates_primary_and_supporting_resources():
    primary = [
        _result("MedicationRequest/med-1", [], similarity=0.87),
        _result("Condition/diabetes-1", [], similarity=0.82),
    ]
    primary[0].resource_type = "MedicationRequest"
    supplementary = [_result("Observation/a1c-1", [], similarity=0.0)]
    supplementary[0].resource_type = "Observation"

    context = build_context(primary, supplementary)

    assert context.index("=== Retrieved FHIR Resources") < context.index("=== Supporting FHIR Resources")
    assert "-- MedicationRequest --" in context
    assert "[MedicationRequest/med-1] (similarity: 0.87)" in context
    assert "[Condition/diabetes-1] (similarity: 0.82)" in context
    assert "[Observation/a1c-1] (supporting context)" in context
    assert context.index("[MedicationRequest/med-1]") < context.index("[Observation/a1c-1]")

