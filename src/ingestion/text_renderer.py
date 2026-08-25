"""Human-readable renderers for FHIR resources used in embeddings."""

from collections.abc import Iterable
from typing import Any


def _first_coding(resource: dict, *paths: str) -> tuple[str, str, str] | None:
    for path in paths:
        value: Any = resource
        for part in path.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        codings = value.get("coding", []) if isinstance(value, dict) else []
        if isinstance(codings, list):
            for coding in codings:
                if isinstance(coding, dict) and coding.get("code"):
                    return (
                        str(coding.get("display") or coding["code"]),
                        str(coding["code"]),
                        _system_name(coding.get("system")),
                    )
    return None


def _system_name(system: Any) -> str:
    names = {
        "http://snomed.info/sct": "SNOMED",
        "http://loinc.org": "LOINC",
        "http://www.nlm.nih.gov/research/umls/rxnorm": "RxNorm",
    }
    return names.get(str(system), str(system or "code"))


def _coded_text(coding: tuple[str, str, str] | None) -> str:
    if coding is None:
        return "unspecified"
    display, code, system = coding
    return f"{display} ({system}: {code})"


def _patient(resource: dict) -> str:
    for field in ("subject", "patient"):
        reference = resource.get(field, {})
        if isinstance(reference, dict) and reference.get("reference"):
            return str(reference["reference"])
    return "unknown patient"


def _date(resource: dict, *fields: str) -> str | None:
    for field in fields:
        value = resource.get(field)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            for nested in ("start", "end"):
                if isinstance(value.get(nested), str) and value[nested]:
                    return value[nested]
    return None


def _status(resource: dict, *fields: str) -> str | None:
    for field in fields:
        value = resource.get(field)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            codings = value.get("coding", [])
            if isinstance(codings, list) and codings:
                coding = codings[0]
                if isinstance(coding, dict):
                    return str(coding.get("display") or coding.get("code") or "") or None
    return None


def _join(items: Iterable[str]) -> str:
    return ", ".join(item for item in items if item)


def render_resource_text(resource_json: dict, resource_type: str) -> str:
    """Convert a FHIR resource to human-readable text for embedding."""
    renderers = {
        "Patient": render_patient,
        "Condition": render_condition,
        "Observation": render_observation,
        "MedicationRequest": render_medication_request,
        "Encounter": render_encounter,
        "AllergyIntolerance": render_allergy_intolerance,
        "Procedure": render_procedure,
        "DiagnosticReport": render_diagnostic_report,
        "Immunization": render_immunization,
        "CarePlan": render_care_plan,
    }
    renderer = renderers.get(resource_type)
    return renderer(resource_json) if renderer else _render_generic(resource_json, resource_type)


def render_patient(resource: dict) -> str:
    names = resource.get("name", [])
    display_name = "unknown"
    if names and isinstance(names[0], dict):
        name = names[0]
        display_name = " ".join(name.get("given", []) + [name.get("family", "")]).strip()
    details = _join(filter(None, [resource.get("gender"), resource.get("birthDate")]))
    return f"Patient: {display_name}." + (f" Demographics: {details}." if details else "")


def render_condition(resource: dict) -> str:
    code = _coded_text(_first_coding(resource, "code"))
    status = _status(resource, "clinicalStatus", "verificationStatus")
    onset = _date(resource, "onsetDateTime", "onsetPeriod")
    lines = [f"Condition: {code}."]
    if status:
        lines.append(f"Status: {status}.")
    if onset:
        lines.append(f"Onset: {onset}.")
    lines.append(f"Patient: {_patient(resource)}.")
    return "\n".join(lines)


def render_observation(resource: dict) -> str:
    code = _coded_text(_first_coding(resource, "code"))
    value = resource.get("valueQuantity")
    if isinstance(value, dict) and value.get("value") is not None:
        value_text = f"{value['value']} {value.get('unit', value.get('code', ''))}".strip()
    elif isinstance(resource.get("valueCodeableConcept"), dict):
        value_text = _coded_text(_first_coding(resource, "valueCodeableConcept"))
    else:
        value_text = "not recorded"
    date = _date(resource, "effectiveDateTime", "effectivePeriod", "issued")
    lines = [f"Observation: {code}.", f"Value: {value_text}."]
    if date:
        lines.append(f"Date: {date}.")
    lines.append(f"Patient: {_patient(resource)}.")
    return "\n".join(lines)


