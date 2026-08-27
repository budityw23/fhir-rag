# FHIR RAG Debugging Notes

This note records the issues encountered while running the FHIR RAG UI with
Synthea data, the evidence used to identify each cause, and the resulting fix.

## 1. Alpine Could Not Find `submitQuestion`

**Symptom**

The browser console reported `submitQuestion is not defined` when pressing
Enter in the clinical-question text area.

**Cause**

Alpine evaluated `x-data` before the script that defines the component
function was loaded.

**Fix**

Load `app.js` before `alpine.min.js` in `src/frontend/index.html`. Alpine can
then resolve `submitQuestion()` while it initializes the page.

**Lesson**

For Alpine components defined in ordinary script files, script order is part
of the component contract. Verify this first when an `x-data` method is
reported as undefined.

## 2. Synthea JAR Was Not Found

**Symptom**

`java -jar synthea.jar ...` failed with `Unable to access jarfile synthea.jar`.

**Cause**

The downloaded artifact was named `synthea-with-dependencies.jar`, not
`synthea.jar`, or the command was run from a different directory.

**Fix**

Run the command from the directory containing the JAR and use its actual
filename:

```bash
java -jar synthea-with-dependencies.jar -p 70 --exporter.fhir.export=true
```

**Lesson**

Treat the JAR name and working directory as explicit setup inputs. A README
should not assume a renamed download.

## 3. Docker Could Not See Generated Bundles

**Symptom**

The ingestion command in the `app` container reported:

```text
No FHIR bundles found in data/synthea
```

**Cause**

The host `data/synthea` directory was not mounted into the application
container.

**Fix**

Add a read-only Compose volume mount:

```yaml
volumes:
  - ./data/synthea:/app/data/synthea:ro
```

**Lesson**

Always verify both sides of a data path: `find data/synthea` on the host and
inside the container. A successful host-side generation does not imply the
container can read it.

## 4. Synthea Module Filtering Removed Clinical Data

**Symptom**

The UI could select patients, but questions about HbA1c, diabetes medications,
and complications produced insufficient or ungrounded answers. The indexed
resources were mostly `Patient`, `Encounter`, `DiagnosticReport`, and
`Immunization`; there were no `Observation`, `Condition`, or
`MedicationRequest` records.

**Cause**

The commands used `-m diabetes` and `-m type1_diabetes`. In Synthea, `-m`
filters loaded modules. It is not a patient-cohort selector, so it omitted
the broader resource-generation modules required by this application.

**Fix**

Generate normal FHIR data without `-m`, then copy the FHIR bundles into
`data/synthea` and re-ingest them:

```bash
java -jar synthea-with-dependencies.jar -p 70 --exporter.fhir.export=true
cp output/fhir/*.json data/synthea/
docker compose exec app python -m src.ingestion.ingest --data-dir data/synthea/
```

The restricted dataset is retained in `data/synthea.module-filtered-backup`.

**Verification**

The regenerated index contained 41,837 `Observation`, 2,791 `Condition`, and
3,416 `MedicationRequest` chunks.

**Lesson**

Before tuning an LLM, inspect the source data and indexed resource-type counts.
No model can answer an HbA1c question when the index contains no observations.

## 5. Synthea `urn:uuid` References Did Not Match Patient IDs

**Symptom**

Resources referenced patients as `urn:uuid:...`, while the database stored
canonical IDs such as `Patient/<id>`. Patient-scoped retrieval could therefore
miss relevant records.

**Cause**

FHIR Bundle `fullUrl` values use UUID URNs, but resource IDs use the canonical
`ResourceType/id` form. The parser stored the former without resolving it.

**Fix**

`src/ingestion/fhir_parser.py` builds a Bundle-local `fullUrl` map and
normalizes references during parsing.

**Lesson**

FHIR references are not always canonical IDs. Preserve `entry.fullUrl` while
parsing Bundles and normalize references before using them as database keys.

## 6. FHIR Model Validation Stalled Ingestion

**Symptom**

Ingestion of 80 normal Synthea bundles consumed CPU for minutes and inserted
no chunks. Logs repeatedly reported Bundle validation failures.

**Cause**

Whole-Bundle validation by `fhir.resources` was both expensive for large
Synthea Bundles and incompatible with some emitted fields. The application
only needs JSON fields from supported resource types during ingestion.

**Fix**

Parse raw JSON entries directly, validate the basic Bundle shape (`entry` is a
list), and filter supported resource types. This also preserves raw `fullUrl`
values needed for reference normalization.

