---
title: "Debugging RAG Systems: 15 Defects and the Measurement That Found Each One"
published: false
tags: rag, debugging, llm, engineering
series: "Grounded RAG over FHIR"
---

Fifteen defects, documented as I found them, in a grounded RAG system over FHIR clinical records. Looking back at the log, almost none of them were where I first looked, and the ones that took longest were the ones that produced no error at all.

Two patterns run through the whole list. Every defect landed in one of three buckets, and telling them apart took one measurement each. And the hardest ones were failures that looked like successes from the outside.

## Three buckets

When an answer is wrong, there are exactly three places the fault can be, and they need completely different investigations.

**The data was never indexed.** The fact is not in the database. No retrieval or prompt change can help.

**The data was never retrieved.** It is in the database, and it did not make the top-k for this question.

**The data was never rendered.** It was retrieved, and the text the model saw did not contain it.

Note that "the model reasoned badly" is not on the list. Across fifteen defects, exactly zero were generation failures. Every single time the answer was wrong, the model had been given input that made the wrong answer correct.

That is the most useful thing I learned, and it is worth stating plainly: **in a grounded RAG system, the model is almost never the problem.**

## Bucket one: never indexed

The clearest case took an afternoon and was entirely self-inflicted. Questions about HbA1c, medications, and complications all returned insufficient data. I assumed retrieval.

One query settled it:

```sql
SELECT resource_type, count(*) FROM fhir_chunks
GROUP BY resource_type ORDER BY count(*) DESC;
```

Zero `Observation`. Zero `Condition`. Zero `MedicationRequest`. I had generated my Synthea corpus with `-m diabetes`, believing it selected a diabetes cohort. It filters *loaded modules*, so it had omitted the modules that generate observations and medications entirely. There were no lab results in the database to retrieve.

Regenerating without `-m` produced 41,837 observations, 2,791 conditions, and 3,416 medication requests.

**The measurement:** count rows by type before anything else. It takes five seconds and it eliminates a whole bucket.

Two more in this bucket had the same shape. Bundles the container could not see, because the host directory was not mounted. And ingestion that consumed CPU for minutes while inserting nothing, because whole-Bundle validation through a FHIR model library was both slow and incompatible with some Synthea fields. Both looked like application bugs. Both were "the data is not there".

## Bucket two: never retrieved

This is the largest bucket and it contains the most interesting failures. The full worked example is the next section, so here is just the measurement.

**Rank the known-correct resource against the query and compare it with `TOP_K`.** Take the resource you know contains the answer, rank the whole patient's chunks against the query embedding, and find its position. If it is outside top-k, the model never saw it, and every minute spent on the prompt is wasted.

**That single measurement separates a retrieval bug from a reasoning bug**, and it is the one I reach for first now.

Three defects live here. A hash-based embedding backend that matched tokens literally, so "allergies" shared no signal with "AllergyIntolerance". An HNSW index returning zero rows for a valid patient filter, because approximate search picks global neighbours before the filter applies. And near-identical Synthea conditions clustering tightly enough to occupy every Condition slot in a top-25 retrieval.

## Bucket three: never rendered

The subtlest bucket, and the one with a distinctive signature.

An answer that names the right entities and then cannot describe them has not failed at retrieval or reasoning. It failed at ingestion, and the evidence is sitting in one column.

**The measurement:** read the stored text for the resource in question.

```sql
SELECT text_content FROM fhir_chunks WHERE resource_id = 'AllergyIntolerance/...';
```

That string is exactly what the model received. If the fact is not in it, nothing downstream can produce it.

The signature is worth memorising. **Correct entities with missing attributes points at the renderer.** Wrong entities points at retrieval. I now check the rendered text before touching either.

A second one in this bucket was mechanical: `_first_coding` assumed a path ended at a single CodeableConcept, but `Encounter.type` is an array of them, so every encounter in the database rendered as `Encounter: unspecified.`

## One session, start to finish

The buckets are easier to trust with a full example. Here is the longest single
debugging session in the project, in the order the measurements actually
happened.

