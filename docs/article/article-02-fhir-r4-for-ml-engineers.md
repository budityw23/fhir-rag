---
title: "FHIR R4 for ML Engineers: What Actually Lives in a Patient Record"
published: false
tags: fhir, healthcare, machinelearning, rag
series: "Grounded RAG over FHIR"
---

Every RAG tutorial starts with a folder of PDFs. You split them, embed the splits, and search. The mental model is a pile of prose, and the retrieval problem is finding the right paragraph.

A FHIR record is not a pile of prose. It is a graph of typed, coded, cross-referencing objects, where the meaning of any one node depends on nodes it points at. If you bring the document-RAG mental model to it, you will build something that technically runs and quietly answers the wrong questions.

Here is what is actually in there, written for someone who knows embeddings and has never opened a patient chart.

## A Bundle is not a document

The unit you get handed is a **Bundle**: a JSON envelope with an `entry` array. Each entry has a `fullUrl` and a `resource`. The resources are not sections of one document. They are independent records that happen to have been shipped together.

```json
{
  "resourceType": "Bundle",
  "entry": [
    { "fullUrl": "urn:uuid:8f2c...", "resource": { "resourceType": "Patient", "id": "8f2c..." } },
    { "fullUrl": "urn:uuid:1a4d...", "resource": { "resourceType": "Observation", "id": "1a4d..." } }
  ]
}
```

That distinction matters immediately. There is no document order to preserve, no narrative flow to keep intact across a chunk boundary, and no reason to concatenate entries. Each resource stands alone, which is why my ingestion treats one resource as one chunk and stops there.

## The types that carry clinical meaning

FHIR R4 defines over 140 resource types. For question answering over a patient record, ten of them do almost all the work:

```python
# src/ingestion/fhir_parser.py
SUPPORTED_TYPES = [
    "Patient", "Condition", "Observation", "MedicationRequest",
    "Encounter", "AllergyIntolerance", "Procedure", "DiagnosticReport",
    "Immunization", "CarePlan",
]
```

Roughly: `Condition` is a diagnosis or problem. `Observation` is a measured value (a lab result, a vital sign, a BMI percentile). `MedicationRequest` is a prescription. `Encounter` is a visit. `Procedure` is something done to the patient. `DiagnosticReport` groups observations into a report. `CarePlan` is the plan of care.

In a real Synthea corpus, `Observation` outnumbers everything else by an order of magnitude. My 78-patient corpus indexed 41,837 observations against 2,791 conditions and 3,416 medication requests. That imbalance is not a quirk of synthetic data. Real records look like that too, and it means a naive top-k retrieval is heavily biased toward lab values unless you do something about it.

The types I skip are just as informative: `Provenance`, `Claim`, `ExplanationOfBenefit`, `Organization`. They are billing and audit infrastructure. They are enormous, they are numerous, and no clinician asks questions of them.

## CodeableConcept, and why `display` is not a label

This is the single data structure you have to internalise. Almost every clinically meaningful field in FHIR is a **CodeableConcept**: a set of codings from standard terminologies, optionally with free text.

```json
"code": {
  "coding": [{
    "system": "http://snomed.info/sct",
    "code": "44054006",
    "display": "Diabetes mellitus type 2"
  }]
}
```

Three things trip people up.

First, `coding` is an array. The same concept can be coded in SNOMED CT and ICD-10 and a local system simultaneously. Taking `coding[0]` is a heuristic, not a rule.

Second, `display` is a convenience string, not an identifier. It is allowed to be absent, allowed to be a local translation, and allowed to disagree with what the code actually means. The code plus its system is the fact. The display is a hint.

Third, and this is the one that cost me a real bug: some fields are a single CodeableConcept and some are an *array* of them. `Condition.code` is singular. `Encounter.type` is plural. My path walker assumed singular, so every single Encounter in the database rendered as `Encounter: unspecified.` until I fixed it:

```python
# src/ingestion/text_renderer.py
# Several FHIR fields (Encounter.type, AllergyIntolerance.reaction[].
# manifestation) are arrays of CodeableConcept rather than a single
# one; without this the walk yields "unspecified" for every Encounter.
if isinstance(value, list):
    value = next((item for item in value if isinstance(item, dict)), None)
codings = value.get("coding", []) if isinstance(value, dict) else []
```

Read the spec page for the specific field. There is no general rule.

## The terminologies, briefly

Three code systems cover most of what you will see, and knowing which is which tells you what a resource is about before you read it:

