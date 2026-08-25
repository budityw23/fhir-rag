from src.ingestion.text_renderer import (
    render_care_plan,
    render_condition,
    render_medication_request,
    render_observation,
    render_resource_text,
)


PATIENT = {"reference": "Patient/abc-123"}


def test_render_type_2_diabetes_condition():
    text = render_condition({
        "resourceType": "Condition",
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "44054006", "display": "Diabetes mellitus type 2"}]},
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "onsetDateTime": "2019-03-15",
        "subject": PATIENT,
    })

    assert "Condition: Diabetes mellitus type 2 (SNOMED: 44054006)." in text
    assert "Status: active." in text
    assert "Onset: 2019-03-15." in text
    assert "Patient: Patient/abc-123." in text


def test_render_hba1c_observation():
    text = render_observation({
        "resourceType": "Observation",
        "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "Hemoglobin A1c"}]},
        "valueQuantity": {"value": 7.2, "unit": "%"},
        "effectiveDateTime": "2024-06-15",
        "subject": PATIENT,
    })

    assert "Hemoglobin A1c (LOINC: 4548-4)" in text
    assert "Value: 7.2 %." in text
    assert "Date: 2024-06-15." in text


def test_render_metformin_medication_request():
    text = render_medication_request({
        "resourceType": "MedicationRequest",
        "medicationCodeableConcept": {"coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "860975", "display": "Metformin 500 MG"}]},
        "status": "active",
        "authoredOn": "2024-03-15",
        "dosageInstruction": [{"text": "Take one tablet by mouth daily"}],
        "subject": PATIENT,
    })

    assert "MedicationRequest: Metformin 500 MG (RxNorm: 860975)." in text
    assert "Status: active." in text
    assert "Authored: 2024-03-15." in text
    assert "Take one tablet" in text


def test_render_diabetes_care_plan_and_dispatch():
    resource = {
        "resourceType": "CarePlan",
        "title": "Diabetes self-management plan",
        "status": "active",
        "period": {"start": "2019-04-01"},
        "activity": [
            {"detail": {"description": "Glucose monitoring"}},
            {"detail": {"description": "Medication review"}},
        ],
        "subject": PATIENT,
    }

    text = render_care_plan(resource)
    dispatched = render_resource_text(resource, "CarePlan")

    assert "CarePlan: Diabetes self-management plan." in text
    assert "Status: active." in text
    assert "Period: 2019-04-01 to ongoing." in text
    assert "Activities: Glucose monitoring, Medication review." in text
    assert dispatched == text


def test_unknown_resource_uses_readable_fallback():
    text = render_resource_text({"resourceType": "Unknown", "status": "active"}, "Unknown")
    assert text == "Unknown: status: active."
    assert "{" not in text and "}" not in text

