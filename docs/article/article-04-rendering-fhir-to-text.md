---
title: "Embeddings Do Not Read JSON: Rendering FHIR Resources Into Text"
published: false
tags: fhir, embeddings, rag, python
series: "Grounded RAG over FHIR"
---

The allergy question came back almost right. It listed all seven of the patient's allergens correctly, with citations, and then finished with: "Insufficient data in the available FHIR resources to determine the specific reactions."

The reactions were in the record. Seven `AllergyIntolerance` resources, each with a populated `reaction` array. Retrieval had found every one of them. The model had cited every one of them. And the reactions still were not there, because they had never been written into the text the model was given.

Between the FHIR JSON and the embedding model sits a rendering layer that nobody writes articles about. It is where most of your retrieval quality is decided, and it is where the bugs are hardest to see.

## What a model sees when you feed it JSON

You can embed raw JSON. It produces vectors. They are not good vectors.

An embedding model trained on natural language is being asked to interpret `"valueQuantity":{"value":7.2,"unit":"%"}` as a clinical fact. Half the tokens are syntax. Field names carry meaning but are wrapped in quotes and braces that the model has to see through. And the parts a clinician would consider central (the code display, the value, the date) are buried at inconsistent depths depending on resource type.

So each resource gets rendered to a sentence-shaped string first:

```
Observation: Hemoglobin A1c/Hemoglobin.total in Blood (LOINC: 4548-4).
Value: 7.2 %.
Date: 2024-06-15T09:22:00+07:00.
Patient: Patient/8f2c-...
```

Same facts, no syntax, and the code and its system are preserved inline so a query mentioning either the name or the code can match. That string is what gets embedded, what gets indexed for full text, and what the model sees at generation time. It is the whole surface area of a resource, and anything left out of it does not exist as far as the rest of the system is concerned.

## Ten renderers, one signature

Dispatch is a dict lookup with a generic fallback:

```python
# src/ingestion/text_renderer.py
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
```

Per-type functions rather than one clever generic renderer, because the types genuinely differ. An Observation needs its value. A MedicationRequest needs its dosage. A CarePlan needs its activities. There is no shared abstraction that captures that without becoming a configuration language, and I would rather have ten short functions I can read than one long one I cannot.

Each renderer follows the same shape: pull the code, pull the status, pull the date, add type-specific detail, end with the patient reference.

```python
# src/ingestion/text_renderer.py
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
```

## The path walker, and the array trap

The shared helper is `_first_coding`, which walks a dotted path and returns the first usable coding it finds. My original version assumed every path ended at a single CodeableConcept.

That assumption is wrong, and FHIR does not warn you. `Condition.code` is a single CodeableConcept. `Encounter.type` is an *array* of them. So the `isinstance(value, dict)` check failed on every Encounter in the database, and all of them rendered as:

```
Encounter: unspecified.
```

Nine thousand encounters, every one of them describing nothing. The symptom surfaced through a question about a BMI percentile at a well-child visit, which failed with "all Encounters are listed as unspecified". That was the model reporting accurately on garbage input.

The fix is three lines, and it is worth reading with its comment because the comment is the actual lesson:

```python
# src/ingestion/text_renderer.py
# Several FHIR fields (Encounter.type, AllergyIntolerance.reaction[].
# manifestation) are arrays of CodeableConcept rather than a single
# one; without this the walk yields "unspecified" for every Encounter.
if isinstance(value, list):
    value = next((item for item in value if isinstance(item, dict)), None)
codings = value.get("coding", []) if isinstance(value, dict) else []
```

Encounters now render as `Encounter: Well child visit (procedure) (SNOMED: 410620009).`

## The bug I opened with

The allergy renderer was worse, because it was not broken. It was incomplete, which is harder to spot. It emitted code, status, and patient, and simply never looked at `reaction`, `criticality`, or `category`.

Rendering a reaction is not one field access. `reaction` is an array, each reaction has an array of `manifestation` CodeableConcepts, and a manifestation is allowed to carry only free text with no coding at all:

```python
# src/ingestion/text_renderer.py
def _reaction_text(reaction: dict) -> str | None:
    """Render one reaction as its manifestations plus optional severity."""
    manifestations = []
    for item in reaction.get("manifestation", []):
        if not isinstance(item, dict):
            continue
        coding = _first_coding({"m": item}, "m")
        if coding is not None:
            manifestations.append(_coded_text(coding))
            continue
        # FHIR allows a CodeableConcept carrying only free text; without this
        # the manifestation is dropped as "unspecified" and the reaction is
        # rendered with no detail at all.
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            manifestations.append(text.strip())
    if not manifestations:
        return None
    severity = reaction.get("severity")
    rendered = _join(manifestations)
    return f"{rendered} ({severity})" if isinstance(severity, str) and severity else rendered
```

Before, the stored text for an allergy was two lines:

```
AllergyIntolerance: Mold (organism) (SNOMED: 84489001).
Status: active.
```

After:

```
AllergyIntolerance: Mold (organism) (SNOMED: 84489001).
Status: active.
Category: environment.
Criticality: low.
Reactions: Cutaneous hypersensitivity (disorder) (SNOMED: 21626009) (mild); ...
Recorded: 2021-08-14.
Patient: Patient/...
```

Same retrieval, same model, same prompt. The question that had been unanswerable became a grounded answer with seven citations, because the answer was finally in the text.

## Read the stored text before blaming the model

Both of these bugs presented as generation failures. The answer named the right entities and then said it could not determine an attribute, which reads exactly like a model being overly cautious. The instinct is to adjust the prompt, or reach for a bigger model.

Neither would have helped. The model was reasoning correctly over text that did not contain the answer.

So there is now a check I run before touching retrieval or the prompt:

```bash
docker compose exec -T db psql -U fhir -d fhir_rag -c \
  "SELECT text_content FROM fhir_chunks WHERE resource_id = 'AllergyIntolerance/...'"
```

That output is the exact string the model saw. If the fact is not in there, nothing downstream can produce it, and every minute spent on prompts or retrieval is wasted. If it is in there, then you have a real retrieval or reasoning question to investigate.

The general form of the rule: when an answer is *partially* right, with correct entities but missing attributes, suspect the renderer first. Fully wrong entities point at retrieval. Right entities with missing detail point at what you wrote into the chunk.

## What I would do differently

I would write the renderers against a checklist of the fields each resource type actually uses in my corpus, rather than against my memory of the spec. A one-line query per type would have caught the allergy gap on day one:

```sql
SELECT jsonb_object_keys(resource) FROM raw_resources WHERE resource_type = 'AllergyIntolerance';
```

I did not keep the raw JSON, which is a decision I would revisit. Rendering is lossy by design, and having the source next to the render would have made both of these bugs a five-minute diff instead of a debugging session.

The next article in the series moves down a layer, into pgvector: the schema these rendered strings land in, why HNSW over IVFFlat, and the failure where a perfectly valid patient filter returned zero rows from a table full of matches.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
