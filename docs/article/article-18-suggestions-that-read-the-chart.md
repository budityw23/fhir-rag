---
title: "Suggestions That Read the Chart: Generating Example Questions Per Patient"
published: false
tags: fhir, ux, python, rag
series: "Grounded RAG over FHIR"
---

My interface offered four example questions. One of them was "What is the latest HbA1c, and how has it trended?"

Then I added a pediatric patient to the corpus. A six-year-old with eczema, asthma, and allergic rhinitis, and no glucose result anywhere in his record. Clicking that suggestion produced a correct, well-behaved refusal:

> Insufficient data in the available FHIR resources to answer this question.

Which reads, to anyone who did not write the system, as a broken demo. My own interface had invited the user to ask a question the record could not answer, and then the system got blamed for answering it honestly.

The suggestions had to read the chart.

## Static examples set you up to fail

The general problem is that a static example makes a claim about the data. "Here is a question you can ask" implies "and this record can answer it". When it cannot, the user's first interaction is a refusal, and refusals are the output people are least inclined to trust.

This matters disproportionately for a system whose whole design point is that it declines when the evidence is missing. Every refusal I can prevent by not asking a stupid question is a refusal that does not erode confidence in the ones that are genuinely informative.

So the endpoint reads what is actually in the patient's record:

```python
# src/api/routes.py
condition_rows = await pool.fetch(
    """
    SELECT text_content
    FROM fhir_chunks
    WHERE patient_ref = $1
      AND resource_type = 'Condition'
      AND text_content ILIKE '%Status: active%'
    ORDER BY resource_date DESC NULLS LAST
    """,
    patient_ref,
)
type_rows = await pool.fetch(
    "SELECT DISTINCT resource_type FROM fhir_chunks WHERE patient_ref = $1",
    patient_ref,
)
```

Two cheap indexed queries: the patient's active conditions, and which resource types exist for them at all. Everything else is pure logic over those two lists, which makes it trivially testable.

## Two sources of questions

Conditions drive specific questions. Resource types drive general ones.

```python
# src/api/suggestions.py
CONDITION_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("diabet", "What is the latest HbA1c, and how has it trended?"),
    ("asthma", "What is the current asthma medication regimen?"),
    ("atopic dermatitis", "How has the atopic dermatitis been treated over time?"),
    ("rhinitis", "When was the allergic rhinitis diagnosed, and what triggers are recorded?"),
    ("hypertension", "What are the most recent blood pressure readings?"),
    ("obesity", "How has BMI percentile changed over time?"),
)

RESOURCE_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("AllergyIntolerance", "Which allergies are documented, and what reaction did each cause?"),
    ("Immunization", "Is the immunization schedule up to date for this patient's age?"),
    ("MedicationRequest", "What medications is this patient currently taking?"),
    ("Procedure", "What procedures have been performed, and why?"),
)
```

The HbA1c question now appears only for a patient whose active conditions mention diabetes. The pediatric patient gets asthma, allergies, and immunizations instead, all of which his record can answer.

This is deliberately a keyword table rather than anything cleverer. It is six lines of data, it is obvious what it does, and adding a condition is one line. A semantic matcher would be more general and considerably harder to reason about when it produced a bad suggestion.

## Synthea's conditions are not all conditions

Two problems surfaced immediately, and both are about what Synthea puts in the `Condition` resource type.

The first is administrative noise. Synthea emits one `Medication review due` Condition per visit, so it is active, numerous, and often the most recent thing in the list. It describes no clinical problem:

```python
# src/api/suggestions.py
ADMINISTRATIVE_CONDITIONS = ("medication review due",)
```

The second is more interesting. Synthea records social determinants of health as active Conditions: "Unemployed", "Limited social contact", "Stress". These are legitimate clinical data, and in FHIR they are coded as findings rather than disorders. They are also frequently the *most recent* conditions on the record, so ordering by date buries the actual diagnoses underneath them.

And "When was Unemployed diagnosed?" reads wrong in a way that would undermine the whole interface.

