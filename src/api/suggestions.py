"""Build example questions from what a patient's record actually contains.

Static suggestions mislead: offering "What is the latest HbA1c?" for a
six-year-old with no glucose results invites a question the record cannot
answer, and makes a correct "insufficient data" reply look like a failure.
"""

import re

# Administrative Conditions that Synthea emits once per visit. They are active
# and numerous, so they dominate a naive condition list without describing any
# clinical problem.
ADMINISTRATIVE_CONDITIONS = ("medication review due",)

# Matched against a patient's active condition text, lowest-effort first. Each
# entry contributes one question when its keyword appears.
CONDITION_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("diabet", "What is the latest HbA1c, and how has it trended?"),
    ("asthma", "What is the current asthma medication regimen?"),
    ("atopic dermatitis", "How has the atopic dermatitis been treated over time?"),
    ("rhinitis", "When was the allergic rhinitis diagnosed, and what triggers are recorded?"),
    ("hypertension", "What are the most recent blood pressure readings?"),
    ("obesity", "How has BMI percentile changed over time?"),
)

# Contributed when the patient has any resource of that type.
RESOURCE_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("AllergyIntolerance", "Which allergies are documented, and what reaction did each cause?"),
    ("Immunization", "Is the immunization schedule up to date for this patient's age?"),
    ("MedicationRequest", "What medications is this patient currently taking?"),
    ("Procedure", "What procedures have been performed, and why?"),
)

_CONDITION_NAME = re.compile(r"^Condition:\s*(.+?)\s*\((?:SNOMED|LOINC|RxNorm)[:\s]", re.MULTILINE)

# Synthea records social determinants ("Unemployed", "Limited social contact")
# as active Conditions, and they are often the most recent ones. Ordering by
# date alone therefore buries the diagnoses a clinician would ask about.
SOCIAL_QUALIFIERS = ("finding",)

MAX_SUGGESTIONS = 4
# Condition-specific questions are capped so that resource-driven ones
# (allergies, immunizations) still reach a patient with several diagnoses.
MAX_CONDITION_QUESTIONS = 2

# SNOMED display names carry a type qualifier that reads as noise in a chip.
_QUALIFIER = re.compile(
    r"\s*\((?:disorder|situation|finding|procedure|regime/therapy|substance|organism)\)\s*$",
    re.IGNORECASE,
)


def _condition_rank(name: str, qualifier: str) -> int:
    """Order conditions by how likely a reader is to ask about them."""
    lowered = name.lower()
    if any(keyword in lowered for keyword, _ in CONDITION_QUESTIONS):
        return 0
    if qualifier.lower() in SOCIAL_QUALIFIERS:
        return 2
    return 1


def _condition_names(condition_texts: list[str]) -> list[str]:
    """Extract distinct condition display names, most askable first.

    Callers pass rows newest first; Python's stable sort preserves that order
    within each rank.
    """
    seen: set[str] = set()
    ranked: list[tuple[int, str]] = []
    for text in condition_texts:
        match = _CONDITION_NAME.search(text or "")
        if not match:
            continue
        raw = match.group(1).strip()
        qualifier_match = _QUALIFIER.search(raw)
        qualifier = qualifier_match.group(0).strip(" ()") if qualifier_match else ""
        name = _QUALIFIER.sub("", raw)
        lowered = name.lower()
        if any(skip in lowered for skip in ADMINISTRATIVE_CONDITIONS):
            continue
        if name in seen:
            continue
        seen.add(name)
        ranked.append((_condition_rank(name, qualifier), name))
    ranked.sort(key=lambda item: item[0])
    # "When was Unemployed diagnosed?" reads wrong. Social findings are kept
    # only when the record has no clinical condition to offer instead.
    clinical = [name for rank, name in ranked if rank < 2]
    return clinical or [name for _, name in ranked]


def build_suggestions(condition_texts: list[str], resource_types: list[str]) -> list[str]:
    """Derive example questions for one patient's record."""
    names = _condition_names(condition_texts)
    available = set(resource_types)
    suggestions: list[str] = []

    # Naming the conditions explicitly is deliberate. A generic "active
    # problems" question is answered from the retrieved chunks, and repeated
    # administrative Conditions can occupy every slot; naming them retrieves
    # the clinical rows instead.
    if names:
        listed = ", ".join(names[:3])
        suggestions.append(
            f"What is the history of {listed} for this patient, and when was each diagnosed?"
        )

    condition_blob = " ".join(names).lower()
    matched = 0
    for keyword, question in CONDITION_QUESTIONS:
        if matched >= MAX_CONDITION_QUESTIONS:
            break
        if keyword in condition_blob and question not in suggestions:
            suggestions.append(question)
            matched += 1

    for resource_type, question in RESOURCE_QUESTIONS:
        if resource_type in available and question not in suggestions:
            suggestions.append(question)

    if not suggestions:
        suggestions = [
            "What are this patient's active problems, and when was each diagnosed?",
            "What medications is this patient currently taking?",
        ]
    return suggestions[:MAX_SUGGESTIONS]
