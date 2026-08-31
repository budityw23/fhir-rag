# Why FHIR Makes a Better Foundation for Healthcare RAG Than Flat Tables

If you are building a Retrieval-Augmented Generation (RAG) system for clinical data, the first architectural decision you face is not which vector database to use or which embedding model to pick. It is something more fundamental: **how do you represent clinical data before it ever reaches the LLM?**

Most tutorials default to tabular data. Export your patient records to CSV, chunk the rows, embed them, done. It works for demos, but it quietly creates problems that surface the moment you try to handle real clinical questions.

After working with FHIR R4 in production healthcare systems and building a RAG pipeline over FHIR resources, I have come to believe that FHIR is a significantly better foundation for healthcare RAG. Here is why.

## 1. Each Resource Is Already a Meaningful Chunk

Chunking is one of the hardest problems in RAG. Chunk too small and you lose context. Chunk too large and you dilute relevance. With tabular data, you are forced to make arbitrary decisions: do you chunk by row, by patient, by date range?

FHIR solves this naturally. Each resource (an `Observation`, a `Condition`, a `MedicationRequest`) is already a clinically meaningful unit. It maps to how clinicians actually think about patient data. One blood pressure reading is one `Observation`. One diagnosis is one `Condition`. The granularity is built into the standard.

```json
{
  "resourceType": "Condition",
  "code": {
    "coding": [{
      "system": "http://snomed.info/sct",
      "code": "44054006",
      "display": "Type 2 diabetes mellitus"
    }]
  },
  "onsetDateTime": "2021-03-15",
  "clinicalStatus": {
    "coding": [{
      "code": "active"
    }]
  }
}
```

This chunk carries its own meaning. A flat table row like `| 44054006 | 2021-03-15 | active |` does not.

## 2. Semantic Structure That the LLM Can Actually Use

A row in a table is just positional data. The meaning lives in the column headers, and those headers are not embedded alongside each row in most RAG pipelines.

A FHIR resource is self-describing. The field names (`clinicalStatus`, `onsetDateTime`, `verificationStatus`) carry semantic weight. When the LLM retrieves a FHIR Condition resource, it can reason about what "active" means in the context of `clinicalStatus` without needing a separate schema definition injected into the prompt.

This matters more than it sounds. In tabular RAG, you either burn prompt tokens explaining the schema every time, or you hope the model infers the right meaning from ambiguous column names like `status` or `code`. With FHIR, the structure *is* the explanation.

## 3. Terminology Bindings Give You Precision

When a clinician asks "does this patient have diabetes?", a tabular system has to match against whatever string happens to be in the diagnosis column. Maybe it says "Type 2 DM." Maybe it says "Diabetes mellitus, type II." Maybe it says "E11.9" with no display text at all.

FHIR resources bind to standard terminologies: SNOMED CT, LOINC, ICD-10, RxNorm. The `Condition` resource above does not just say "diabetes" in free text. It carries the SNOMED code `44054006`, which unambiguously means Type 2 diabetes mellitus across any system in the world.

This opens up a powerful retrieval strategy: instead of relying purely on semantic similarity (which can miss or hallucinate), you can combine vector search with terminology-aware filtering. Retrieve by embedding similarity, then validate against the actual coded concepts. Hybrid retrieval with clinical precision.

## 4. References Create a Traversable Knowledge Graph

Clinical data is relational. A lab result belongs to an encounter, which belongs to a patient, which has a care team. In a flat table, those relationships are foreign keys that your RAG pipeline has to know how to JOIN. And deciding *which* JOINs matter for a given query is itself a hard problem.

FHIR makes these relationships explicit through `Reference` fields:

```json
{
  "resourceType": "MedicationRequest",
  "subject": { "reference": "Patient/123" },
  "encounter": { "reference": "Encounter/456" },
  "requester": { "reference": "Practitioner/789" }
}
```

When your RAG system retrieves a `MedicationRequest`, it can follow those references to pull in the relevant `Patient`, `Encounter`, and `Practitioner` resources as additional context. No JOIN logic, no schema knowledge. Just follow the links.

