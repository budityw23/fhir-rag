---
title: "One Resource, One Chunk: FHIR-Aware Chunking Beats Token Windows"
published: false
tags: rag, fhir, chunking, embeddings
series: "Grounded RAG over FHIR"
---

The default chunking strategy in every RAG tutorial is a recursive character splitter with a 512-token window and 50 tokens of overlap. It is a reasonable default for prose. For FHIR records it is a mistake, and the reason is not about token counts at all.

Two things break. A resource split across two chunks loses the one property that makes citation possible, which is that a chunk maps to exactly one stable identifier. And two resources merged into one chunk put clinically unrelated facts into the same retrievable unit, so retrieving a blood pressure reading also drags in whatever immunization happened to sit next to it in the file.

FHIR already solved the chunking problem. I just had to not undo it.

## The chunk boundary is in the standard

A resource is a clinically meaningful unit. One diagnosis is one `Condition`. One lab result is one `Observation`. One prescription is one `MedicationRequest`. That granularity was designed by people modelling how clinicians think about records, which is a considerably better basis for a chunk boundary than a token count.

So my chunker does almost nothing:

```python
# src/ingestion/chunker.py
def chunk_resource(parsed: ParsedResource) -> FHIRChunk:
    """Convert a ParsedResource into a FHIRChunk with structured metadata."""
    return FHIRChunk(
        resource_id=parsed.resource_id,
        resource_type=parsed.resource_type,
        patient_ref=parsed.patient_ref or "",
        resource_date=extract_date(parsed.resource_json, parsed.resource_type),
        codes=extract_codes(parsed.resource_json),
        references=list(parsed.references),
        text_content=render_resource_text(parsed.resource_json, parsed.resource_type),
    )
```

No splitting, no overlap, no size heuristic. The interesting work is not deciding where to cut. It is deciding what metadata survives the cut.

## Metadata is the point

A text chunk with an opaque id is nearly useless for clinical questions, because most clinical questions have a structural component that similarity search cannot express. "This patient" is a filter. "Most recent" is a sort. "Which medications" is a type constraint. None of those are semantic.

So each chunk carries four pieces of structure alongside its text.

`patient_ref` is the highest-value filter in the system. Patient-scoped retrieval turns a search across 77,466 chunks into a search across a few hundred, which is both more accurate and, at 5 to 24 ms, roughly a hundred times faster than the unscoped version.

`resource_type` lets a question about medications exclude 41,837 observations up front.

`resource_date` supports the temporal half of clinical questions, which is most of them.

`references` holds outbound FHIR links, and it is what turns a flat chunk store into a walkable graph later.

## Dates are scattered across five field names

FHIR does not have a `date` field. It has `effectiveDateTime` on observations, `onsetDateTime` on conditions, `recordedDate` on allergies, `authoredOn` on medication requests, and `period.start` on encounters and care plans. Each is right for its resource type, and none of them is general.

Rather than write per-type extractors, I resolve them by priority:

```python
# src/ingestion/chunker.py
def extract_date(resource_json: dict, resource_type: str) -> datetime | None:
    """Extract the most relevant date from a resource.
    Priority: effectiveDateTime > onsetDateTime > recordedDate > authoredOn > period.start
    """
    del resource_type  # Part of the public API for resource-specific extensions.
    candidates = [
        resource_json.get("effectiveDateTime"),
        resource_json.get("onsetDateTime"),
        resource_json.get("recordedDate"),
        resource_json.get("authoredOn"),
        (resource_json.get("period") or {}).get("start")
        if isinstance(resource_json.get("period"), dict)
        else None,
    ]
    for candidate in candidates:
        parsed = _parse_datetime(candidate)
        if parsed is not None:
            return parsed
    return None
```

The ordering is not arbitrary. The fields are mutually exclusive in practice, so priority is really just "whichever one this resource type uses". Writing it as a priority list instead of a type dispatch means a resource type I have not thought about yet still gets a sensible date rather than `NULL`.

I kept the unused `resource_type` parameter deliberately. The moment a type needs special handling (`Procedure.performedPeriod` is the likely first), the signature does not have to change.

## Codes come out of the whole resource

Terminology codes are the retrieval signal that a text splitter throws away entirely, and they do not live in one place. A `MedicationRequest` has a coding on `medicationCodeableConcept`, another on `dosageInstruction[].route`, another on `reasonCode`. So extraction walks the entire resource:

```python
# src/ingestion/chunker.py
def walk(value):
    if isinstance(value, dict):
        coding = value.get("coding")
        if isinstance(coding, list):
            for item in coding:
                if not isinstance(item, dict) or not item.get("code"):
                    continue
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
```

Stored as JSONB, this gives every chunk a set of unambiguous concept identifiers. My evaluation questions use them as ground truth (question DX-001 expects SNOMED `44054006`), and terminology-aware filtering is the obvious next retrieval feature.

## What this looks like end to end

A Synthea `Observation` goes in:

```json
{
  "resourceType": "Observation",
  "id": "1a4d-...",
  "code": { "coding": [{ "system": "http://loinc.org", "code": "4548-4",
                         "display": "Hemoglobin A1c/Hemoglobin.total in Blood" }] },
  "subject": { "reference": "urn:uuid:8f2c-..." },
  "effectiveDateTime": "2024-06-15T09:22:00+07:00",
  "valueQuantity": { "value": 7.2, "unit": "%" }
}
```

And one chunk comes out:

```
resource_id:    Observation/1a4d-...
resource_type:  Observation
patient_ref:    Patient/8f2c-...
resource_date:  2024-06-15 09:22:00+07
codes:          [{"system": "http://loinc.org", "code": "4548-4", ...}]
text_content:   Observation: Hemoglobin A1c/Hemoglobin.total in Blood (LOINC: 4548-4).
                Value: 7.2 %.
                Date: 2024-06-15T09:22:00+07:00.
                Patient: Patient/8f2c-...
```

One row, one citable id, four filterable dimensions, and a text field an embedding model can actually use. The `urn:uuid` in `subject` has been normalised to a canonical patient reference, which is a whole trap of its own that the previous article covers.

That `text_content` field is where most of the retrieval quality gets decided, and it is the subject of the next article. A renderer that drops a field makes that field permanently uncitable, no matter how good your retrieval or your model is.

## The cost of this decision

Honest trade-off: one resource per chunk means near-duplicate resources produce near-duplicate vectors, and top-k retrieval has no defence against that.

Synthea emits one `Medication review due` Condition per visit. Twelve of them once occupied every Condition slot in a top-25 retrieval, and the answer to "what are this patient's active problems?" came back as a single administrative entry with the three real diagnoses nowhere in sight. The model described exactly what it was given.

A larger chunk that merged conditions would have masked that particular failure, at the cost of the citation precision the whole system is built on. The right fix is diversity-aware retrieval, either MMR re-ranking or collapsing candidates by `(resource_type, code)` before applying top-k. That is still on my list, and there is an article later in this series about how the problem surfaced.

## The takeaway

Before you reach for a text splitter, ask whether your source format already defines a unit. Structured formats usually do: a FHIR resource, a database row, a log event, a function definition. When they do, the splitter is not adding structure, it is destroying the structure you were handed.

Chunking is a hard problem for prose because prose has no natural boundaries. Do not import that difficulty into a format that does not have it.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