**Lesson**

Use strict model validation at API boundaries that require it. For bulk
ingestion, prefer tolerant parsing plus explicit checks when the upstream
format is valid but version-variable.

## 7. pgvector Could Not Encode Python Embeddings

**Symptom**

Queries failed with an error similar to:

```text
invalid input for query argument $1: [0.0, ...] (expected str, got list)
```

**Cause**

`asyncpg` did not know how to encode a Python list as PostgreSQL's `vector`
type.

**Fix**

Register pgvector codecs for every pooled connection with
`pgvector.asyncpg.register_vector` via the pool `init` callback.

**Lesson**

Database type codecs must be installed per connection, not merely once when
the process starts.

## 8. HNSW Returned No Results for a Valid Patient Filter

**Symptom**

The database contained 1,725 observations for a selected patient, but a
patient-scoped vector query returned an empty list. A direct cosine-distance
calculation against the same embeddings worked.

**Cause**

The HNSW index finds approximate nearest neighbors globally before SQL filters
are applied. Its candidates did not include a row for the selected patient,
so filtering removed every candidate.

**Fix**

`src/retrieval/hybrid_search.py` disables index scans inside the transaction
for patient-scoped searches, forcing exact ranking for that small subset.

**Lesson**

Approximate vector indexes and selective relational filters need deliberate
query design. For correctness-critical, narrow filters, exact ranking is often
the better tradeoff.

## 9. Lightweight Embeddings Did Not Recognize `HbA1c`

**Symptom**

After retrieval was fixed, a query containing `HbA1c` ranked unrelated
observations above records labeled `Hemoglobin A1c`.

**Cause**

The default lightweight hash embedding matches tokens literally. `hba1c` and
`hemoglobin a1c` are different tokens.

**Fix**

`Embedder.embed_query` expands common clinical abbreviations before embedding:

```text
HbA1c -> hemoglobin a1c
```

This changes query processing only, so no re-ingestion is required.

**Verification**

Patient-scoped retrieval for `What is the latest HbA1c?` returned two LOINC
`4548-4` Hemoglobin A1c observations.

**Lesson**

Use small, explicit query expansions for high-value clinical abbreviations
before adding a larger embedding runtime. Move to a semantic embedding model
when the vocabulary is too broad to maintain with targeted expansions.

## 10. Hash Embeddings Made Non-Diabetes Questions Unanswerable

**Symptom**

A pediatric Synthea patient (Neal874 Upton904, born 2020-03-29) returned
`Insufficient data in the available FHIR resources` for questions whose
answers were plainly indexed:

- "Which allergies are documented, and what reaction did each cause?"
- "What was his BMI percentile at the most recent well-child visit?"
- "Is his immunization schedule up to date for a 6-year-old?"

The database held 7 `AllergyIntolerance`, 33 `Immunization`, and 226
`Observation` chunks for this patient.

**Cause**

The answer was never retrieved, so the model was answering honestly about an
empty context. Ranking the patient's chunks against each query showed the
correct resource far below the `TOP_K=10` cutoff:

| Question | Best matching resource ranked |
| --- | --- |
| allergies | `AllergyIntolerance` #34 |
| immunization schedule | `Immunization` #33 |
| BMI percentile | not in top 10 |

Top-10 similarity scores sat between 0.12 and 0.24, which is noise for a
384-dimensional cosine space. The default `EMBEDDING_BACKEND=hash` is a signed
hashing trick over unigrams and bigrams: it matches tokens literally and has no
semantic generalization, so "allergies" shares no signal with
`AllergyIntolerance`. This is the limit anticipated by the lesson in section 9.

A second, independent cause: `hybrid_search` was not hybrid. It was a single
vector `ORDER BY` with no lexical arm, so a query naming a resource type
outright still could not retrieve it.

**Fix**

Four changes, in increasing cost:

1. `TOP_K` raised from 10 to 25 (`src/config.py`, `.env.example`,
   `docker-compose.yml`).
2. A real lexical arm. `fhir_chunks` gained a generated `text_search TSVECTOR`
   column with a GIN index, and `hybrid_search` now runs a vector arm and a
   `websearch_to_tsquery` arm, each over-fetching `TOP_K * 5` candidates, then
   fuses them with Reciprocal Rank Fusion (`k = 60`). With no `query_text` it
   degrades to pure vector search.
