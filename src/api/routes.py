"""FastAPI routes for the FHIR RAG application."""

import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..config import settings
from ..database import get_pool
from ..generation.citation_mapper import map_citations
from ..retrieval.context_builder import build_context
from ..retrieval.hybrid_search import hybrid_search
from ..retrieval.reference_resolver import resolve_references
from .schemas import CitationResponse, HealthResponse, PatientSummary, QueryRequest, QueryResponse

logger = logging.getLogger(__name__)
router = APIRouter()
_prompt_environment = Environment(
    loader=FileSystemLoader(Path(__file__).parent.parent / "generation" / "prompts"),
    undefined=StrictUndefined,
)


def _pool(request: Request):
    pool = getattr(request.app.state, "pool", None)
    return pool or get_pool()


def _patient_summary(row) -> PatientSummary:
    patient_id = row.get("patient_ref", row.get("id", ""))
    text = row.get("text_content", "") or ""
    name_match = re.search(r"Patient:\s*([^\.]+)", text)
    date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    return PatientSummary(
        id=patient_id,
        name=row.get("name") or (name_match.group(1).strip() if name_match else patient_id),
        birth_date=row.get("birth_date") or (date_match.group(0) if date_match else None),
    )


@router.post("/api/query", response_model=QueryResponse)
async def query_patient(request: Request, query: QueryRequest) -> QueryResponse:
    """Answer a grounded question over retrieved FHIR resources."""
    try:
        pool = _pool(request)
        embedder = request.app.state.embedder
        llm_client = request.app.state.llm_client
        query_embedding = embedder.embed_query(query.question)
        primary = await hybrid_search(
            pool,
            query_embedding,
            patient_ref=query.patient_ref,
            resource_types=query.resource_types,
            top_k=settings.top_k,
        )
        supplementary = await resolve_references(
            pool,
            primary,
            max_hops=settings.max_reference_hops,
        )
        context = build_context(primary, supplementary)
        system_prompt = _prompt_environment.get_template("clinical_qa.jinja2").render(
            context=context,
            question=query.question,
        )
        llm_response = await llm_client.generate(system_prompt, query.question)
        grounded = map_citations(
            llm_response.content,
            query.question,
            primary + supplementary,
        )
        return QueryResponse(
            answer=grounded.answer,
            citations=[CitationResponse(**citation.__dict__) for citation in grounded.citations],
            confidence=grounded.confidence,
            query=grounded.query,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("FHIR query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Unable to process FHIR query") from exc


@router.get("/api/patients", response_model=list[PatientSummary])
async def list_patients(request: Request) -> list[PatientSummary]:
    """Return distinct patients represented in the FHIR chunk store."""
    try:
        rows = await _pool(request).fetch(
            """
            SELECT DISTINCT ON (patient_ref) patient_ref, text_content
            FROM fhir_chunks
            WHERE resource_type = $1
            ORDER BY patient_ref
            """,
            "Patient",
        )
        return [_patient_summary(row) for row in rows]
    except Exception as exc:
        logger.exception("Patient listing failed: %s", exc)
        raise HTTPException(status_code=500, detail="Unable to list patients") from exc


@router.get("/api/resources/{resource_id}")
async def get_resource(request: Request, resource_id: str) -> dict:
    """Return one resource's text and searchable metadata."""
    try:
        row = await _pool(request).fetchrow(
            """
            SELECT resource_id, resource_type, patient_ref, resource_date,
                   codes, references, text_content, created_at
            FROM fhir_chunks
            WHERE resource_id = $1
            """,
            resource_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="FHIR resource not found")
        return dict(row)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Resource lookup failed: %s", exc)
        raise HTTPException(status_code=500, detail="Unable to retrieve FHIR resource") from exc


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Check database connectivity and report the indexed chunk count."""
    try:
        count = await _pool(request).fetchval("SELECT COUNT(*) FROM fhir_chunks")
        return HealthResponse(status="ok", db_connected=True, chunks_count=int(count))
    except Exception as exc:
        logger.exception("Health check failed: %s", exc)
        raise HTTPException(status_code=500, detail="Database is unavailable") from exc