**The symptom.** A pediatric Synthea patient returned "insufficient data" for
three questions whose answers were plainly in the record:

```
"Which allergies are documented, and what reaction did each cause?"
"What was his BMI percentile at the most recent well-child visit?"
"Is his immunization schedule up to date for a 6-year-old?"
```

**Measurement one: is the data indexed?** Always first, because it is five
seconds and eliminates a whole bucket.

```sql
SELECT resource_type, count(*) FROM fhir_chunks
WHERE patient_ref = 'Patient/064e883f-d41c-5fa5-b6f6-664fdbfb9ca8'
GROUP BY resource_type;
```

Seven `AllergyIntolerance`, 33 `Immunization`, 226 `Observation`. The data is
there. Bucket one eliminated, and I have not touched the model or the prompt.

**Measurement two: is the data retrieved?** Rank the known-correct resource
against the query embedding and compare with `TOP_K`:

| Question | Best matching resource ranked |
| --- | --- |
| allergies | `AllergyIntolerance` #34 |
| immunization schedule | `Immunization` #33 |
| BMI percentile | not in top 10 |

With `TOP_K=10`, none of them was ever in the context window. That single table
is the whole diagnosis: the model was answering honestly about a context that
did not contain the answer. A larger model would have produced the same refusal
at higher cost.

Worth noting what I also measured here: the top-10 similarity scores sat between
0.12 and 0.24. In a 384-dimensional cosine space that is noise. The ranking was
not merely wrong, it was arbitrary, which pointed straight at the embedding
rather than at the query.

**The cause.** `EMBEDDING_BACKEND=hash`, a signed hashing trick over unigrams
and bigrams. It matches tokens literally, so "allergies" shares no signal with
"AllergyIntolerance". A second, independent cause surfaced in the same
investigation: `hybrid_search` was not hybrid. It was a single vector `ORDER BY`
with no lexical arm, so a query naming a resource type outright still could not
retrieve it.

**The fix, in increasing cost.** `TOP_K` from 10 to 25. A real lexical arm with
a generated `tsvector` column and RRF fusion. `EMBEDDING_BACKEND=transformer`.
And `store_chunks` from `ON CONFLICT DO NOTHING` to `DO UPDATE`, which was
necessary for any of the rest to reach the database.

**Verification.** Not "the answers look better". A direct comparison of stored
vectors against freshly computed ones:

```python
stored = [float(x) for x in row["embedding"].to_list()]
fresh = embedder.embed_texts([row["text_content"]])[0]
# cos=1.0000, nonzero=384/384
```

**And then it was still wrong.** The allergy question now retrieved all seven
resources and cited all seven, and still said it could not determine the
reactions. Same symptom string, completely different cause, and this is the part
that makes the three-bucket model worth having: I had fixed a bucket-two defect
and immediately hit a bucket-three one behind it.

**Measurement three: what did the model actually see?**

```sql
SELECT text_content FROM fhir_chunks WHERE resource_id = 'AllergyIntolerance/...';
```

```
AllergyIntolerance: Mold (organism) (SNOMED: 84489001).
Status: active.
```

Two lines. `render_allergy_intolerance` emitted code, status, and patient, and
never looked at `reaction`, `criticality`, or `category`. The fact had never been
written into the chunk.

Four measurements, three of them one-liners, and each one eliminated a category
rather than testing a hypothesis. That is the property worth copying: a good
debugging measurement halves the search space regardless of its outcome.

## Failures that look like successes

Four of the fifteen produced no error at all, and they are worth taking one at a
time because they have nothing technically in common. What they share is a
shape.

**A retrieval arm that matched nothing.** My lexical arm used
`websearch_to_tsquery`, which joins terms with AND, requiring every stemmed word
of a question to appear in one four-line clinical chunk:

```
'Which allergies are documented, and what reaction did each cause?'
  -> 'allergi' & 'document' & 'reaction' & 'caus'   -> 0 rows
```

Zero rows on every realistic question, for weeks. The fused result still looked
healthy because the vector arm carried it, and I had attributed the quality
improvement to the wrong change in a batch of two.