3. `EMBEDDING_BACKEND=transformer` (`all-MiniLM-L6-v2`, 384-dim, so the
   pgvector column is unchanged). The `Dockerfile` installs the `semantic`
   extra from the PyTorch CPU wheel index and bakes the model weights into the
   image; `lifespan` pre-warms the encoder so the first query does not absorb
   the ~11s lazy load.
4. `store_chunks` changed from `ON CONFLICT DO NOTHING` to `DO UPDATE`.

**Verification**

`cosine(stored_vector, freshly_encoded_text)` is `1.0000` with 384/384
non-zero components on sampled rows. The allergy question now returns all 7
`AllergyIntolerance` resources with 7 citations and `grounded` confidence,
and "What is the latest HbA1c?" still correctly returns insufficient data for
this patient, who has no glucose results.

**Lesson**

When a grounded RAG system says "insufficient data", check retrieval before
blaming the model. The generator was behaving correctly the whole time — a
larger model would have produced the same refusal at higher cost. Rank the
known-correct resource against the query and compare it to `TOP_K`; that one
measurement separates a retrieval bug from a reasoning bug.

## 11. A Re-Embed That Silently Discarded Every Vector

**Symptom**

After switching to `EMBEDDING_BACKEND=transformer` and re-running ingestion to
completion (`chunks_stored: 77466`, ~10 minutes of CPU), retrieval quality did
not change. A query for allergies returned 25 `Observation` rows about
respiratory rate and head circumference.

**Cause**

Two independent failures compounded:

1. `store_chunks` still used `ON CONFLICT (resource_id) DO NOTHING`. Every
   `resource_id` already existed, so all 77,466 freshly computed transformer
   vectors were computed and then dropped on write.
2. The image had been rebuilt *before* that `ingest.py` fix was written, and
   `docker compose up -d` reuses an existing image rather than rebuilding. The
   container was running the old code.

Both are silent. Ingestion reported success because `store_chunks` returns the
number of *attempted* rows, not the number actually written.

**Fix**

`ON CONFLICT ... DO UPDATE SET` refreshing `embedding`, `text_content`, and
the metadata columns, and a rebuild ordered after every source edit.

**Verification**

Compare a stored vector against a freshly encoded one instead of trusting the
ingestion summary:

```python
stored = [float(x) for x in row["embedding"].to_list()]
fresh = embedder.embed_texts([row["text_content"]])[0]
# cosine must be ~1.0; a hash vector is sparse (~17/384 non-zero)
```

Before the fix this printed `cos=-0.0206`, `nonzero=17/384`. After, `cos=1.0000`,
`nonzero=384/384`.

**Lesson**

An idempotent upsert and a *refreshing* upsert are different things, and the
difference is invisible until you diff the data. Whenever a pipeline
recomputes a derived column, assert on the stored value, not on the job's exit
status. Rebuild the image after the last source edit, not before it.

## 12. Renderers Dropped Reactions and Encounter Types

**Symptom**

With retrieval fixed, the allergy question listed all 7 allergens but appended
"Insufficient data ... to determine the specific reactions". The BMI question
failed with "All Encounters are listed as `unspecified`".

**Cause**

Data loss at ingestion, not retrieval. `render_allergy_intolerance` emitted
only code, status, and patient — never `reaction`, `criticality`, or
`category`. Separately, `_first_coding` walked a path expecting a single
`CodeableConcept`, but `Encounter.type` is an *array* of them, so the
`isinstance(value, dict)` check failed and every Encounter rendered as
`Encounter: unspecified.`

The model cannot cite what was never written into `text_content`.

**Fix**

`_first_coding` now unwraps a list before looking for `coding`.
`render_allergy_intolerance` renders category, criticality, each reaction's
manifestations with severity, and the recorded date.

**Verification**

```text
AllergyIntolerance: Mold (organism) (SNOMED: 84489001).
Status: active.
Category: environment.
Criticality: low.
Reactions: Cutaneous hypersensitivity (disorder) (SNOMED: 21626009) (mild); ...
```

Encounters now render `Encounter: Well child visit (procedure) (SNOMED: 410620009).`

**Lesson**

When an answer is partially right — correct entities, missing attributes —
suspect the renderer before the retriever or the model. Read the stored
`text_content` for the resource in question; it is the exact string the model
saw. FHIR mixes singular and array-valued `CodeableConcept` fields, so path
helpers must handle both.

## 13. Gemini Thinking Tokens Consumed the Entire Output Budget

**Symptom**

Answers stopped mid-word, sometimes after only 182 characters, and were then
reported as `ungrounded` with zero citations because the cut landed inside a
`[ResourceType/id]` marker. An earlier version of this note blamed the length
of the enumeration; that explanation was wrong.

