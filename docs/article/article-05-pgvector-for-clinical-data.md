---
title: "Setting Up pgvector for Clinical Data: Schema, HNSW, and the Filters That Break It"
published: false
tags: postgres, pgvector, rag, database
series: "Grounded RAG over FHIR"
---

The database had 1,725 observations for the patient I was querying. I could count them in psql. A patient-scoped vector search returned an empty list.

Not a bad ranking. Zero rows. And computing cosine distance directly against the same embeddings, with no index involved, returned exactly what I expected.

That is the failure mode that makes approximate vector indexes interesting, and it is the last section of this article. First, the schema.

## One table, four access patterns

Everything lives in one table, because everything the system does is a query against the same rows:

```sql
-- db/init.sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS fhir_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_id TEXT NOT NULL UNIQUE,
    resource_type TEXT NOT NULL,
    patient_ref TEXT NOT NULL,
    resource_date TIMESTAMPTZ,
    codes JSONB DEFAULT '[]',
    "references" TEXT[] DEFAULT '{}',
    text_content TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    text_search TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text_content)) STORED,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

Column by column, each one earns its place.

`resource_id` is the canonical `ResourceType/id` string, and it is `UNIQUE` because that is what makes re-ingestion an upsert rather than a duplicate-fest. It is also the citation target, which means the thing the model cites is the same string that is the natural key. That alignment is not an accident, it is the reason citations can be verified at all.

`patient_ref` is the highest-selectivity filter in the system. `resource_type` and `resource_date` cover the structural part of clinical questions ("which medications", "most recent").

`codes` is JSONB holding every SNOMED, LOINC, and RxNorm coding found in the resource. `"references"` is a `TEXT[]` of outbound FHIR links, which is what makes graph traversal a single indexed lookup later. Note the quoting: `references` is a reserved word in Postgres, so it needs quotes everywhere it appears, including inside every query in the codebase. If I were starting again I would name it `outbound_refs` and save myself the noise.

## Vectors are 384 dimensions on purpose

The embedding column is `vector(384)`, matching `all-MiniLM-L6-v2`. That model is small, runs fine on CPU, and produces vectors a quarter the size of the OpenAI defaults.

The size matters more than it looks. HNSW index build time and memory both scale with dimensionality, and at 77,466 chunks the whole index is small enough that I never think about it. A 1536-dimensional model would have been four times the storage and four times the distance computation for retrieval quality I could not measure a difference in, on text this short.

It also let me keep a dependency-free fallback. The project ships a hash-based embedding backend that produces vectors of the same dimension, so switching backends never requires a schema migration. That backend turned out to be useless for real retrieval, which is a story for another article in this series, but the design property is still right: pick a dimension and make every backend conform to it.

## Generated columns beat write paths

The lexical half of retrieval needs a `tsvector`. There are two ways to get one: compute it during ingestion and write it as a column, or let Postgres derive it.

```sql
text_search TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text_content)) STORED
```

Deriving it means the index can never drift from the text it indexes. There is no code path that updates `text_content` and forgets `text_search`, because there is no code path that writes `text_search` at all. My ingestion INSERT does not mention the column. Re-ingestion refreshes it for free.

The cost is that changing the text search configuration means rebuilding the column. That is a real migration, but it is a rare one, and I will take it over a class of bug where search results silently reflect text from two deploys ago.

## HNSW over IVFFlat

pgvector offers two index types, and the choice comes down to how your data arrives.

```sql
-- db/init.sql
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_embedding ON fhir_chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```

**IVFFlat** partitions vectors into lists and searches the nearest few. It is faster to build and uses less memory, but the list count has to be tuned to your row count, and it wants to be built after the data is loaded because the partitioning is derived from the data distribution. Add a lot of rows later and quality degrades until you rebuild.

**HNSW** builds a navigable graph. It is slower to build and larger in memory, but it is insert-friendly and needs no tuning against row count.

My dataset changes size constantly. I regenerate Synthea cohorts, add a pediatric patient, re-ingest after a renderer fix. A structure that needs retraining after bulk changes would mean either remembering to rebuild or silently degrading. HNSW costs me build time I do not notice and removes an operational failure mode entirely.

`m = 16` and `ef_construction = 64` are the pgvector defaults and I have not had reason to move them.

## The rest of the indexes are boring, and that is the point

```sql
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_resource_type ON fhir_chunks (resource_type);
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_patient_ref ON fhir_chunks (patient_ref);
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_resource_date ON fhir_chunks (resource_date);
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_resource_id ON fhir_chunks (resource_id);
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_text_search ON fhir_chunks USING gin (text_search);
```

Four ordinary B-tree indexes and a GIN index. This is the argument for keeping vectors in Postgres in one screenshot: the "AI" part of the system is one index among six, and the other five are doing just as much work. Patient listing, reference resolution, and suggestion building are all plain relational queries against these rows. In a dedicated vector store, each of those would be a second system and a network hop.

## `init.sql` only runs once, so ship migrations from day one

The Compose file mounts `init.sql` into `/docker-entrypoint-initdb.d/`. That directory runs only when the Postgres data volume is empty. Edit the schema on a running database and nothing happens, silently.

I learned this the way everyone does, by adding the `text_search` column and watching an existing deployment keep failing. Two habits came out of it.

First, `init.sql` is written to be replayable. `CREATE TABLE IF NOT EXISTS` plus a *separate* `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for anything added later:

