---
title: "FHIR RAG Is Not Document RAG, and the Difference Starts at Ingestion"
published: false
tags: rag, fhir, healthcare, architecture
series: "Grounded RAG over FHIR"
---

Point a standard RAG stack at a folder of FHIR bundles and it will run. It will chunk the JSON, embed the chunks, retrieve by similarity, and produce answers. Some of them will be right.

It will also be the wrong architecture, and the reason is not that FHIR is exotic. It is that document RAG and record RAG are solving different retrieval problems, and almost every default in the document stack encodes an assumption that clinical records violate.

## Passages versus records

Document RAG has one job: find the passage that contains the answer. The corpus is prose, the unit is a span of text, and the measure of success is whether the retrieved span says what the user asked about.

Record RAG has a different job: assemble the *set* of records that, taken together, support an answer. "What diabetes medications is this patient on?" is not answered by one record. It is answered by all the `MedicationRequest` resources with an active status, and being wrong means missing one, not retrieving the wrong one.

That difference propagates everywhere. Document RAG's top-k is "the k most likely to contain the answer". Record RAG's top-k is "hopefully all the members of a set whose size I do not know in advance". Those are not the same operation, and top-k similarity search is a much better fit for the first.

It also means the failure modes differ. My worst retrieval failure was not retrieving something irrelevant. It was retrieving twelve copies of the same administrative record and crowding out three real diagnoses, which is a set-completeness failure that has no real analogue in document search.

## Structured filters do work similarity cannot

Look at what a clinical question actually asks for:

```python
# src/retrieval/hybrid_search.py
async def hybrid_search(
    pool,
    query_embedding: list[float],
    query_text: str | None = None,
    patient_ref: str | None = None,
    resource_types: list[str] | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    top_k: int = 10,
) -> list[SearchResult]:
```

Two of those parameters are semantic. Four are structural, and they carry more weight than the semantic ones.

"This patient" is not a similarity relation. It is an equality filter, and it is the single highest-value operation in the system: scoping to one patient turns a search across 77,466 chunks into a search across a few hundred, and takes retrieval from over a second to under 25 milliseconds. No embedding model can approximate that, and if you leave it out, a question about one person is answered from everybody.

"Most recent" is a sort on a timestamp. "Which medications" is a type constraint that excludes 41,837 observations before ranking begins.

Document RAG has metadata filtering as an optional feature you bolt on. For clinical records it is load-bearing, and it wants to be in the same query as the vector search so the planner can use it, which is a large part of why the vectors live in Postgres rather than in a dedicated store.

## Citations point at ids, not page numbers

A document citation is a locator. "Page 47" tells a human where to look, and its correctness cannot be checked mechanically without re-reading the source.

A record citation is an identifier, and identifiers can be verified:

```python
# src/generation/citation_mapper.py
resources = {
    (r.resource_type.lower(), r.resource_id.split("/", 1)[-1].lower()): r
    for r in available_resources
}
for resource_type, resource_id in matches:
    resource = resources.get((resource_type.lower(), resource_id.lower()))
    if resource is None:
        continue
    valid_count += 1
```

`Observation/1a4d-...` either was retrieved or was not. That is a dictionary lookup, and it means the system can tell the user whether an answer's evidence holds up, without a human checking.

This is the strongest argument for record RAG over document RAG in any high-stakes domain, and it depends entirely on a chunking decision: one resource, one chunk, so a citation names exactly one thing. Split a resource across chunks and the id no longer identifies a retrievable unit. Merge two and a citation is ambiguous.

## Codes are a retrieval signal a splitter discards

Every clinically meaningful field in FHIR is bound to a terminology. Diabetes is SNOMED `44054006` whether the record says "Type 2 DM", "Diabetes mellitus type II", or nothing at all in the display field.

A text splitter sees those as strings and throws away the distinction between a code and a word. I extract them into a queryable column instead:

```python
# src/ingestion/chunker.py
codes=extract_codes(parsed.resource_json),
```

Stored as JSONB, walked recursively out of the whole resource, and used as ground truth in evaluation. Terminology-aware filtering (retrieve by embedding, then validate against the coded concept) is the obvious next retrieval feature and it has no equivalent in document RAG, because prose has no codes.

The general form: **structured source formats carry signals that are invisible after chunking**. Extract them before you flatten, or they are gone.

## References are edges, not citations

In a document corpus, one document referencing another is a weak signal you might exploit. In FHIR, references are the skeleton. An observation belongs to an encounter, a medication request treats a condition, everything belongs to a patient.

Because those edges are stored on the resource, following them is cheap:

```python
# src/retrieval/reference_resolver.py
rows = await pool.fetch(REFERENCE_QUERY, frontier)
```

One indexed batch lookup per hop. A "well-child visit" qualifier that lives on the `Encounter` becomes available to a question about a BMI `Observation` for the price of a millisecond.

Document RAG has nothing like this. The closest analogue is a knowledge graph you have to *build*, usually by extracting entities and relations with an LLM, at real cost and real error rate. FHIR hands you a curated graph where every edge was asserted by a clinical system.

## Where document RAG techniques still apply

I do not want to overstate this. Plenty transfers.

Hybrid retrieval is a document RAG idea and it is essential here. My vector arm misses questions that name a resource type outright, and a `tsvector` arm catches them. Reciprocal Rank Fusion is from the information retrieval literature and works unchanged.

Re-ranking would help and I have not implemented it. Query expansion helps; I do a crude version, mapping "HbA1c" to "hemoglobin a1c" before embedding, because the abbreviation and the display name share no tokens.

And the diversity problem I hit (near-identical chunks occupying every slot) has a well-known document RAG solution in MMR that applies directly.

The pattern is that **retrieval algorithms transfer, and pipeline assumptions do not**. Ranking and fusion are general. Chunking strategy, metadata design, and citation format are where the source format asserts itself.

## The practical difference

If you are pointing a RAG stack at clinical records, three changes get you most of the way.

Chunk on the resource boundary, not on token count. The format already defines the unit.

Put the structural fields in columns, not in an opaque metadata blob, and filter on them in the same query as the vector search. Patient, type, and date do more work than the embedding does.

Make citations verifiable by making chunk ids meaningful, then actually verify them rather than trusting the model's formatting.

None of that is exotic. It is mostly *not* doing things the document RAG defaults would do for you.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
