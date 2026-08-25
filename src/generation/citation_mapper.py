"""Map LLM resource citations back to retrieved FHIR resources."""

import re
from dataclasses import dataclass

from ..retrieval.hybrid_search import SearchResult


@dataclass
class Citation:
    resource_id: str
    resource_type: str
    text_snippet: str
    date: str | None


@dataclass
class GroundedAnswer:
    answer: str
    citations: list[Citation]
    confidence: str
    query: str


CITATION_PATTERN = re.compile(r"\[([A-Za-z][A-Za-z0-9]*)/([^\]\s]+)\]")


def _date_text(resource: SearchResult) -> str | None:
    if resource.resource_date is None:
        return None
    return resource.resource_date.date().isoformat()


def map_citations(
    llm_response: str,
    query: str,
    available_resources: list[SearchResult],
) -> GroundedAnswer:
    """Parse LLM response for [ResourceType/id] citations.
    Match against available_resources. Classify confidence.
    """
    matches = CITATION_PATTERN.findall(llm_response)
    resources = {
        (resource.resource_type.lower(), resource.resource_id.split("/", 1)[-1].lower()): resource
        for resource in available_resources
    }
    citations: list[Citation] = []
    seen_ids: set[str] = set()
    valid_count = 0
    for resource_type, resource_id in matches:
        key = (resource_type.lower(), resource_id.lower())
        resource = resources.get(key)
        if resource is None:
            continue
        valid_count += 1
        if resource.resource_id in seen_ids:
            continue
        seen_ids.add(resource.resource_id)
        citations.append(
            Citation(
                resource_id=resource.resource_id,
                resource_type=resource.resource_type,
                text_snippet=resource.text_content,
                date=_date_text(resource),
            )
        )

    if not matches or valid_count == 0:
        confidence = "ungrounded"
    elif valid_count == len(matches):
        confidence = "grounded"
    else:
        confidence = "partially_grounded"
    return GroundedAnswer(
        answer=llm_response,
        citations=citations,
        confidence=confidence,
        query=query,
    )

