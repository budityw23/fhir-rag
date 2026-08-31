---
title: "A CTE Referenced Twice Turned a 5 ms Query Into 3.9 Seconds"
published: false
tags: postgres, performance, sql, pgvector
series: "Grounded RAG over FHIR"
---

I had an HNSW index on the embedding column and a GIN index on the tsvector column. Both were created, both were valid, and `EXPLAIN` showed neither of them being used.

The query was taking 3,871 ms against 77,466 rows. The cause was one keyword I did not know I needed.

## The query shape

Hybrid retrieval over FHIR resources: filter to a patient and a set of resource types, then run a vector arm and a full-text arm over the filtered set, then fuse them.

The obvious way to express that is a CTE for the filter, referenced by both arms:

```sql
-- src/retrieval/hybrid_search.py
WITH filtered AS (
    SELECT resource_id, resource_type, patient_ref, resource_date,
           codes, "references", text_content, embedding, text_search
    FROM fhir_chunks
    WHERE ($2::text IS NULL OR patient_ref = $2::text)
      AND ($3::text[] IS NULL OR resource_type = ANY($3::text[]))
      AND ($4::timestamptz IS NULL OR resource_date >= $4::timestamptz)
      AND ($5::timestamptz IS NULL OR resource_date <= $5::timestamptz)
),
vector_arm AS (
    SELECT resource_id, ROW_NUMBER() OVER (ORDER BY embedding <=> $1) AS rank, ...
    FROM filtered ORDER BY embedding <=> $1 LIMIT $7
),
lexical_arm AS (
    SELECT resource_id, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(text_search, q.query) DESC) AS rank
    FROM filtered, lexical_query q WHERE ... LIMIT $7
),
...
JOIN filtered c ON c.resource_id = f.resource_id
```

`filtered` is referenced three times: once by each arm, once by the final join. That is the readable way to write it, and it is exactly what makes it slow.

## The plan that told the truth

```
CTE filtered -> Seq Scan on fhir_chunks (77,466 rows)
vector arm   -> Sort, external merge Disk: 6480kB
lexical arm  -> CTE Scan, Rows Removed by Filter: 77466
Execution Time: 3871 ms
```

Three things worth reading carefully.

The CTE is a **sequential scan** over the entire table. Not an index scan on `patient_ref`, not anything selective. Every row, every time.

The vector arm is doing an **external merge sort spilling 6.5 MB to disk**. That is what "sort 77,466 vectors by cosine distance" looks like when the HNSW index is not available.

And the lexical arm reads `CTE Scan` with `Rows Removed by Filter: 77466`, which is the GIN index sitting unused while Postgres filters every row by hand.

Both indexes existed. Neither was reachable.

## Why

PostgreSQL **materialises** a CTE that is referenced more than once.

Since version 12, a CTE referenced exactly once is inlined into the containing query, so the planner can push predicates through it and use indexes normally. Referenced two or more times, the default flips: Postgres computes the CTE once into a temporary result and both references read from that result.

The reasoning is sound in general. If a CTE is expensive and referenced several times, computing it once is a win, and it also guarantees stable semantics if the CTE has side effects.

But a materialised result is not a table. It has no indexes. Once `filtered` is materialised, the vector arm cannot use HNSW because HNSW is an index on `fhir_chunks`, not on an ephemeral result set. Same for GIN. Materialisation is an **optimisation fence**, and I had placed one directly between my query and both of my indexes.

## The fix

Two words:

```sql
-- src/retrieval/hybrid_search.py
WITH filtered AS NOT MATERIALIZED (
    SELECT resource_id, resource_type, patient_ref, resource_date,
           codes, "references", text_content, embedding, text_search
    FROM fhir_chunks
    WHERE ($2::text IS NULL OR patient_ref = $2::text)
      ...
),
```

`NOT MATERIALIZED` tells the planner to inline the CTE at each reference regardless of reference count. Predicates flow through, indexes become reachable, and the arms plan as if the filter had been written inline three times.

| | Before | After |
| --- | --- | --- |
| Unscoped query plan | Seq Scan, 3871 ms | HNSW Index Scan, 1099 ms |
| Patient-scoped latency | not measurable separately | 5 to 24 ms |

The unscoped case dropped by a factor of 3.5. The patient-scoped case, which is what the application actually runs, is now fast enough that retrieval is a rounding error next to generation latency.

## When you want the opposite

`MATERIALIZED` is the explicit form of the old default, and it is the right choice when the CTE is genuinely expensive and its result is genuinely reused. An aggregation over a large table, referenced four times downstream, should be computed once.

The heuristic I use now: if the CTE is a **filter**, inline it, because you want the predicates to reach the base table's indexes. If the CTE is a **computation**, materialise it, because you want the work done once.

My `filtered` CTE is a filter. My `lexical_query` CTE, in the same statement, is a computation (it builds one tsquery) and I left it materialised. Both defaults happen to be wrong for their respective cases if you do not think about it, since `lexical_query` is referenced once and gets inlined, which is harmless because it is trivial.

## The habit this changed

I did not find this by profiling. I found it because a review flagged the query and I ran `EXPLAIN (ANALYZE)` to prove the reviewer wrong.

The general failure was assuming that creating an index means using an index. Those are different claims, and only one of them is verified by the `CREATE INDEX` succeeding. Between the two sit CTE materialisation, type mismatches that prevent index use, functions that are not marked immutable, statistics that are stale, and a planner making a cost decision on bad estimates.

So `EXPLAIN (ANALYZE)` is now part of writing the query, not part of investigating it later. For anything with a vector index in it, it is worth being specific about what you are checking for:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT ... ;
-- Look for: "Index Scan using idx_fhir_chunks_embedding"
-- Not for:  "Seq Scan on fhir_chunks"
```

If you are running pgvector behind any kind of filtering, check this today. The CTE pattern is the natural way to express "filter, then search two ways", and it silently disables the index you installed pgvector for.

There is a related trap in the same file, where I deliberately turn the HNSW index *off* for patient-scoped queries because an approximate index and a selective filter can compose into zero results. That one is covered in the pgvector schema article earlier in this series.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