**A job reporting attempted work.** Ingestion printed `chunks_stored: 77466`
after a ten-minute re-embed in which nothing was written, because the upsert was
`ON CONFLICT DO NOTHING` against rows that all already existed. The count was
the length of the input list, which the code even says:

```python
# src/ingestion/ingest.py
# asyncpg executemany does not return affected-row counts. The upsert is
# idempotent; callers receive the number of attempted stored chunks.
return len(records)
```

**An HTTP 200 that was not a complete answer.** Gemini charges internal
reasoning against `maxOutputTokens`. At a 2048 cap it spent 1,742 tokens
thinking and 302 answering, and the truncation landed inside a citation marker,
so the grounding checker reported it as ungrounded. The evidence was in the
response body all along:

```json
{"finishReason": "MAX_TOKENS", "thoughtsTokenCount": 1742, "candidatesTokenCount": 302}
```

**Indexes that existed and were never used.** A CTE referenced three times gets
materialised by PostgreSQL, which fenced off both the HNSW and GIN indexes and
turned a 5 ms query into 3,871 ms. `CREATE INDEX` had succeeded, so I believed
the index was in use.

The common shape: **the system's own report of its health was not evidence of
its health.** A green exit code, an HTTP 200, a row count, a successful index
creation. Each is a claim about a process completing, not about a state being
reached, and the gap between those two is where these defects live.

The defence generalises past RAG. Any component whose absence is survivable can
fail silently, because the rest of the system compensates and the end-to-end
result still looks fine. A cache that never hits. A fallback that never fires. A
validation step that passes everything. For each one, "did this component do
anything?" is a different question from "did the system produce a good result?",
and only the first one catches it.

## Verify the fix is running before doubting the fix

One habit that is not a measurement, and that cost me an hour on its own.

My `Dockerfile` copies `src/` in at build time, and `docker compose up -d`
reuses an existing image rather than rebuilding. So after finding the
`ON CONFLICT DO NOTHING` bug and fixing it, I restarted the stack, re-ran
ingestion, and watched nothing change. The fix was correct. The container was
running the code from before it.

Worse, I had rebuilt the image earlier in the same session, which left me
confident it was current. A stale rebuild is more misleading than no rebuild.

```bash
docker exec fhir_rag-app-1 md5sum src/api/routes.py; md5sum src/api/routes.py
```

Two hashes, equal or not, no interpretation required. That is the property I
want in a check, and it now runs before I conclude anything about a fix that
appears to have done nothing.

The general trap is any deployment step that reuses a cached artifact: Docker
layers, Python bytecode, a bundler cache, a CDN. The symptom is always "my fix
did nothing", and the instinct is always to doubt the fix rather than the
delivery. Build after the last edit, never before, and verify rather than
assume.

## Triage, in the order that costs least

Ordering matters as much as the measurements themselves. Each of these
eliminates a bucket, and they are listed cheapest first, so a session should
run top to bottom rather than jumping to the most interesting hypothesis.

| Question | Measurement | If it fails |
| --- | --- | --- |
| Is the data indexed? | `count(*) GROUP BY resource_type` | Fix ingestion. Nothing else can help. |
| Was it retrieved? | Rank the known-correct resource, compare with `TOP_K` | Fix retrieval. The prompt is irrelevant. |
| Did the model see it? | `SELECT text_content WHERE resource_id = ...` | Fix the renderer. |
| Did each component contribute? | Row count per retrieval arm | A silent component is carrying nothing. |
| Was the response complete? | `finishReason`, output token count | Truncation, not a quality problem. |
| Was the index used? | `EXPLAIN (ANALYZE)` | A plan problem, not a hardware one. |

Only after all six do I consider that the model reasoned badly, and in fifteen
defects I have never got that far.

The symptom-to-bucket mapping is worth internalising separately, because it
short-circuits the ordering when the symptom is distinctive:

**"Insufficient data" on a question you know the record answers** is almost
always bucket one or two. Check indexing, then retrieval ranking.