- **SNOMED CT** for clinical findings, conditions, and procedures. `http://snomed.info/sct`.
- **LOINC** for lab tests and measurements. `http://loinc.org`. If you see LOINC `4548-4`, that is hemoglobin A1c.
- **RxNorm** for medications. `http://www.nlm.nih.gov/research/umls/rxnorm`.

I flatten these into a queryable JSONB column at ingestion, walking the whole resource recursively rather than looking in specific places, because codings show up nested at several depths:

```python
# src/ingestion/chunker.py
def extract_codes(resource_json: dict) -> list[dict]:
    """Extract all coded values (SNOMED, LOINC, RxNorm) from a resource."""
    codes: list[dict] = []

    def walk(value):
        if isinstance(value, dict):
            coding = value.get("coding")
            if isinstance(coding, list):
                for item in coding:
                    if isinstance(item, dict) and item.get("code"):
                        code = {"system": item.get("system", ""),
                                "code": item["code"],
                                "display": item.get("display", "")}
                        if code not in codes:
                            codes.append(code)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(resource_json)
    return codes
```

These codes are a retrieval signal that a text splitter throws away, and they are the difference between matching "diabetes" as a string and matching the concept regardless of how it was spelled.

## References, and the `urn:uuid` trap

Resources point at each other through `Reference` objects, which contain a `reference` string:

```json
{
  "resourceType": "MedicationRequest",
  "subject": { "reference": "Patient/123" },
  "encounter": { "reference": "Encounter/456" }
}
```

That looks simple, and inside a Bundle it is not. Synthea (and plenty of real systems) writes references as `urn:uuid:...` pointing at the entry's `fullUrl`, not as canonical `ResourceType/id`. If you store the reference string as it appears, your foreign keys point at nothing, and patient-scoped retrieval silently misses records.

The fix is to build a Bundle-local map from `fullUrl` to canonical id while parsing, then normalise every reference through it:

```python
# src/ingestion/fhir_parser.py
def _reference_map(entries: list) -> dict[str, str]:
    """Map Bundle fullUrls to canonical FHIR resource IDs."""
    references: dict[str, str] = {}
    for entry in entries:
        full_url = entry.get("fullUrl")
        resource = entry.get("resource")
        if not isinstance(full_url, str) or not isinstance(resource, dict):
            continue
        resource_id = _resource_id(resource, resource.get("resourceType"))
        if resource_id:
            references[full_url] = resource_id
    return references
```

This is also why I parse Bundles as raw JSON instead of running them through a validating FHIR model library. The library discards `fullUrl` context by the time you have objects, whole-Bundle validation on large Synthea bundles is slow enough to stall ingestion outright, and some emitted fields do not match the installed model version. Strict validation belongs at API boundaries. For bulk ingestion I want tolerant parsing plus explicit checks.

## The patient link is not one field

You would expect every resource to reference its patient the same way. It does not. Most use `subject`, some use `patient`, and `Patient` itself is its own answer:

```python
# src/ingestion/fhir_parser.py
def resolve_patient_ref(resource, resource_type, reference_map=None):
    if resource_type == "Patient":
        return _resource_id(resource, resource_type)
    # FHIR resources use either subject or patient for their patient link.
    for field in ("subject", "patient"):
        reference = _reference_value(resource.get(field))
        if reference:
            return _normalize_reference(reference, reference_map)
    return None
```

Nine lines, and they are load-bearing. Patient scoping is the highest-value filter in the whole system. Without it, a question about one person is answered from all 78 people in the corpus.

## What Synthea gives you, and where it lies

[Synthea](https://synthetichealth.github.io/synthea/) generates synthetic patients with realistic disease progression, and it is the right way to develop against FHIR without touching real data. It is also not real data, in ways that will bite you.

It emits administrative records with clinical resource types. One `Medication review due` Condition per visit, dozens per patient, all nearly identical. It records social determinants ("Unemployed", "Limited social contact") as active Conditions, which are often the most *recent* conditions, so ordering a problem list by date buries the actual diagnoses. And its coverage of clinical workflows is uneven: there is no continuous glucose monitor history, no insulin pump model.

None of that makes it useless. It makes it a corpus with known distortions, which is arguably better for development than a corpus with unknown ones.

## What this changes about your pipeline

If you take one thing from this: the structure is not overhead you have to strip before embedding. It is signal you get for free, and every part of it maps to a design decision. Resource type becomes a filter. Codes become a second retrieval signal. References become a graph you can walk for context. Resource ids become citation targets.

The next article in the series makes the chunking argument in full, and shows what happens when you ignore all of that and reach for a recursive character splitter instead.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