**Cause**

`gemini-2.5-flash` is a thinking model, and internal reasoning tokens count
against `maxOutputTokens`. At the previous cap of 2048 the model spent almost
the entire budget thinking:

```json
{"finishReason": "MAX_TOKENS",
 "thoughtsTokenCount": 1742,
 "candidatesTokenCount": 302}
```

85% of the budget produced no visible text. The request succeeded, so nothing
in the pipeline reported a problem.

**Fix**

`src/generation/llm_client.py` now sends a shared generation config on both
Google paths with `maxOutputTokens: 4096` and
`thinkingConfig: {thinkingBudget: 512}`, and logs a warning whenever
`finishReason == "MAX_TOKENS"`.

**Verification**

Same prompt, three configurations:

| Config | finishReason | thinking | output | chars |
| --- | --- | --- | --- | --- |
| 2048, unbounded thinking | MAX_TOKENS | 1964 | 80 | 382 |
| 2048, thinkingBudget 0 | STOP | 0 | 1675 | 6824 |
| 4096, thinkingBudget 512 | STOP | 448 | 2122 | 8436 |

Across a 17-question regression set, truncations went from several to zero.
The bounded budget also uses *fewer* thinking tokens than the broken default.

**Lesson**

For thinking models, `maxOutputTokens` is a budget shared with reasoning, not a
limit on the answer. Always bound `thinkingBudget` explicitly for extraction
tasks, and treat `finishReason` as a value to check rather than ignore — an
HTTP 200 is not evidence of a complete answer.

## 14. Near-Duplicate Chunks Crowded Out the Real Diagnoses

**Symptom**

"What are Neal's active problems, and when was each diagnosed?" answered
"Neal has one active problem: Medication review due", omitting his three
active clinical conditions (atopic dermatitis, perennial allergic rhinitis,
childhood asthma).

**Cause**

Retrieval, not generation. Of 25 retrieved chunks, 12 were `Condition` and all
12 were near-identical `Medication review due (situation)` rows — Synthea emits
one per visit. Near-duplicate text embeds to nearly the same vector, so these
rows occupy a dense cluster that wins every top-k slot for a generic
"problems" query. The model described exactly what it was given.

**Workaround**

Naming the conditions in the question retrieves them correctly, because
retrieval is driven by the query text:

```text
"What chronic conditions does he have - asthma, eczema, allergic rhinitis -
 and when was each diagnosed?"   -> grounded, 3 citations, all correct
```

Asking the model to *exclude* the duplicates does not work. Exclusion happens
during generation, after retrieval has already discarded the answer.

**Resolved by section 15.** Once the lexical arm actually matched, the clinical
conditions were retrieved and this question answers correctly. Diversity-aware
retrieval (MMR, or collapsing by `(resource_type, code)`) is still the more
robust fix and remains unimplemented.

**Lesson**

Top-k similarity assumes candidates are informative *and* distinct. Synthetic
records violate that badly with repeated administrative entries. When an
aggregation question under-reports, inspect the resource-type histogram of the
retrieved set before touching the prompt.

## 15. The Lexical Arm Matched Nothing, and the CTE Blocked Every Index

**Symptom**

Found by CodeRabbit review of PR #1, then confirmed with `EXPLAIN (ANALYZE)`.
A patient-unscoped hybrid query took **3871 ms**, and the lexical arm returned
zero rows for every realistic question.

**Cause**

Two defects in the same query.

`websearch_to_tsquery` joins terms with AND. A question has to have *all* of
its stemmed terms present in one short clinical chunk for the arm to match,
which never happens:

```text
'Is his immunization schedule up to date for a 6-year-old?'
  -> 'immun' & 'schedul' & 'date' & '6' <-> 'year-old'   -> 0 rows
'Which allergies are documented, and what reaction did each cause?'
  -> 'allergi' & 'document' & 'reaction' & 'caus'        -> 0 rows
```

So "hybrid" search was pure vector search. The retrieval gains in section 10
came entirely from the transformer embeddings; the lexical arm contributed
nothing.

Separately, the `filtered` CTE is referenced three times, and PostgreSQL
materialises a CTE referenced more than once. The arms then scanned a
materialised result, so neither the HNSW nor the GIN index could be used:

```text
CTE filtered -> Seq Scan on fhir_chunks (77,466 rows)
vector arm   -> Sort, external merge Disk: 6480kB
lexical arm  -> CTE Scan, Rows Removed by Filter: 77466
Execution Time: 3871 ms
```

