"""Pydantic request and response models for the JSON API."""

from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str
    patient_ref: str | None = None
    resource_types: list[str] | None = None


class CitationResponse(BaseModel):
    resource_id: str
    resource_type: str
    text_snippet: str
    date: str | None


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]
    confidence: str
    query: str


class PatientSummary(BaseModel):
    id: str
    name: str
    birth_date: str | None


class HealthResponse(BaseModel):
    status: str
    db_connected: bool
    chunks_count: int

