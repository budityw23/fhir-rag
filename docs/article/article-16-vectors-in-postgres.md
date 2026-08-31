---
title: "Why I Put the Vector Index in Postgres Instead of a Vector Database"
published: false
tags: postgres, pgvector, architecture, rag
series: "Grounded RAG over FHIR"
---

The default advice for building RAG is to pick a vector database. Pinecone, Weaviate, Qdrant, Milvus, whichever. The vector store is presented as the core of the system and everything else arranges itself around it.

I put the vectors in Postgres with pgvector, and the reason has almost nothing to do with vector search performance. It is that most of the queries my system runs are not vector queries at all.

## The queries that are not vector queries

Here is everything my application asks the database to do.

Retrieve resources semantically similar to a question, filtered by patient, type, and date. That is the vector query, and it is the only one.

Then: fetch a batch of resources by exact id, to follow FHIR references.

```sql
-- src/retrieval/reference_resolver.py
SELECT resource_id, resource_type, patient_ref, resource_date,
       codes, "references", text_content
FROM fhir_chunks
WHERE resource_id = ANY($1)
```

List the distinct patients in the corpus, for the picker.

```sql
-- src/api/routes.py
SELECT DISTINCT ON (patient_ref) patient_ref, text_content
FROM fhir_chunks
WHERE resource_type = $1
ORDER BY patient_ref
```

Find one patient's active conditions, newest first, to generate example questions.

```sql
-- src/api/routes.py
SELECT text_content FROM fhir_chunks
WHERE patient_ref = $1
  AND resource_type = 'Condition'
  AND text_content ILIKE '%Status: active%'
ORDER BY resource_date DESC NULLS LAST
```

Plus a single-row fetch for the resource inspector and a `COUNT(*)` for the health check.

Six access patterns. One of them involves a vector. The other five are `DISTINCT ON`, `ANY`, `ILIKE`, `ORDER BY ... NULLS LAST`, and an aggregate: bread-and-butter SQL against the same rows the embeddings live on.

## What a dedicated store would have cost

With a separate vector database, those five queries need somewhere else to live, which means Postgres stays in the architecture anyway and now there are two systems holding the same 77,466 records.

Every ingestion writes to both. Every schema change touches both. Anything that fails between the two writes leaves them inconsistent, and inconsistency here means a vector search returning ids that the relational side cannot resolve, which surfaces as a citation pointing at nothing.

And the hybrid query would have to be split across the network. Retrieve top-k from the vector store, ship the ids to Postgres, fetch the rows, and do the fusion in Python. My current version is one query. The distributed version has a round trip in the middle of the hot path and moves fusion logic out of the database that has the statistics to optimise it.

There is a subtler cost too. The filter that matters most is `patient_ref`, and it is highly selective. In a dedicated store I would be relying on that store's metadata filtering, which is a feature with real limitations that vary by product. In Postgres it is a `WHERE` clause on an indexed column, and the planner treats it as such.

## One table, six indexes, no synchronisation

```sql
-- db/init.sql
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_embedding ON fhir_chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_resource_type ON fhir_chunks (resource_type);
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_patient_ref ON fhir_chunks (patient_ref);
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_resource_date ON fhir_chunks (resource_date);
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_resource_id ON fhir_chunks (resource_id);
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_text_search ON fhir_chunks USING gin (text_search);
```

That list is the argument in one screenshot. The HNSW index is one of six. The other five carry just as much traffic.

Consistency is free because there is nothing to synchronise. A row has its text, its metadata, its embedding, and its tsvector, and they are updated in one statement:

```sql
-- src/ingestion/ingest.py
ON CONFLICT (resource_id) DO UPDATE SET
    resource_type = EXCLUDED.resource_type,
    patient_ref = EXCLUDED.patient_ref,
    ...
    embedding = EXCLUDED.embedding
```

Re-ingest after a renderer change and the text and the vector move together. There is no window where they disagree.

## The operational argument

The whole system is two containers:

```yaml
# docker-compose.yml
services:
  db:
    image: pgvector/pgvector:pg16
  app:
    build: .
```

`pgvector/pgvector:pg16` is stock Postgres with the extension compiled in. Backups are `pg_dump`. Monitoring is whatever already monitors Postgres. Access control is Postgres roles.

In healthcare that last point is not a footnote. Adding a datastore to a system that will eventually touch patient data means a security review, an access control model, an audit logging story, and a data residency answer, all for the new component. "It is a Postgres extension" is a materially easier conversation than "it is a new database service", and I say that from experience at a clinical research unit rather than from theory.

## What I gave up

Three things, and I want to be specific rather than dismissive.

**Scale.** pgvector on one machine handles my 77,466 chunks without noticing. At tens of millions of vectors, dedicated stores have sharding and distributed search that pgvector does not. If my corpus grew two orders of magnitude I would be re-evaluating.

**Purpose-built filtered search.** Some vector databases have put real engineering into making filtered ANN search work well, which is exactly the problem I ran into. My solution is blunt: for patient-scoped queries I turn the index off entirely.

```python
# src/retrieval/hybrid_search.py
if patient_ref is not None:
    # HNSW selects global nearest neighbors before applying the
    # patient filter, which can incorrectly return no records.
    # Patient-scoped searches are small enough for exact ranking.
    await connection.execute("SET LOCAL enable_indexscan = off")
```

That works because my most common filter is selective enough to make exact ranking fast (5 to 24 ms). It is a design that depends on knowing my data distribution, and it would not survive a filter that selects a million rows.

**Managed operations.** Someone else's problem versus mine.

## Where the threshold is

I would move when the vector workload stops being one query among six. Concretely: if corpus-wide semantic search became the dominant access pattern rather than patient-scoped retrieval, if the corpus reached tens of millions of vectors, or if I needed features pgvector does not have, such as native multi-vector search or learned sparse retrieval.

None of those is close. What is much closer is needing better filtered-ANN behaviour, and the honest answer there is that pgvector is improving fast enough that I expect to get it without moving.

## The general point

"Vector database" names a data structure, not an architecture. The question worth asking is not "which vector store" but "what fraction of my queries are actually vector queries, and what do the rest need?"

If the answer is that similarity search is one operation embedded in a system that also filters, joins, sorts, and aggregates, then the vectors want to be where the rest of the data already is. Adding a specialised store for one of six access patterns buys you a synchronisation problem in exchange for performance on a query that was not your bottleneck.

Start in Postgres. Move when you can point at the specific query that is too slow, and know why.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