**Correct entities with missing attributes** is bucket three, essentially every
time. The renderer dropped a field.

**An answer that under-reports on an aggregation** ("one active problem" when
there are four) is a retrieval diversity problem. Look at the histogram of the
retrieved set, both by resource type and by content within the dominant type.

**An answer that stops mid-sentence** is not a model quality problem. Read the
finish reason.

## The anatomy of a log entry

The single highest-leverage habit was writing each defect down with its
evidence, not just its fix. Every entry in `docs/notes/fhir-rag-debugging.md`
has the same five parts, and the shape is what makes them useful later:

**Symptom**, as observed, in the words I would have used at the time. This is
what makes the file searchable when a similar symptom reappears.

**Cause**, with the evidence that established it. Not "the CTE was materialised"
but the `EXPLAIN` output showing `Seq Scan` and `Rows Removed by Filter: 77466`.

**Fix**, as the actual diff or the actual line.

**Verification**, which is a different thing from the fix. For the re-embed bug
this is `cos=-0.0206, nonzero=17/384` before and `cos=1.0000, nonzero=384/384`
after. A fix without a verification is a hypothesis.

**Lesson**, stated generally enough to apply to the next thing.

Ten minutes per entry. What it buys is compounding: when the near-duplicate
conditions defect turned out to be partly caused by the broken lexical arm, I
could see the connection because both write-ups had their measurements attached.
The `-m diabetes` mistake is in there so nobody regenerating the corpus repeats
it. And section 11's lesson (assert on stored values, not exit status) is why I
caught a later bug in seconds rather than hours.

Two entries also record that my *first* explanation was wrong. Section 13
originally blamed answer length for the truncation, and it was actually thinking
tokens consuming the output budget. I left the correction visible rather than
rewriting history, because the misdiagnosis is the interesting part: it was
plausible enough that I stopped investigating, which is the actual failure mode
worth remembering.

## What the log does not contain

Worth being explicit about the shape of the sample, because fifteen defects from
one project is not a survey.

There are no generation failures in the list, and I do not think that
generalises as strongly as it reads. My prompt is short, single-turn, and heavily
constrained, over a context block of at most a few dozen short resources. That is
close to the easiest possible task for a modern model. A system doing multi-turn
reasoning, tool use, or synthesis across hundreds of documents would find real
generation defects, and my "the model is almost never the problem" would be
overconfident there.

There are also no concurrency defects, no defects that only appear under load,
and no defects caused by real data messiness, because the corpus is synthetic
and the system runs for one user at a time. Synthea gives me no duplicate
patients, no conflicting records from two source systems, and no free-text notes
with the answer buried in them. A pipeline validated only against generated data
has not met the hardest part of the problem.

What the sample does cover well is the pipeline seam: the places where one stage
hands work to the next and the handoff loses something. Eleven of the fifteen
are seam defects. Parsing to storage, storage to retrieval, retrieval to
rendering, rendering to prompt, provider to response. That is where I would look
first in an unfamiliar RAG system, and it is the part I would expect to transfer.

## The checklist

If you are building a RAG system over structured data, the compressed version.

Assume the model is not the problem, and prove it before spending time there.
Three cheap measurements (row counts, retrieval rank, stored text) eliminate
three whole buckets, and they run in under a minute combined.

Measure each component's contribution independently, because end-to-end quality
hides component failure. A retrieval arm that returns nothing looks identical to
a working one from the outside.

Assert on state, never on exit status. A job's report of what it attempted is not
evidence of what it committed, and an HTTP 200 is not evidence of a complete
answer.

And write down what you find, with the evidence attached, because the next defect
is usually adjacent to the last one and the reasoning is what compounds.

---

*I work on clinical data systems at a research unit, mostly FHIR R4, HL7 v2, and HAPI FHIR. This series documents an open-source grounded RAG system over FHIR records: [github.com/budityw23/fhir-rag](https://github.com/budityw23/fhir-rag). The full defect log, with evidence, is in `docs/notes/fhir-rag-debugging.md`.*
