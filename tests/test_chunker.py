from datetime import datetime

from src.ingestion.chunker import chunk_resource, extract_codes, extract_date
from src.ingestion.fhir_parser import ParsedResource


PATIENT = "Patient/abc-123"


def _parsed(resource_type: str, resource_json: dict) -> ParsedResource:
    return ParsedResource(
        resource_id=f"{resource_type}/one",
        resource_type=resource_type,
        resource_json=resource_json,
        patient_ref=PATIENT,
        references=[PATIENT],
    )


def test_extract_dates_for_diabetes_resource_types():
    condition = {"onsetDateTime": "2019-03-15"}
    observation = {"effectiveDateTime": "2024-06-15T12:30:00Z"}
    medication = {"authoredOn": "2024-03-15"}
    care_plan = {"period": {"start": "2019-04-01"}}

    assert extract_date(condition, "Condition") == datetime(2019, 3, 15)
    assert extract_date(observation, "Observation") == datetime.fromisoformat("2024-06-15T12:30:00+00:00")
    assert extract_date(medication, "MedicationRequest") == datetime(2024, 3, 15)
    assert extract_date(care_plan, "CarePlan") == datetime(2019, 4, 1)


def test_extract_date_uses_documented_priority():
    resource = {
        "effectiveDateTime": "2024-06-15",
        "onsetDateTime": "2019-03-15",
        "recordedDate": "2020-01-01",
        "authoredOn": "2021-01-01",
        "period": {"start": "2022-01-01"},
    }

    assert extract_date(resource, "Observation") == datetime(2024, 6, 15)


def test_extract_codes_from_diabetes_paths():
    resource = {
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "44054006", "display": "Type 2 diabetes"}]},
        "medicationCodeableConcept": {"coding": [{"system": "rxnorm", "code": "860975", "display": "Metformin"}]},
        "valueCodeableConcept": {"coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "Hemoglobin A1c"}]},
        "vaccineCode": {"coding": [{"system": "http://snomed.info/sct", "code": "123", "display": "Example vaccine"}]},
    }

    assert extract_codes(resource) == [
        {"system": "http://snomed.info/sct", "code": "44054006", "display": "Type 2 diabetes"},
        {"system": "rxnorm", "code": "860975", "display": "Metformin"},
        {"system": "http://loinc.org", "code": "4548-4", "display": "Hemoglobin A1c"},
        {"system": "http://snomed.info/sct", "code": "123", "display": "Example vaccine"},
    ]


def test_chunk_resource_creates_one_chunk_with_rendered_text():
    resource = {
        "resourceType": "Observation",
        "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "Hemoglobin A1c"}]},
        "valueQuantity": {"value": 7.2, "unit": "%"},
        "effectiveDateTime": "2024-06-15",
        "subject": {"reference": PATIENT},
    }

    chunk = chunk_resource(_parsed("Observation", resource))

    assert chunk.resource_id == "Observation/one"
    assert chunk.resource_type == "Observation"
    assert chunk.patient_ref == PATIENT
    assert chunk.resource_date == datetime(2024, 6, 15)
    assert chunk.codes[0]["code"] == "4548-4"
    assert "Hemoglobin A1c" in chunk.text_content
    assert "7.2" in chunk.text_content

