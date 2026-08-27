"""Parse FHIR R4 Bundles into resources used by the ingestion pipeline."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ParsedResource:
    resource_id: str
    resource_type: str
    resource_json: dict
    patient_ref: str | None
    references: list[str]


SUPPORTED_TYPES = [
    "Patient", "Condition", "Observation", "MedicationRequest",
    "Encounter", "AllergyIntolerance", "Procedure", "DiagnosticReport",
    "Immunization", "CarePlan",
]


def _reference_value(value: Any) -> str | None:
    """Return a FHIR reference string when value is a Reference object."""
    if isinstance(value, dict) and isinstance(value.get("reference"), str):
        return value["reference"]
    return None


def _resource_id(resource: dict, resource_type: str) -> str | None:
    resource_id = resource.get("id")
    if not isinstance(resource_id, str) or not resource_id:
        return None
    return f"{resource_type}/{resource_id}"


def _reference_map(entries: list[Any]) -> dict[str, str]:
    """Map Bundle fullUrls to canonical FHIR resource IDs."""
    references: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        full_url = entry.get("fullUrl")
        resource = entry.get("resource")
        if not isinstance(full_url, str) or not isinstance(resource, dict):
            continue
        resource_type = resource.get("resourceType")
        if not isinstance(resource_type, str):
            continue
        resource_id = _resource_id(resource, resource_type)
        if resource_id:
            references[full_url] = resource_id
    return references


def _normalize_reference(reference: str, reference_map: dict[str, str] | None) -> str:
    return (reference_map or {}).get(reference, reference)


def parse_bundle(bundle_path: Path) -> list[ParsedResource]:
    """Parse a FHIR Bundle JSON file, return individual resources."""
    try:
        with bundle_path.open(encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Skipping invalid FHIR Bundle %s: %s", bundle_path, exc)
        return []

    if not isinstance(payload, dict) or not isinstance(payload.get("entry"), list):
        logger.warning("Skipping FHIR Bundle %s without an entry list", bundle_path)
        return []

    # Preserve fullUrl values from the original JSON so urn:uuid links can be
    # converted to canonical ResourceType/id references. Whole-Bundle Pydantic
    # validation is deliberately avoided: Synthea's large valid bundles are
    # expensive to validate and may not match the installed model version.
    entries = payload["entry"]
    reference_map = _reference_map(entries)

    parsed: list[ParsedResource] = []
    for entry in entries:
        resource_json = entry.get("resource") if isinstance(entry, dict) else None
        if resource_json is None:
            logger.warning("Skipping empty resource entry in %s", bundle_path)
            continue
        if not isinstance(resource_json, dict):
            continue
        resource_type = resource_json.get("resourceType")
        if resource_type not in SUPPORTED_TYPES:
            continue

        resource_id = _resource_id(resource_json, resource_type)
        if resource_id is None:
            logger.warning(
                "Skipping %s resource without an id in %s",
                resource_type,
                bundle_path,
            )
            continue

        parsed.append(
            ParsedResource(
                resource_id=resource_id,
                resource_type=resource_type,
                resource_json=resource_json,
                patient_ref=resolve_patient_ref(resource_json, resource_type, reference_map),
                references=extract_references(resource_json, reference_map),
            )
        )
    return parsed


def parse_all_bundles(data_dir: Path) -> list[ParsedResource]:
    """Parse all .json files in a directory."""
    resources: list[ParsedResource] = []
    try:
        bundle_paths = sorted(data_dir.glob("*.json"))
    except OSError as exc:
        logger.warning("Unable to read FHIR data directory %s: %s", data_dir, exc)
        return resources

    for bundle_path in bundle_paths:
        resources.extend(parse_bundle(bundle_path))
    return resources


def resolve_patient_ref(
    resource: dict,
    resource_type: str,
    reference_map: dict[str, str] | None = None,
) -> str | None:
    """Extract patient reference from a resource. Handles subject, patient fields."""
    if resource_type == "Patient":
        return _resource_id(resource, resource_type)

    # FHIR resources use either subject or patient for their patient link.
    for field in ("subject", "patient"):
        reference = _reference_value(resource.get(field))
        if reference:
            return _normalize_reference(reference, reference_map)
    return None


def extract_references(resource: dict, reference_map: dict[str, str] | None = None) -> list[str]:
    """Walk resource JSON and collect all Reference values."""
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            reference = _reference_value(value)
            if reference:
                normalized = _normalize_reference(reference, reference_map)
                if normalized not in extracted:
                    extracted.append(normalized)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    extracted: list[str] = []
    walk(resource)
    return extracted
