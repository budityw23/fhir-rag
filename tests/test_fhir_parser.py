import json

from src.ingestion.fhir_parser import (
    SUPPORTED_TYPES,
    extract_references,
    parse_all_bundles,
    parse_bundle,
    resolve_patient_ref,
)


def _bundle() -> dict:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "abc-123"}},
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "condition-1",
                    "subject": {"reference": "Patient/abc-123"},
                    "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
                    "code": {"coding": [{"system": "http://snomed.info/sct", "code": "44054006"}]},
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "a1c-1",
                    "status": "final",
                    "subject": {"reference": "Patient/abc-123"},
                    "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}]},
                }
            },
            {"resource": {"resourceType": "Organization", "id": "not-supported"}},
        ],
    }


def test_parse_bundle_validates_filters_and_resolves_resources(tmp_path):
    path = tmp_path / "diabetes.json"
    path.write_text(json.dumps(_bundle()), encoding="utf-8")

    resources = parse_bundle(path)

    assert [resource.resource_id for resource in resources] == [
        "Patient/abc-123", "Condition/condition-1", "Observation/a1c-1"
    ]
    assert all(resource.resource_type in SUPPORTED_TYPES for resource in resources)
    assert resources[0].patient_ref == "Patient/abc-123"
    assert resources[1].patient_ref == "Patient/abc-123"
    assert resources[2].patient_ref == "Patient/abc-123"


def test_parse_all_bundles_and_skip_invalid_json(tmp_path, caplog):
    (tmp_path / "valid.json").write_text(json.dumps(_bundle()), encoding="utf-8")
    (tmp_path / "broken.json").write_text("not json", encoding="utf-8")

    resources = parse_all_bundles(tmp_path)

    assert len(resources) == 3
    assert "Skipping invalid FHIR Bundle" in caplog.text


def test_extract_references_walks_nested_objects_without_duplicates():
    resource = {
        "resourceType": "CarePlan",
        "subject": {"reference": "Patient/abc-123"},
        "activity": [
            {"reference": {"reference": "ServiceRequest/request-1"}},
            {"detail": {"goal": [{"reference": "Goal/goal-1"}]}},
        ],
    }

    assert extract_references(resource) == [
        "Patient/abc-123", "ServiceRequest/request-1", "Goal/goal-1"
    ]


def test_patient_reference_resolution_for_diabetes_resources():
    patient = "Patient/abc-123"
    assert resolve_patient_ref({"subject": {"reference": patient}}, "Condition") == patient
    assert resolve_patient_ref({"subject": {"reference": patient}}, "Observation") == patient
    assert resolve_patient_ref({"subject": {"reference": patient}}, "MedicationRequest") == patient
    assert resolve_patient_ref({"patient": {"reference": patient}}, "Encounter") == patient
