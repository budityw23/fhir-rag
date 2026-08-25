"""Build structured, citation-ready context for answer generation."""

from collections import OrderedDict

from .hybrid_search import SearchResult


def _group_by_type(results: list[SearchResult]) -> OrderedDict[str, list[SearchResult]]:
    groups: OrderedDict[str, list[SearchResult]] = OrderedDict()
    for result in results:
        groups.setdefault(result.resource_type, []).append(result)
    return groups


def _render_grouped(results: list[SearchResult], primary: bool) -> list[str]:
    lines: list[str] = []
    for resource_type, grouped in _group_by_type(results).items():
        lines.append(f"-- {resource_type} --")
        for result in grouped:
            if primary:
                lines.append(f"[{result.resource_id}] (similarity: {result.similarity:.2f})")
            else:
                lines.append(f"[{result.resource_id}] (supporting context)")
            lines.append(result.text_content)
            lines.append("")
    return lines


def build_context(
    primary_results: list[SearchResult],
    supplementary_results: list[SearchResult],
) -> str:
    """Build structured context string for LLM prompt.
    Groups by resource type. Includes resource IDs for citation.
    Primary results first, then supplementary (marked as supporting context).
    """
    lines = ["=== Retrieved FHIR Resources (ranked by relevance) ===", ""]
    lines.extend(_render_grouped(primary_results, primary=True))
    if supplementary_results:
        lines.extend([
            "=== Supporting FHIR Resources (resolved references) ===",
            "",
        ])
        lines.extend(_render_grouped(supplementary_results, primary=False))
    return "\n".join(lines).rstrip()

