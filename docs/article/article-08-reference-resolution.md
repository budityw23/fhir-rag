---
title: "Following the Graph: Two-Hop FHIR Reference Resolution as Free Context"
published: false
tags: fhir, rag, graphrag, python
series: "Grounded RAG over FHIR"
---

"What was his BMI percentile at the most recent well-child visit?"

Vector search retrieves the BMI `Observation`. That is the resource the question is semantically about, and retrieval does its job. The answer still cannot be produced, because "well-child visit" is a property of the `Encounter` the observation was recorded at, and nothing in the BMI observation's text says which visit that was.

The information is one link away. FHIR resources carry their own outbound references, so following that link costs one indexed lookup, not a query planner.

## Store the references at ingestion

The graph walk only works if the edges are already in the database. During parsing I collect every `Reference` in the resource, normalise it to canonical form, and store the result as a `TEXT[]`:

```python
# src/ingestion/fhir_parser.py
def extract_references(resource: dict, reference_map: dict | None = None) -> list[str]:
    """Walk resource JSON and collect all Reference values."""
    def walk(value):
        if isinstance(value, dict):
            reference = _reference_value(value)
            if reference:
                normalized = _normalize_reference(reference, reference_map)
                if normalized not in extracted:
                    extracted.append(normalized)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    extracted: list[str] = []
    walk(resource)
    return extracted
```

Two details matter here. The walk is recursive over the whole resource rather than reading known fields, because references appear nested at several depths (`subject`, `encounter`, `requester`, `reasonReference`, `performer[].actor`) and the set differs per resource type.

And `_normalize_reference` is doing essential work. Synthea writes references as `urn:uuid:...` pointing at a Bundle entry's `fullUrl`, not as `ResourceType/id`. Storing those raw gives you edges that point at nothing. The parser builds a Bundle-local map from `fullUrl` to canonical id and rewrites every reference through it, which I covered in more detail in the FHIR-for-ML-engineers article earlier in this series.

## The walk

Breadth-first, deduplicating against everything already seen, capped at two hops:

```python
# src/retrieval/reference_resolver.py
async def resolve_references(pool, results: list[SearchResult], max_hops: int = 2):
    """Follow FHIR references from search results. Returns additional resources.
    Does not duplicate resources already in results.
    """
    if max_hops <= 0 or not results:
        return []

    seen = {result.resource_id for result in results}
    supplementary: list[SearchResult] = []
    frontier = _unique_references(results, seen)

    for _ in range(max_hops):
        if not frontier:
            break
        rows = await pool.fetch(REFERENCE_QUERY, frontier)
        found: list[SearchResult] = []
        for row in rows:
            resource_id = row["resource_id"]
            if resource_id in seen:
                continue
            seen.add(resource_id)
            found.append(result_from_row(row, similarity=0.0))
        supplementary.extend(found)
        frontier = _unique_references(found, seen)

    return supplementary
```

Fifty-two lines including the query and the helper. Each hop is a single round trip, because the frontier is fetched as a batch:

```sql
-- src/retrieval/reference_resolver.py
SELECT resource_id, resource_type, patient_ref, resource_date,
       codes, "references", text_content
FROM fhir_chunks
WHERE resource_id = ANY($1)
```

`resource_id` is indexed and unique, so a hop over a frontier of forty references is one index scan, not forty. Two hops from a top-25 result set is two queries, and both land in single-digit milliseconds.

The `seen` set is seeded with the primary results and grows as the walk proceeds, which does double duty: it prevents cycles (FHIR references are frequently reciprocal in effect, and Patient is reachable from everything) and it prevents re-presenting a resource the vector arm already found.

## Marking supplementary context

A resolved resource is not the same kind of thing as a retrieved one. It did not match the question. It is there because something that matched pointed at it. Presenting both to the model as equally relevant invites the model to answer from the wrong one.

So the context builder labels them differently:

```python
# src/retrieval/context_builder.py
def _render_grouped(results: list[SearchResult], primary: bool) -> list[str]:
    lines: list[str] = []
    for resource_type, grouped in _group_by_type(results).items():
        lines.append(f"-- {resource_type} --")
        for result in grouped:
            if primary:
                lines.append(f"[{result.resource_id}] (similarity: {result.similarity:.2f})")
            else:
                lines.append(f"[{result.resource_id}] (supporting context)")
            lines.append(result.text_content)
            lines.append("")
    return lines
```

Which produces a context block shaped like this:

```
=== Retrieved FHIR Resources (ranked by relevance) ===

-- Observation --
[Observation/1a4d-...] (similarity: 0.71)
Observation: Body mass index (BMI) [Percentile] Per age and sex (LOINC: 59576-9).
Value: 62.4 %.
Date: 2025-11-03T10:15:00+07:00.
Patient: Patient/8f2c-...

=== Supporting FHIR Resources (resolved references) ===

-- Encounter --
[Encounter/9c1b-...] (supporting context)
Encounter: Well child visit (procedure) (SNOMED: 410620009).
Status: finished.
Date: 2025-11-03T10:00:00+07:00.
Patient: Patient/8f2c-...
```

Now the question is answerable, and both resources are citable because both carry their id.

Grouping by resource type is a small thing that helps more than it should. A flat list of 25 chunks in similarity order is hard to reason over. Grouped, the model can see at a glance that it has eleven observations, three conditions, and one encounter, which makes aggregate questions ("which medications") noticeably more reliable.

## Why two hops

`MAX_REFERENCE_HOPS` is configurable and defaults to 2. That number is empirical rather than principled.

One hop covers the cases that motivated the feature: observation to encounter, medication request to condition, procedure to encounter. Two hops covers a chain worth having, typically observation to encounter to a second observation recorded at the same visit.

Three hops does not pay. FHIR graphs are dense, and by the third hop the frontier expands into most of the patient's record. You are no longer adding context, you are undoing the retrieval step and filling the prompt with noise, which costs tokens and dilutes the model's attention on the resources that actually matched.

The `similarity=0.0` on resolved resources is deliberate for the same reason. They did not earn a similarity score, and giving them a fabricated one would let them be mistaken for good matches by anything downstream that sorts.

## What this is and is not

This is graph traversal, not graph reasoning. There is no path-finding, no ranking of edges, no query planner deciding which relationships matter. It is "fetch the neighbours, twice", and the reason such a blunt approach works is that FHIR references are already curated. A resource points at another resource because a clinical system decided they are related. That is a much higher-quality edge than anything you would infer from co-occurrence or embedding similarity.

A real graph RAG approach would rank the edges, or learn which reference types matter for which questions. I have not needed it. The cheap version answers the cross-resource questions in my evaluation set, and the ones it misses (`cross_resource` recall sits at 0.83) fail because one of the two expected resource types was never retrieved in the first place, not because the traversal was too shallow.

That is the general shape of it: if your data format already encodes relationships, walking them is nearly free and worth doing before you reach for anything more sophisticated.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
