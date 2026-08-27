"""Hybrid vector + full-text search with optional structured FHIR filters."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Reciprocal Rank Fusion constant. 60 is the value from the original RRF
# paper and damps the influence of any single arm's top few results.
RRF_K = 60
# Candidates each arm contributes before fusion, as a multiple of top_k.
ARM_OVERFETCH = 5


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
    query_text: str | None = None,
    patient_ref: str | None = None,
    resource_types: list[str] | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    top_k: int = 10,
) -> list[SearchResult]:
    """Fuse vector and full-text ranking with Reciprocal Rank Fusion.

    The vector arm alone misses questions whose wording shares no tokens with
    the rendered resource ("immunization schedule" vs. the Immunization
    resources themselves), so a Postgres full-text arm runs alongside it and
    the two rankings are combined by RRF. When query_text is absent the
    lexical arm contributes nothing and this degrades to pure vector search.
    """
    # Each arm is over-fetched so that a resource ranked highly by one arm can
    # still surface after fusion even when the other arm ignores it entirely.
    candidate_limit = max(top_k * ARM_OVERFETCH, top_k)
    query = """
        WITH filtered AS (
            SELECT resource_id, resource_type, patient_ref, resource_date,
                   codes, "references", text_content, embedding, text_search
            FROM fhir_chunks
            WHERE ($2::text IS NULL OR patient_ref = $2::text)
              AND ($3::text[] IS NULL OR resource_type = ANY($3::text[]))
              AND ($4::timestamptz IS NULL OR resource_date >= $4::timestamptz)
              AND ($5::timestamptz IS NULL OR resource_date <= $5::timestamptz)
        ),
        vector_arm AS (
            SELECT resource_id,
                   ROW_NUMBER() OVER (ORDER BY embedding <=> $1) AS rank,
                   1 - (embedding <=> $1) AS similarity
            FROM filtered
            ORDER BY embedding <=> $1
            LIMIT $7
        ),
        lexical_arm AS (
            SELECT resource_id,
                   ROW_NUMBER() OVER (
                       ORDER BY ts_rank_cd(text_search, websearch_to_tsquery('english', $8)) DESC
                   ) AS rank
            FROM filtered
            WHERE $8::text IS NOT NULL
              AND text_search @@ websearch_to_tsquery('english', $8)
            ORDER BY ts_rank_cd(text_search, websearch_to_tsquery('english', $8)) DESC
            LIMIT $7
        ),
        fused AS (
            SELECT COALESCE(v.resource_id, l.resource_id) AS resource_id,
                   COALESCE(1.0 / ($9 + v.rank), 0.0)
                     + COALESCE(1.0 / ($9 + l.rank), 0.0) AS score,
                   COALESCE(v.similarity, 0.0) AS similarity
            FROM vector_arm v
            FULL OUTER JOIN lexical_arm l ON v.resource_id = l.resource_id
        )
        SELECT f.resource_id, c.resource_type, c.patient_ref, c.resource_date,
               c.codes, c."references", c.text_content, f.similarity
        FROM fused f
        JOIN filtered c ON c.resource_id = f.resource_id
        ORDER BY f.score DESC
        LIMIT $6
    """
    async with pool.acquire() as connection:
        async with connection.transaction():
            if patient_ref is not None:
                # HNSW selects global nearest neighbors before applying the
                # patient filter, which can incorrectly return no records.
                # Patient-scoped searches are small enough for exact ranking.
                await connection.execute("SET LOCAL enable_indexscan = off")
            rows = await connection.fetch(
                query,
                query_embedding,
                patient_ref,
                resource_types,
                date_start,
                date_end,
                top_k,
                candidate_limit,
                query_text,
                RRF_K,
            )
    return [result_from_row(row) for row in rows]