This reference-based traversal is especially powerful for clinical questions that span multiple resource types: "What medications was this patient prescribed during their last hospital admission?" requires connecting `MedicationRequest` to `Encounter` to `Patient`. In FHIR, the path is explicit. In a tabular system, you need a query planner.

## 5. Nested and Polymorphic Data Stays Intact

Clinical data is inherently messy and nested. A single blood pressure reading has two components (systolic and diastolic). An observation's value might be a number, a code, a string, or a ratio depending on the test type. A medication dosage has timing, route, and dose quantity as sub-structures.

Tables flatten all of this. You end up with columns like `value_quantity`, `value_code`, `value_string`, `component_1_code`, `component_1_value` and the structural meaning disappears.

FHIR preserves the nesting:

```json
{
  "resourceType": "Observation",
  "code": {
    "coding": [{ "code": "85354-9", "display": "Blood pressure" }]
  },
  "component": [
    {
      "code": { "coding": [{ "code": "8480-6", "display": "Systolic" }] },
      "valueQuantity": { "value": 130, "unit": "mmHg" }
    },
    {
      "code": { "coding": [{ "code": "8462-4", "display": "Diastolic" }] },
      "valueQuantity": { "value": 85, "unit": "mmHg" }
    }
  ]
}
```

When this reaches the LLM, it can see that 130 is systolic and 85 is diastolic. A flat row with `| 130 | 85 |` requires the model to guess which is which from column headers that may or may not be present in the retrieved chunk.

## 6. Interoperability Means Your Pipeline Is Portable

If you build RAG on a proprietary table schema, your pipeline works for exactly that database. Change the source system, and you rebuild your chunking, your embeddings, your retrieval logic.

FHIR R4 is a global standard. A `Patient` resource from Hospital A has the same structure as one from Hospital B. Your embedding model learns the FHIR schema once. Your retrieval logic works across any FHIR-compliant source. Your chunking strategy is defined by the standard, not by the source system's table design.

This is not just a theoretical benefit. In multi-site research networks (which I work with), the ability to run the same RAG pipeline across sites without per-site customization is a real operational advantage.

## The Honest Trade-Off: Verbosity

FHIR is verbose. A single Condition resource can be 40-50 lines of JSON where a table row might be 5 columns. This means:

- **Embedding cost is higher.** More tokens per chunk means more embedding API calls.
- **Context window usage is less efficient.** When you retrieve 5 FHIR resources as context, you consume more tokens than 5 table rows.
- **Chunk size tuning matters more.** You may need to selectively flatten or summarize FHIR resources before embedding, keeping only the fields that are useful for retrieval.

These are real engineering challenges. But they are tractable. You can create lean representations for embedding while keeping full resources for context injection. The semantic advantages of FHIR are structural. The verbosity problem is operational.

## A Practical Architecture

Here is a simplified version of how this works in practice:

1. **Ingest** FHIR bundles (from Synthea for development, from real EHRs in production)
2. **Parse** each resource using a FHIR library (e.g., `fhir.resources` in Python)
3. **Generate embeddings** from a lean text representation of each resource
4. **Store** vectors in pgvector alongside the full FHIR JSON
5. **Retrieve** by semantic similarity, optionally filtered by resource type or terminology code
6. **Traverse** FHIR references to pull in related resources as additional context
7. **Generate** the answer with the LLM, grounded in the retrieved FHIR data

The key insight is that FHIR gives you step 1 through 6 almost for free. With tabular data, every step requires custom decisions about schema mapping, JOIN logic, and chunk boundaries.

## Conclusion

The choice of data representation is upstream of every other decision in your RAG pipeline. It affects chunking, retrieval quality, context richness, and ultimately the accuracy of the LLM's clinical reasoning.

FHIR is not just a data format. It is a shared clinical ontology with built-in semantics, terminology bindings, and reference links. When you build RAG on FHIR, you inherit all of that structure. When you build RAG on flat tables, you have to reconstruct it yourself, often imperfectly.

If you are building healthcare RAG systems, start with FHIR. The standard has already solved problems you have not thought of yet.

---

*I am building a FHIR RAG system as an open-source project. If you are working in healthcare interoperability or clinical AI, I would love to connect. Find me on [dev.to](https://dev.to) or [chat.fhir.org](https://chat.fhir.org).*
