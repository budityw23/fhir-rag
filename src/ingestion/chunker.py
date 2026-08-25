"""Convert parsed FHIR resources into one searchable chunk per resource."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .fhir_parser import ParsedResource
from .text_renderer import render_resource_text


@dataclass
class FHIRChunk:
    resource_id: str
    resource_type: str
    patient_ref: str
    resource_date: datetime | None
    codes: list[dict]
    references: list[str]
    text_content: str


def chunk_resource(parsed: ParsedResource) -> FHIRChunk:
    """Convert a ParsedResource into a FHIRChunk with structured metadata."""
    return FHIRChunk(
        resource_id=parsed.resource_id,
        resource_type=parsed.resource_type,
        patient_ref=parsed.patient_ref or "",
        resource_date=extract_date(parsed.resource_json, parsed.resource_type),
        codes=extract_codes(parsed.resource_json),
        references=list(parsed.references),
        text_content=render_resource_text(parsed.resource_json, parsed.resource_type),
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def extract_date(resource_json: dict, resource_type: str) -> datetime | None:
    """Extract the most relevant date from a resource.
    Priority: effectiveDateTime > onsetDateTime > recordedDate > authoredOn > period.start
    """
    del resource_type  # The field is part of the public API for resource-specific extensions.
    candidates: list[Any] = [
        resource_json.get("effectiveDateTime"),
        resource_json.get("onsetDateTime"),
        resource_json.get("recordedDate"),
        resource_json.get("authoredOn"),
        (resource_json.get("period") or {}).get("start")
        if isinstance(resource_json.get("period"), dict)
        else None,
    ]
    for candidate in candidates:
        parsed = _parse_datetime(candidate)
        if parsed is not None:
            return parsed
    return None


def extract_codes(resource_json: dict) -> list[dict]:
    """Extract all coded values (SNOMED, LOINC, RxNorm) from a resource."""
    codes: list[dict] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            coding = value.get("coding")
            if isinstance(coding, list):
                for item in coding:
                    if not isinstance(item, dict) or not item.get("code"):
                        continue
                    code = {
                        "system": item.get("system", ""),
                        "code": item["code"],
                        "display": item.get("display", ""),
                    }
                    if code not in codes:
                        codes.append(code)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(resource_json)
    return codes