**Fix**

Declare the CTE `AS NOT MATERIALIZED`, and relax the conjunction to OR by
reusing `websearch_to_tsquery` for tokenising and escaping and rewriting its
operator:

```sql
NULLIF(replace(websearch_to_tsquery('english', $8)::text, ' & ', ' | '), '')::tsquery
```

An OR-joined query matches any chunk sharing a single common word, so an
equally weighted arm then outvoted semantic similarity and pushed
`MedicationRequest` rows out of asthma-medication questions. The fusion is now
weighted, `LEXICAL_WEIGHT = 0.5`.

**Verification**

| | Before | After |
| --- | --- | --- |
| Unscoped query plan | Seq Scan, 3871 ms | HNSW Index Scan, 1099 ms |
| Patient-scoped latency | — | 5-24 ms |
| Lexical rows on real questions | 0 | matches |
| 17-question set | 4 partially grounded, Q1 wrong | Q1-Q13 all grounded |

This also fixed section 14: with a working lexical arm, "What are Neal's active
problems?" now returns the clinical conditions rather than only the repeated
administrative entry.

**Lesson**

A retrieval arm that silently matches nothing looks exactly like a working one
from the outside — end-to-end answers still improved, because the other arm
carried it. Assert that each arm returns rows, not just that the fused result
looks better. And check the query plan before assuming an index is used: a CTE
referenced more than once is an optimisation fence by default.

## 16. The Patient Picker Was Unordered and Unreadable

**Symptom**

The patient dropdown listed 78 records in no useful order, and each option read
`Kimberly627 Hahn503 — Patient/07e85900-...`. Finding a known patient meant
scanning the whole list, and the digits made the names hard to read at a glance.

**Cause**

Two separate things, neither of them a retrieval defect:

- `/api/patients` returned rows in the order the query produced them. The
  `ORDER BY patient_ref` in that query is not a display order — it is required
  by `SELECT DISTINCT ON (patient_ref)`, so it sorts by opaque UUID.
- Synthea suffixes every name part with digits (`Bob965 Demarcus108
  Hammes673`) to keep synthetic identities distinct. The renderer stored that
  string verbatim and `_patient_summary` parsed it back out unchanged.

The display name is parsed out of `text_content` in `_patient_summary`, not
selected as a column, so the sort could not move into SQL without also changing
what the query selects.

**Fix**

Both in `src/api/routes.py`, display-side only:

- `_strip_synthea_digits` removes digits that follow a letter
  (`(?<=[^\W\d_])\d+\b`). The lookbehind is what keeps a purely numeric token
  intact, and it leaves the `patient_ref` fallback alone when no name parses.
- `list_patients` sorts the built summaries by `name.casefold()` before
  returning them.

Nothing upstream changes: `patient_ref` is still the filter key for
`/api/query`, and the stored `text_content` keeps the original Synthea names,
so citations and retrieval are untouched.

**Verification**

```bash
curl -s localhost:8000/api/patients | \
  python3 -c "import sys,json;[print(p['name']) for p in json.load(sys.stdin)[:6]]"
# Albert Sean Nienow
# Alejandrina Susanne Cormier
# Alysa Rath
# ...
```

**Lesson**

An `ORDER BY` that exists to satisfy `DISTINCT ON` is a correctness constraint,
not a presentation choice — reading it as the display order is how a list ends
up sorted by UUID. And when the displayed value is derived in Python rather
than selected as a column, the sort belongs where the value is built.

**Environment note**

`docker compose build` failed here with:

```text
error getting credentials - err: fork/exec /usr/bin/docker-credential-desktop.exe: exec format error
```

This is the WSL Docker Desktop credential helper, not a project problem. Build
against a throwaway config that declares no helper:

```bash
mkdir -p /tmp/dockercfg && echo '{}' > /tmp/dockercfg/config.json
DOCKER_CONFIG=/tmp/dockercfg docker compose build app
DOCKER_CONFIG=/tmp/dockercfg docker compose up -d --force-recreate app
```

## 17. The Evaluation Set Measured Nothing It Claimed To

**Symptom**

`eval/questions.json` held 50 questions and the harness produced a full report
with recall, citation accuracy and keyword coverage. Every number was
meaningless, and nothing in the output said so.

**Cause**

Four independent defects, all silent.

