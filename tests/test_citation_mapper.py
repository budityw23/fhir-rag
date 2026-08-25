from datetime import datetime, timezone

from src.generation.citation_mapper import map_citations
from src.retrieval.hybrid_search import SearchResult


def _resource(resource_id: str, resource_type: str = "Observation") -> SearchResult:
    return SearchResult(
        resource_id=resource_id,
        resource_type=resource_type,
        patient_ref="Patient/abc-123",
        resource_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
        codes=[],
        references=[],
        text_content="Hemoglobin A1c (LOINC: 4548-4). Value: 7.2 %.",
        similarity=0.9,
    )


def test_map_citations_extracts_matches_case_insensitively():
    answer = map_citations(
        "The HbA1c was 7.2% [observation/a1c-1].",
        "What was the latest HbA1c?",
        [_resource("Observation/a1c-1")],
    )

    assert answer.confidence == "grounded"
    assert answer.answer.startswith("The HbA1c")
    assert answer.citations[0].resource_id == "Observation/a1c-1"
    assert answer.citations[0].resource_type == "Observation"
    assert "7.2" in answer.citations[0].text_snippet
    assert answer.citations[0].date == "2024-06-15"


def test_map_citations_classifies_partial_and_ungrounded_answers():
    partial = map_citations(
        "Metformin is active [MedicationRequest/med-1]. The dose changed [MedicationRequest/fake].",
        "What medication is active?",
        [_resource("MedicationRequest/med-1", "MedicationRequest")],
    )
    ungrounded = map_citations(
        "The patient has kidney disease [Condition/fake].",
        "Does the patient have kidney disease?",
        [_resource("Observation/a1c-1")],
    )

    assert partial.confidence == "partially_grounded"
    assert [citation.resource_id for citation in partial.citations] == ["MedicationRequest/med-1"]
    assert ungrounded.confidence == "ungrounded"
    assert ungrounded.citations == []


def test_map_citations_without_citations_is_ungrounded_and_deduplicates():
    no_citation = map_citations("Insufficient data.", "Question", [_resource("Observation/a1c-1")])
    duplicate = map_citations(
        "See [Observation/a1c-1] and again [Observation/a1c-1].",
        "Question",
        [_resource("Observation/a1c-1")],
    )

    assert no_citation.confidence == "ungrounded"
    assert duplicate.confidence == "grounded"
    assert len(duplicate.citations) == 1

