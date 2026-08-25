"""Resolve cross-resource FHIR references for retrieved results."""

from .hybrid_search import SearchResult, result_from_row


REFERENCE_QUERY = """
    SELECT resource_id, resource_type, patient_ref, resource_date,
           codes, references, text_content
    FROM fhir_chunks
    WHERE resource_id = ANY($1)
"""


async def resolve_references(
    pool,
    results: list[SearchResult],
    max_hops: int = 2,
) -> list[SearchResult]:
    """Follow FHIR references from search results. Returns additional resources.
    Does not duplicate resources already in results.
    """
    if max_hops <= 0 or not results:
        return []

    seen = {result.resource_id for result in results}
    supplementary: list[SearchResult] = []
    frontier = _unique_references(results, seen)

    for _ in range(max_hops):
        if not frontier:
            break
        rows = await pool.fetch(REFERENCE_QUERY, frontier)
        found: list[SearchResult] = []
        for row in rows:
            resource_id = row["resource_id"]
            if resource_id in seen:
                continue
            seen.add(resource_id)
            found.append(result_from_row(row, similarity=0.0))
        supplementary.extend(found)
        frontier = _unique_references(found, seen)

    return supplementary


def _unique_references(results: list[SearchResult], seen: set[str]) -> list[str]:
    references: list[str] = []
    for result in results:
        for reference in result.references:
            if reference and reference not in seen and reference not in references:
                references.append(reference)
    return references