*The questions were never scoped to a patient.* Every entry carried the literal
placeholder `"Patient/{id}"`, and `evaluate.py` never resolved it — it called
`hybrid_search` with no `patient_ref` at all, with a comment describing the
placeholder as deliberate. "What is this patient's most recent HbA1c?" was
therefore answered from all 78 patients in the corpus at once. A question about
one record cannot be scored against an answer drawn from every record.

*The cohort did not match the corpus.* The set was written for Type 1 and
Type 2 diabetes, but the generated corpus is 78 general Synthea patients, of
whom only 11 have diabetes. Most questions had no grounding in any specific
record.

*Date expectations could never match.* `_matches_expectation` used
`\b\d{4}-\d{2}-\d{2}\b`, but rendered resources carry full ISO timestamps:

```text
"Onset 2025-04-06T12:39:43+07:00"   ->  \b after the day fails against the "T"
```

Every `date`, `duration or date`, `chronological events with dates` and
`multiple date-value pairs` expectation scored zero. The `temporal` category
read 0.20 while the answers were correct.

*Negative questions were scored on signals that punish correct behaviour.*
They name no `expected_resource_types`, so `_retrieval_recall` returned 0.0
whenever anything was retrieved — which patient-scoped retrieval always does,
since the patient has other resources. And a correct "insufficient data" answer
contains no citations, so `_citation_accuracy` returned 0.0. Answering a
negative question correctly lowered two of the three headline metrics.

**Fix**

52 questions, each naming a real `patient_ref` and each expectation grounded in
that patient's records, across two cohorts: three adults with type 2 diabetes
and its complications, and one child with the atopic march and no glucose data
at all. The pediatric patient supplies the negative controls.

`hybrid_search` is now called with the question's `patient_ref`, and
`load_questions` rejects a placeholder rather than scoring every question as a
miss. The date pattern drops the trailing boundary; `duration or date` is
checked before the generic `endswith("date")` branch that was swallowing it;
recall is not applicable for negative questions and they are excluded from
citation accuracy. Results carry `id`, `category` and `cohort`, with
per-category and per-cohort breakdowns.

`Dockerfile` now copies `eval/`, which the documented
`docker compose exec app python -m eval.evaluate` had always required.

**Verification**

Fixing the date pattern alone moved keyword coverage from 0.849 to 0.952 and
the `temporal` category from 0.20 to 1.00 — with no change to the pipeline
being measured.

| Metric | Baseline |
| --- | --- |
| Retrieval recall | 0.971 |
| Citation accuracy | 0.957 |
| Answer-keyword coverage | 0.952 |
| Grounded / partial / ungrounded | 45 / 0 / 7 |
| Latency mean / max | 14.7 s / 27.3 s |

All seven ungrounded results are the five negatives plus two answers that wrote
resource ids without brackets. Latency is entirely generation; patient-scoped
retrieval runs in 5-24 ms. The weakest categories are now real signal:
`medications` at 0.79 keyword coverage, because a simvastatin prescription was
not retrieved, and `preventive` at 0.67.

**Lesson**

A metric that cannot fail is worse than no metric. Three of these defects made
the harness report a number that was structurally incapable of reflecting the
system: a placeholder that matched nothing, a regex that matched nothing, and a
scoring rule that penalised the correct answer. Before trusting an evaluation,
check that at least one question fails for the reason you expect and at least
one passes — and confirm the fixture data actually exists in the corpus being
measured.

## Repeatable Checks

Use these commands after loading data:

```bash
# Confirm both services are running.
docker compose ps

# Confirm chunks and clinical resource types were indexed.
docker compose exec -T db psql -U fhir -d fhir_rag -c \
  "SELECT resource_type, count(*) FROM fhir_chunks GROUP BY resource_type ORDER BY count(*) DESC"

# Rebuild only when application code or dependencies change.
docker compose build app
docker compose up -d app

# Confirm stored vectors match the configured embedding backend. A hash vector
# is sparse; a transformer vector is dense. Anything far below 384 means the
# re-embed did not actually land.
docker compose exec -T db psql -U fhir -d fhir_rag -c \
  "SELECT round(avg(cardinality(array_positions(embedding::real[], 0)))) AS avg_zeros
   FROM (SELECT embedding FROM fhir_chunks LIMIT 500) s"
```

Rebuild the image **after** the last source edit. `docker compose up -d` reuses
the existing image and will silently run stale code otherwise.

Run the evaluation harness inside the container, and read the per-category
breakdown rather than only the headline averages:

```bash
docker compose exec app python -m eval.evaluate
```

Do not re-run `docker compose up` after data-only ingestion. Restart or rebuild
the app only after changing application code, Compose configuration, or its
dependencies.
