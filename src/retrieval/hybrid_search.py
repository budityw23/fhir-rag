"""Vector similarity search with optional structured FHIR filters."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class SearchResult:
    resource_id: str
    resource_type: str
    patient_ref: str
    resource_date: datetime | None
    codes: list[dict]
    references: list[str]
    text_content: str
    similarity: float


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def result_from_row(row: Any, similarity: float | None = None) -> SearchResult:
    """Convert an asyncpg record or mapping into a SearchResult."""
    row_similarity = _row_value(row, "similarity", 0.0)
    return SearchResult(
        resource_id=_row_value(row, "resource_id", ""),
        resource_type=_row_value(row, "resource_type", ""),
        patient_ref=_row_value(row, "patient_ref", ""),
        resource_date=_row_value(row, "resource_date"),
        codes=list(_row_value(row, "codes", []) or []),
        references=list(_row_value(row, "references", []) or []),
        text_content=_row_value(row, "text_content", ""),
        similarity=float(row_similarity if similarity is None else similarity),
    )


async def hybrid_search(
    pool,
    query_embedding: list[float],
    patient_ref: str | None = None,
    resource_types: list[str] | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    top_k: int = 10,
) -> list[SearchResult]:
    """Vector similarity search with optional structured filters."""
    query = """
        SELECT resource_id, resource_type, patient_ref, resource_date,
               codes, references, text_content,
               1 - (embedding <=> $1) AS similarity
        FROM fhir_chunks
        WHERE ($2 IS NULL OR patient_ref = $2)
          AND ($3 IS NULL OR resource_type = ANY($3))
          AND ($4 IS NULL OR resource_date >= $4)
          AND ($5 IS NULL OR resource_date <= $5)
        ORDER BY embedding <=> $1
        LIMIT $6
    """
    rows = await pool.fetch(
        query,
        query_embedding,
        patient_ref,
        resource_types,
        date_start,
        date_end,
        top_k,
    )
    return [result_from_row(row) for row in rows]