def render_medication_request(resource: dict) -> str:
    medication = _coded_text(_first_coding(resource, "medicationCodeableConcept"))
    if medication == "unspecified" and isinstance(resource.get("medicationReference"), dict):
        medication = str(resource["medicationReference"].get("display", "unspecified medication"))
    status = _status(resource, "status")
    authored = _date(resource, "authoredOn")
    dosage: list[str] = []
    for instruction in resource.get("dosageInstruction", []):
        if isinstance(instruction, dict):
            if instruction.get("text"):
                dosage.append(str(instruction["text"]))
            dose = instruction.get("doseAndRate", [])
            if dose and isinstance(dose[0], dict):
                quantity = dose[0].get("doseQuantity", {})
                if isinstance(quantity, dict) and quantity.get("value") is not None:
                    dosage.append(f"{quantity['value']} {quantity.get('unit', '')}".strip())
    lines = [f"MedicationRequest: {medication}."]
    if status:
        lines.append(f"Status: {status}.")
    if authored:
        lines.append(f"Authored: {authored}.")
    if dosage:
        lines.append(f"Dosage: {_join(dosage)}.")
    lines.append(f"Patient: {_patient(resource)}.")
    return "\n".join(lines)


def render_encounter(resource: dict) -> str:
    encounter_type = _coded_text(_first_coding(resource, "type"))
    status = _status(resource, "status")
    period = _date(resource, "period")
    lines = [f"Encounter: {encounter_type}."]
    if status:
        lines.append(f"Status: {status}.")
    if period:
        lines.append(f"Date: {period}.")
    lines.append(f"Patient: {_patient(resource)}.")
    return "\n".join(lines)


def render_allergy_intolerance(resource: dict) -> str:
    code = _coded_text(_first_coding(resource, "code"))
    status = _status(resource, "clinicalStatus", "verificationStatus")
    lines = [f"AllergyIntolerance: {code}."]
    if status:
        lines.append(f"Status: {status}.")
    lines.append(f"Patient: {_patient(resource)}.")
    return "\n".join(lines)


def render_procedure(resource: dict) -> str:
    code = _coded_text(_first_coding(resource, "code"))
    status = _status(resource, "status")
    performed = _date(resource, "performedDateTime", "performedPeriod")
    lines = [f"Procedure: {code}."]
    if status:
        lines.append(f"Status: {status}.")
    if performed:
        lines.append(f"Date: {performed}.")
    lines.append(f"Patient: {_patient(resource)}.")
    return "\n".join(lines)


def render_diagnostic_report(resource: dict) -> str:
    code = _coded_text(_first_coding(resource, "code"))
    status = _status(resource, "status")
    effective = _date(resource, "effectiveDateTime", "effectivePeriod")
    lines = [f"DiagnosticReport: {code}."]
    if status:
        lines.append(f"Status: {status}.")
    if effective:
        lines.append(f"Date: {effective}.")
    if resource.get("conclusion"):
        lines.append(f"Conclusion: {resource['conclusion']}.")
    lines.append(f"Patient: {_patient(resource)}.")
    return "\n".join(lines)


def render_immunization(resource: dict) -> str:
    vaccine = _coded_text(_first_coding(resource, "vaccineCode"))
    status = _status(resource, "status")
    occurrence = _date(resource, "occurrenceDateTime", "occurrencePeriod")
    lines = [f"Immunization: {vaccine}."]
    if status:
        lines.append(f"Status: {status}.")
    if occurrence:
        lines.append(f"Date: {occurrence}.")
    lines.append(f"Patient: {_patient(resource)}.")
    return "\n".join(lines)


def render_care_plan(resource: dict) -> str:
    title = resource.get("title") or resource.get("description") or "care plan"
    status = _status(resource, "status", "intent")
    period = _date(resource, "period")
    activities: list[str] = []
    for activity in resource.get("activity", []):
        if not isinstance(activity, dict):
            continue
        detail = activity.get("detail", {})
        if isinstance(detail, dict):
            text = detail.get("description") or detail.get("code", {}).get("text")
            if text:
                activities.append(str(text))
    lines = [f"CarePlan: {title}."]
    if status:
        lines.append(f"Status: {status}.")
    if period:
        end = resource.get("period", {}).get("end") if isinstance(resource.get("period"), dict) else None
        lines.append(f"Period: {period} to {end or 'ongoing'}.")
    if activities:
        lines.append(f"Activities: {_join(activities)}.")
    lines.append(f"Patient: {_patient(resource)}.")
    return "\n".join(lines)


def _render_generic(resource: dict, resource_type: str) -> str:
    """Render scalar fields without exposing raw JSON syntax."""
    parts: list[str] = []
    for key, value in resource.items():
        if key in {"resourceType", "id"} or isinstance(value, (dict, list)):
            continue
        parts.append(f"{key.replace('_', ' ')}: {value}")
    detail = ". ".join(parts) if parts else "No additional details recorded"
    return f"{resource_type}: {detail}."
