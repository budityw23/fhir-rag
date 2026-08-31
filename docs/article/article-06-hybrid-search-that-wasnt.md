---
title: "My Hybrid Search Was Not Hybrid: A Retrieval Arm That Silently Matched Nothing"
published: false
tags: postgres, rag, search, debugging
series: "Grounded RAG over FHIR"
---

I shipped hybrid search. Vector arm, full-text arm, Reciprocal Rank Fusion, the whole standard recipe. Answers improved. I wrote it up as a win and moved on.

Weeks later, a code review prompted me to actually measure each arm separately. The full-text arm had been returning zero rows. Not few rows. Zero, on every realistic question, since the day I wrote it.

The system had been doing pure vector search the entire time and looking like hybrid search from the outside, because the other arm was carrying the result.

## What hybrid search is supposed to fix

Pure vector search fails on a specific and annoying class of question: the ones where the user names the thing they want.

"Is his immunization schedule up to date?" should trivially retrieve the patient's `Immunization` resources. Semantically, the question is about scheduling and age-appropriateness, and the resources are terse records of individual vaccines. The embedding model does not connect them strongly. In my corpus the first `Immunization` resource ranked at position 33, well outside a top-25 cutoff.

A lexical arm should catch exactly that. The word "immunization" is right there in the rendered text. This is what BM25 and `tsvector` are good at, and it is why hybrid retrieval exists.

## The plan, which was fine

Two arms, each over-fetching, fused with **Reciprocal Rank Fusion**: score each document by `1 / (k + rank)` in each ranking and sum. RRF is rank-based rather than score-based, which is why it works across arms whose scores are not comparable, and `k = 60` comes from the original paper.

```python
# src/retrieval/hybrid_search.py
RRF_K = 60
ARM_OVERFETCH = 5
```

Each arm retrieves `top_k * 5` candidates before fusion, so a resource ranked highly by one arm can still surface even when the other arm ignores it entirely.

## The query that matched nothing

The lexical arm used `websearch_to_tsquery`, which is the friendly Postgres entry point that takes user-style input and handles quoting, negation, and escaping for you.

It also joins terms with AND.

That is correct behaviour for web search over documents. It is fatal over short clinical chunks, because it requires every stemmed term in the question to appear in one chunk. Here is what it actually produces:

```
'Is his immunization schedule up to date for a 6-year-old?'
  -> 'immun' & 'schedul' & 'date' & '6' <-> 'year-old'      -> 0 rows

'Which allergies are documented, and what reaction did each cause?'
  -> 'allergi' & 'document' & 'reaction' & 'caus'           -> 0 rows
```

No `Immunization` chunk contains "schedule". No `AllergyIntolerance` chunk contains "documented". These chunks are four lines long. The conjunction can never be satisfied.

So the arm returned nothing, every time, for every question a human would actually ask.

## Why nobody noticed

This is the part I keep thinking about.

The fusion has a `FULL OUTER JOIN` between the arms. When one arm returns zero rows, the join degrades gracefully to the other arm's ranking. No error, no warning, no empty result set at the top level. The system returns 25 well-ranked resources and a good answer.

And retrieval quality genuinely had improved when I added the arm, because I made two changes in the same batch: I added the lexical arm *and* switched from a hash-based embedding backend to a real transformer model. The transformer did all the work. I attributed the gain to the wrong change, and the attribution error hid the broken component behind a real improvement.

A component that fails by contributing nothing is invisible from the outside. Only per-component measurement finds it.

## The fix, in two parts

The first instinct is to swap `websearch_to_tsquery` for `plainto_tsquery` with an OR, or to build the tsquery by hand. Building it by hand means reimplementing tokenisation, stemming, stop words, and escaping, and getting escaping wrong on user input is a security problem.

Better: keep `websearch_to_tsquery` for everything it is good at, then rewrite its operator.

```sql
-- src/retrieval/hybrid_search.py
lexical_query AS (
    -- websearch_to_tsquery joins terms with AND, which requires every
    -- word of a question to appear in one short clinical chunk and so
    -- matched nothing. Reuse its tokenising and escaping, then relax
    -- the conjunction to OR so ts_rank_cd can rank by term overlap.
    SELECT NULLIF(
               replace(websearch_to_tsquery('english', $8)::text, ' & ', ' | '),
               ''
           )::tsquery AS query
),
```

Cast the tsquery to text, replace the AND operators with OR, cast back. The `NULLIF` handles a query that tokenises to nothing (all stop words), so the arm cleanly contributes zero instead of erroring.

Now matching is "shares any term", and `ts_rank_cd` orders by how many terms matched and how densely. That is the right semantics for this data.

## Which immediately caused a second problem

An OR-joined query matches any chunk sharing one common word. "What is the current asthma medication regimen?" now matches every chunk containing "current", which is a lot of them.

With both arms weighted equally, the lexical arm's noisy matches started outvoting genuine semantic similarity, and `MedicationRequest` resources got pushed out of medication questions by whatever happened to share a stopword-adjacent term.

So the fusion is weighted:

```python
# src/retrieval/hybrid_search.py
# Relative weight of the lexical arm in the fusion. The OR-joined query matches
# on any question term, so it ranks chunks that merely share a common word.
# Half weight lets it rescue questions the vector arm misses (a query naming a
# resource type outright) without letting it outvote semantic similarity.
LEXICAL_WEIGHT = 0.5
```

And in the fusion CTE:

```sql
fused AS (
    SELECT COALESCE(v.resource_id, l.resource_id) AS resource_id,
           COALESCE(1.0 / ($9 + v.rank), 0.0)
             + $10 * COALESCE(1.0 / ($9 + l.rank), 0.0) AS score,
           COALESCE(v.similarity, 0.0) AS similarity
    FROM vector_arm v
    FULL OUTER JOIN lexical_arm l ON v.resource_id = l.resource_id
)
```

Half weight is a judgment call, not a tuned value. The reasoning: the lexical arm exists to rescue the specific case where a question names a resource type outright, and in that case it ranks the target first, where even at half weight it contributes enough to pull the resource into the top 25. For everything else it should be a tiebreaker.

## What changed

| | Before | After |
| --- | --- | --- |
| Lexical rows on real questions | 0 | matches |
| 17-question regression set | 4 partially grounded, Q1 wrong | Q1 through Q13 all grounded |

And a question that had been failing for an entirely different reason started working. Asking "what are this patient's active problems?" had been returning only Synthea's repeated administrative `Medication review due` Condition, because near-identical resources cluster in vector space and occupied every Condition slot. With a working lexical arm, the clinical conditions get retrieved on term overlap and the answer is correct.

I had previously written that one up as a chunking and diversity problem. It was, partly. It was also downstream of an arm that did not work.

## The lesson, which generalises

**A component that silently contributes nothing looks exactly like a working one from the outside.** End-to-end metrics cannot distinguish them, because the rest of the system compensates. That is true of a retrieval arm, a cache that never hits, a fallback that never fires, a validation step that passes everything.

The check is embarrassingly cheap once you think to write it. Assert that each arm returns rows:

```sql
SELECT count(*) FROM lexical_arm;   -- should not be 0 for a real question
```

I now treat "did this component do anything?" as a distinct question from "did the system produce a good result?", and I ask the first one explicitly whenever I add a component whose absence is survivable.

There is a second defect in that same query, found in the same review, that turned a 5 ms query into 3.9 seconds by hiding both indexes behind a sequential scan. It is one keyword, and it gets the next article.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag).*