The fix uses the SNOMED qualifier that is already in the rendered text. A disorder is `(disorder)`, a finding is `(finding)`:

```python
# src/api/suggestions.py
SOCIAL_QUALIFIERS = ("finding",)

def _condition_rank(name: str, qualifier: str) -> int:
    """Order conditions by how likely a reader is to ask about them."""
    lowered = name.lower()
    if any(keyword in lowered for keyword, _ in CONDITION_QUESTIONS):
        return 0
    if qualifier.lower() in SOCIAL_QUALIFIERS:
        return 2
    return 1
```

Rank 0 for conditions I have a specific question for, rank 2 for social findings, rank 1 for everything else. Then social findings are used only when there is nothing clinical to offer instead:

```python
# src/api/suggestions.py
ranked.sort(key=lambda item: item[0])
# "When was Unemployed diagnosed?" reads wrong. Social findings are kept
# only when the record has no clinical condition to offer instead.
clinical = [name for rank, name in ranked if rank < 2]
return clinical or [name for _, name in ranked]
```

The sort is stable, and the caller passes rows newest-first, so recency is preserved within each rank. That is a one-line property doing real work: within clinical conditions, the most recent still comes first.

## Naming the conditions steers retrieval

The first generated suggestion names the patient's actual conditions:

```python
# src/api/suggestions.py
# Naming the conditions explicitly is deliberate. A generic "active
# problems" question is answered from the retrieved chunks, and repeated
# administrative Conditions can occupy every slot; naming them retrieves
# the clinical rows instead.
if names:
    listed = ", ".join(names[:3])
    suggestions.append(
        f"What is the history of {listed} for this patient, and when was each diagnosed?"
    )
```

That comment is the interesting part, because it is a UI feature compensating for a retrieval weakness.

A generic "what are the active problems?" question used to retrieve twelve copies of `Medication review due`, because near-identical resources cluster in vector space and crowd out everything else. Naming the conditions puts their terms in the query, which retrieves them directly. I wrote about that failure in more detail earlier in this series.

I am ambivalent about this. It works, and it produces a better first interaction. It also means the interface is quietly routing around a defect rather than the defect being fixed, and a user who types their own generic question gets the old behaviour. I left it in with the comment explaining why, so that whoever fixes retrieval properly knows this is here.

## Budgets, so one thing does not crowd out everything

```python
# src/api/suggestions.py
MAX_SUGGESTIONS = 4
# Condition-specific questions are capped so that resource-driven ones
# (allergies, immunizations) still reach a patient with several diagnoses.
MAX_CONDITION_QUESTIONS = 2
```

Without the second cap, a patient with diabetes, hypertension, and obesity fills all four slots with condition questions and the allergy question never appears. Capping conditions at two guarantees the resource-driven questions get a slot, which keeps the suggestions covering different parts of the record rather than three angles on the same diagnosis.

The same crowding problem as the retrieval bug, at a different layer, with a much simpler fix available.

## Failing invisibly on the frontend

Suggestions are a convenience. If the endpoint fails, the user should still be able to ask a question:

```javascript
// src/frontend/app.js
try {
  const response = await fetch(`/api/suggestions${query}`);
  if (!response.ok) {
    throw new Error("Suggestions are unavailable.");
  }
  const payload = await response.json();
  this.examples = payload.suggestions || [];
} catch {
  // Suggestions are a convenience; a failure here must not block asking.
  this.examples = [];
}
```

And they refresh when the patient changes, because a suggestion describing the previous patient is worse than no suggestion:

```javascript
// src/frontend/app.js
// Suggestions describe the selected record, so they follow the picker.
this.$watch("selectedPatient", () => this.loadSuggestions());
```

## The takeaway

This is 128 lines of Python for a feature nobody would put on a roadmap, and it changed how the system feels more than any retrieval improvement did.

The generalisable idea: **your interface makes implicit claims about your data**. Every example, placeholder, and default is a promise that this input will work. When those promises are written statically and the data varies, some fraction of your users have a broken first experience through no fault of the system.

Deriving them from the data costs two indexed queries.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
