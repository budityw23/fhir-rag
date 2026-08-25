from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import create_app
from src.generation.llm_client import LLMResponse
from src.retrieval.hybrid_search import SearchResult


def _application():
    application = create_app()
    application.state.pool = Mock()
    application.state.embedder = Mock()
    application.state.llm_client = Mock()
    return application


def _result(resource_id: str) -> SearchResult:
    return SearchResult(
        resource_id=resource_id,
        resource_type="Observation",
        patient_ref="Patient/abc-123",
        resource_date=datetime(2024, 6, 15),
        codes=[],
        references=[],
        text_content="Hemoglobin A1c (LOINC: 4548-4). Value: 7.2 %.",
        similarity=0.9,
    )


@pytest.mark.asyncio
async def test_health_returns_database_status_and_count():
    application = _application()
    application.state.pool.fetchval = AsyncMock(return_value=3)

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db_connected": True, "chunks_count": 3}


@pytest.mark.asyncio
async def test_query_orchestrates_pipeline_with_mocked_dependencies():
    application = _application()
    result = _result("Observation/a1c-1")
    application.state.embedder.embed_query.return_value = [0.1] * 384
    application.state.llm_client.generate = AsyncMock(
        return_value=LLMResponse(
            content="The HbA1c was 7.2% [Observation/a1c-1].",
            model="test-model",
            input_tokens=10,
            output_tokens=8,
        )
    )

    with patch("src.api.routes.hybrid_search", new=AsyncMock(return_value=[result])) as search, patch(
        "src.api.routes.resolve_references", new=AsyncMock(return_value=[])
    ) as resolve:
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver") as client:
            response = await client.post(
                "/api/query",
                json={"question": "What is the latest HbA1c?", "patient_ref": "Patient/abc-123"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["confidence"] == "grounded"
    assert body["citations"][0]["resource_id"] == "Observation/a1c-1"
    search.assert_awaited_once()
    resolve.assert_awaited_once()
    application.state.embedder.embed_query.assert_called_once_with("What is the latest HbA1c?")


@pytest.mark.asyncio
async def test_patients_returns_distinct_patient_summaries():
    application = _application()
    application.state.pool.fetch = AsyncMock(return_value=[
        {"patient_ref": "Patient/abc-123", "text_content": "Patient: Jane Doe. Demographics: female, 1965-04-12."}
    ])

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver") as client:
        response = await client.get("/api/patients")

    assert response.status_code == 200
    assert response.json() == [{"id": "Patient/abc-123", "name": "Jane Doe", "birth_date": "1965-04-12"}]


@pytest.mark.asyncio
async def test_query_validation_returns_422():
    application = _application()

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver") as client:
        response = await client.post("/api/query", json={})

    assert response.status_code == 422
