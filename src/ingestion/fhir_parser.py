"""Parse FHIR R4 Bundles into resources used by the ingestion pipeline."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fhir.resources.bundle import Bundle

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


def parse_bundle(bundle_path: Path) -> list[ParsedResource]:
    """Parse a FHIR Bundle JSON file, return individual resources."""
    try:
        with bundle_path.open(encoding="utf-8") as file:
            payload = json.load(file)
        bundle = Bundle.model_validate(payload)
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Skipping invalid FHIR Bundle %s: %s", bundle_path, exc)
        return []
    except ValueError as exc:
        # Validate entries independently as well, so one malformed resource
        # does not discard otherwise usable resources from the Bundle.
        logger.warning("FHIR Bundle %s has invalid resources: %s", bundle_path, exc)
        valid_entries = []
        for entry in payload.get("entry", []) if isinstance(payload, dict) else []:
            try:
                candidate = {
                    "resourceType": "Bundle",
                    "type": payload.get("type", "collection"),
                    "entry": [entry],
                }
                valid_entries.extend(Bundle.model_validate(candidate).entry or [])
            except (TypeError, ValueError) as entry_exc:
                logger.warning("Skipping invalid resource entry in %s: %s", bundle_path, entry_exc)
        bundle = type("ValidatedBundle", (), {"entry": valid_entries})()

    parsed: list[ParsedResource] = []
    for entry in bundle.entry or []:
        resource = entry.resource
        if resource is None:
            logger.warning("Skipping empty resource entry in %s", bundle_path)
            continue

        resource_json = resource.model_dump(exclude_none=True)
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
                patient_ref=resolve_patient_ref(resource_json, resource_type),
                references=extract_references(resource_json),
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


def resolve_patient_ref(resource: dict, resource_type: str) -> str | None:
    """Extract patient reference from a resource. Handles subject, patient fields."""
    if resource_type == "Patient":
        return _resource_id(resource, resource_type)

    # FHIR resources use either subject or patient for their patient link.
    for field in ("subject", "patient"):
        reference = _reference_value(resource.get(field))
        if reference:
            return reference
    return None


def extract_references(resource: dict) -> list[str]:
    """Walk resource JSON and collect all Reference values."""
    references: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            reference = _reference_value(value)
            if reference and reference not in references:
                references.append(reference)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(resource)
    return references
