---
title: "The Re-Embed That Computed 77,466 Vectors and Saved None of Them"
published: false
tags: postgres, debugging, docker, dataengineering
series: "Grounded RAG over FHIR"
---

I switched embedding backends from a hash-based placeholder to a real transformer model, re-ran ingestion, and watched it work for ten minutes across sixteen cores. It finished cleanly:

```
Final stats: {'bundles': 78, 'resources': 77466, 'chunks_stored': 77466}
```

Then I asked the system about a patient's allergies. It returned twenty-five `Observation` resources about respiratory rate and head circumference, exactly as badly as before.

Not one of those 77,466 vectors had been written.

## Two silent failures, stacked

The first one is a single clause. My upsert was:

```sql
ON CONFLICT (resource_id) DO NOTHING
```

That was correct when I wrote it. Ingestion was idempotent, re-running it would not duplicate rows, and re-running it was a no-op. All true.

It is exactly wrong for a re-embed. Every `resource_id` already existed, so every row hit the conflict, and every freshly computed transformer vector was discarded on write. The model ran. The vectors were correct. They went into the database and the database said no thank you.

The second failure is why my first fix did not take. I found the `DO NOTHING`, changed it to `DO UPDATE`, and ran `docker compose up -d`. Nothing improved.

`docker compose up -d` reuses the existing image. My `Dockerfile` copies `src/` in at build time, so the container was running the code from before my fix. I had rebuilt the image earlier in the session, *before* writing the fix, which is worse than not rebuilding at all because it left me confident the image was current.

Both failures are silent. Neither produces an error, a warning, or a nonzero exit code.

## Why the success message was a lie

The most uncomfortable part is that the ingestion summary was accurate about the wrong thing:

```python
# src/ingestion/ingest.py
async with pool.acquire() as connection:
    await register_vector(connection)
    await connection.executemany(query, records)
# asyncpg executemany does not return affected-row counts. The upsert is
# idempotent; callers receive the number of attempted stored chunks.
return len(records)
```

`chunks_stored: 77466` is the length of the list I passed in. It is the number of rows *attempted*, and asyncpg's `executemany` does not give me affected-row counts to report instead.

So the pipeline reported the work it set out to do, not the work that landed. Which is a distinction I would have said I understood, right up until I spent ten minutes of CPU proving I did not.

## The fix

```sql
-- src/ingestion/ingest.py
INSERT INTO fhir_chunks (
    resource_id, resource_type, patient_ref, resource_date,
    codes, "references", text_content, embedding
) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)
ON CONFLICT (resource_id) DO UPDATE SET
    resource_type = EXCLUDED.resource_type,
    patient_ref = EXCLUDED.patient_ref,
    resource_date = EXCLUDED.resource_date,
    codes = EXCLUDED.codes,
    "references" = EXCLUDED."references",
    text_content = EXCLUDED.text_content,
    embedding = EXCLUDED.embedding
```

Every derived column refreshes, not just the embedding. Renderer changes need `text_content` to update, and a partial refresh would have produced a fresh vector next to stale text, which is a subtler version of the same bug and considerably harder to notice.

## Idempotent and refreshing are different properties

This is the idea I actually took away.

**Idempotent** means running twice does no additional harm. `DO NOTHING` is idempotent.

**Refreshing** means running twice brings the stored state in line with the current inputs. `DO NOTHING` is not refreshing, and for any pipeline that computes derived values, refreshing is what you want.

The difference is invisible in the pipeline's output and only visible in the data. Both versions accept the same input, run for the same duration, and print the same summary. The distinction lives entirely in a database that you have to go and look at.

## Assert on the stored value

The check that would have caught this in seconds is to read a row back and compare it against a freshly computed value:

```python
stored = [float(x) for x in row["embedding"].to_list()]
fresh = embedder.embed_texts([row["text_content"]])[0]
# cosine must be ~1.0; a hash vector is sparse (~17/384 non-zero)
```

Before the fix: `cos=-0.0206`, `nonzero=17/384`. After: `cos=1.0000`, `nonzero=384/384`.

That is unambiguous. A hash vector is sparse by construction (each token hashes to one of 384 slots, so a four-line chunk touches maybe seventeen), and a transformer vector is dense. Counting zeros distinguishes them instantly, which makes a cheap SQL-only version possible for routine checks:

```sql
-- Confirm stored vectors match the configured embedding backend.
SELECT round(avg(cardinality(array_positions(embedding::real[], 0)))) AS avg_zeros
FROM (SELECT embedding FROM fhir_chunks LIMIT 500) s
```

`0` means dense transformer vectors. A large number means the re-embed did not land. That query is now in my README and in my project notes, because the failure it detects is one I cannot see any other way.

## The Docker half

The second failure deserves its own rule, because it is entirely mechanical and entirely repeatable:

```bash
docker compose build app && docker compose up -d --force-recreate app
```

Build *after* the last edit, always in that order. And when in doubt, verify rather than assume:

```bash
docker exec fhir_rag-app-1 md5sum src/api/routes.py
md5sum src/api/routes.py
```

Two hashes, either equal or not. There is no interpretation required, which is the property I want in a check.

The general trap: any deployment step that reuses a cached artifact will silently run old code if the cache is stale. Docker image layers, Python bytecode, a bundler's build cache, a CDN. The symptom is always "my fix did nothing", and the instinct is always to doubt the fix.

## What this changed about how I work

Three rules came out of one afternoon.

When a pipeline recomputes a derived column, **assert on the stored value, not the exit status**. Read one row back and check it. This is the whole lesson and it applies to embeddings, denormalised aggregates, cached renders, and search indexes.

When a job reports counts, know whether it is reporting attempted or committed work. If it cannot report committed work, say so in the code, and do not treat the number as evidence.

When a fix appears to do nothing, verify that the fix is running before you doubt the fix. That ordering saves a lot of time.

None of these is clever. All three are the kind of thing you adopt after a green build lies to you for ten minutes.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