```sql
-- db/init.sql
-- CREATE TABLE IF NOT EXISTS is a no-op against a database created before
-- text_search existed, and the GIN index below would then fail on a missing
-- column. Adding it separately keeps this file correct for both a fresh volume
-- and an existing fhir_chunks table.
ALTER TABLE fhir_chunks
    ADD COLUMN IF NOT EXISTS text_search TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('english', text_content)) STORED;
```

That subtlety is worth sitting with. Putting the column in the `CREATE TABLE` is not enough, because on an existing database that statement does nothing at all, and then the `CREATE INDEX` below it fails on a column that does not exist. The table definition and the alter have to both be there.

Second, anything that alters an existing table also ships as a numbered file:

```sql
-- db/migrations/001_add_text_search.sql
ALTER TABLE fhir_chunks
    ADD COLUMN IF NOT EXISTS text_search TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('english', text_content)) STORED;

CREATE INDEX IF NOT EXISTS idx_fhir_chunks_text_search
    ON fhir_chunks USING gin (text_search);
```

A deployed database will never re-run `init.sql`. It needs an explicit path forward.

## The empty result from a table full of matches

Back to the opening. Patient-scoped vector search returned nothing, from a patient with 1,725 observations.

The cause is in how approximate indexes and SQL filters compose. HNSW walks its graph to find the nearest neighbours *globally*, returns a candidate set, and only then does the query apply `WHERE patient_ref = $2`. With 78 patients in the corpus and a query about, say, allergies, the global nearest neighbours are overwhelmingly other patients' allergy records. Filter those out and you can be left with nothing.

This is not a bug in pgvector. It is the documented consequence of combining approximate search with a selective filter, and every vector store has some version of it.

There are several fixes. You can raise `hnsw.ef_search` and hope. You can build partial indexes per filter value, which does not scale to 78 patients and would not survive a real corpus. Or you can notice that the filtered subset is small and skip the approximation entirely:

```python
# src/retrieval/hybrid_search.py
async with pool.acquire() as connection:
    async with connection.transaction():
        if patient_ref is not None:
            # HNSW selects global nearest neighbors before applying the
            # patient filter, which can incorrectly return no records.
            # Patient-scoped searches are small enough for exact ranking.
            await connection.execute("SET LOCAL enable_indexscan = off")
```

One patient has a few hundred to a few thousand chunks. An exact scan over that is 5 to 24 ms, which is faster than I need and *correct*, which the index scan was not. `SET LOCAL` scopes the change to the transaction, so unscoped queries still get the index.

Trading an approximate index for exact ranking when the filter is selective enough is not a hack. It is the right shape of decision, and it is one you can only make if you know how selective your filters actually are.

## The takeaway

pgvector gets you a vector index inside a database that already does everything else. The two things that will bite you are both about interaction rather than about vectors: how an approximate index composes with a selective filter, and how your schema file composes with a database that already exists.

The next article in this series is about the query that runs on top of this schema, and specifically about the retrieval arm that returned zero rows for weeks without anybody noticing.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
