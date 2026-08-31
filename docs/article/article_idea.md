# Article Ideas: Diabetes FHIR RAG

## Project summary

Diabetes FHIR RAG is a grounded clinical question-answering system over Synthea-generated FHIR R4 bundles. Ingestion parses bundles as raw JSON (deliberately skipping whole-bundle Pydantic validation), normalises `urn:uuid` `fullUrl` references to canonical `ResourceType/id` form, renders each of ten supported resource types into human-readable text via type-specific renderers, and stores one chunk per resource in PostgreSQL with a 384-dim `all-MiniLM-L6-v2` embedding, a generated `tsvector` column, plus structured metadata (patient ref, date, SNOMED/LOINC/RxNorm codes, outbound references). Retrieval fuses an HNSW vector arm and a GIN full-text arm with weighted Reciprocal Rank Fusion inside a single `NOT MATERIALIZED` CTE query, then follows FHIR references up to two hops to pull in supporting resources. A Jinja2 prompt forces `[ResourceType/id]` citations and an explicit "insufficient data" refusal; a citation mapper validates every cited id against the retrieved set and classifies the answer as grounded, partially grounded, or ungrounded. FastAPI serves the pipeline plus an Alpine.js/Pico CSS frontend, everything runs under Docker Compose, and a 52-question evaluation harness across two cohorts (adult diabetes, pediatric atopic) scores retrieval recall, citation accuracy, answer-keyword coverage, and latency. The most valuable asset for writing is `docs/notes/fhir-rag-debugging.md`: fifteen documented defects, each with the measurement that identified it.

---

## Article ideas in publishing order

### 1. I Built a RAG System That Answers Questions From FHIR Records and Refuses to Guess

**Angle.** The anchor piece. A grounded clinical Q&A system over synthetic patient records where every answer carries resource-level citations and an explicit grounding verdict, because in a clinical context a confident wrong answer is worse than no answer. Walks the full architecture end to end and gets the reader running it locally in a few commands.

**Key sections.**
- The problem: clinical questions live across a dozen linked resources
- What "grounded" means here: `[ResourceType/id]` citations or "insufficient data"
- The pipeline, one hop at a time (parse, render, embed, retrieve, resolve, generate, verify)
- Why Postgres does all four jobs (rows, vectors, full text, joins)
- Running it: Synthea, Docker Compose, ingest, ask
- What it scores, and what it still gets wrong

**Code to highlight.** The mermaid architecture diagram from `README.md`, `src/api/routes.py:query_patient` as the seven-line spine of the whole system, `src/generation/prompts/clinical_qa.jinja2`, the baseline metrics table.

**Audience.** All four. This is the piece everything else links back to.

**Length.** Medium (2000-2500).

**Reference links.**
- https://hl7.org/fhir/R4/index.html
- https://github.com/synthetichealth/synthea
- https://github.com/pgvector/pgvector
- https://www.anthropic.com/engineering/contextual-retrieval

---

### 2. FHIR R4 for ML Engineers: What Actually Lives in a Patient Record

**Angle.** Most RAG tutorials assume a folder of PDFs. A FHIR record is a graph of typed, coded, cross-referencing resources, and that difference decides your chunking, your metadata, and your citations. This explains the ten resource types the project indexes in terms an ML engineer can act on, not in spec language.

**Key sections.**
- A Bundle is not a document, it is a graph
- The ten types that carry clinical meaning, and the ones that do not
- CodeableConcept, coding arrays, and why `display` is not a label you can trust
- References: `subject`, `patient`, `fullUrl`, and `urn:uuid`
- What Synthea gives you and where it lies

**Code to highlight.** `src/ingestion/fhir_parser.py:SUPPORTED_TYPES`, `resolve_patient_ref`, a real Synthea Observation JSON next to its rendered text output.

**Audience.** ML engineers, fullstack devs entering healthcare.

**Length.** Medium (1800-2200).

**Reference links.**
- https://hl7.org/fhir/R4/resourcelist.html
- https://hl7.org/fhir/R4/datatypes.html#CodeableConcept
- https://loinc.org/get-started/what-loinc-is/
- https://synthetichealth.github.io/synthea/

---

### 3. One Resource, One Chunk: FHIR-Aware Chunking Beats Token Windows

**Angle.** Recursive character splitting is the default in every RAG tutorial and it is wrong for FHIR. A resource is already a semantic unit with a stable id, so splitting it destroys the one thing you need for citations and merging several destroys clinical separation. The chunk boundary was the easiest correct decision in the project and it paid for itself at citation time.

**Key sections.**
- Why 512-token windows fail on clinical records
- The resource as a natural chunk boundary
- Metadata that survives the chunk: date, codes, references, patient
- Date extraction across five differently-named FHIR fields
- The cost: near-duplicate resources compete for slots (foreshadowing article 9)

**Code to highlight.** `src/ingestion/chunker.py` in full, `extract_date` with its priority list, `extract_codes` recursive walk.

**Audience.** ML engineers, FHIR devs.

**Length.** Medium (1500-2000).

**Reference links.**
- https://python.langchain.com/docs/concepts/text_splitters/
- https://hl7.org/fhir/R4/observation.html
- https://www.pinecone.io/learn/chunking-strategies/

---

### 4. Embeddings Do Not Read JSON: Rendering FHIR Resources Into Text

**Angle.** Between the FHIR JSON and the embedding model sits a renderer nobody talks about, and it is where most of the retrieval quality is decided. A renderer that drops a field makes that field permanently uncitable, no matter how good the model is. This is the article about the layer that cost the most bugs.

**Key sections.**
- What an embedding model sees when you feed it raw JSON
- Ten renderers, one signature
- The `_first_coding` path walker, and the array-vs-object trap in `Encounter.type`
- The bug: seven allergies with no reactions
- Reading `text_content` before blaming the model

**Code to highlight.** `src/ingestion/text_renderer.py:_first_coding`, `render_allergy_intolerance`, `_reaction_text`, before/after rendered output from debugging note §12.

**Audience.** FHIR devs, ML engineers.

**Length.** Medium (1800-2200).

**Reference links.**
- https://hl7.org/fhir/R4/allergyintolerance.html
- https://sbert.net/docs/sentence_transformer/pretrained_models.html
- https://hl7.org/fhir/R4/narrative.html

---

### 5. Setting Up pgvector for Clinical Data: Schema, HNSW, and the Filters That Break It

**Angle.** A step-by-step build of the storage layer, with the two non-obvious decisions explained: HNSW over IVFFlat, and a generated `tsvector` column so the lexical index can never drift from the text. Ends with the failure that surprises everyone, where a selective SQL filter and an approximate index produce zero rows from a table full of matches.

**Key sections.**
- The schema, column by column, and why each one exists
- HNSW over IVFFlat for a dataset that keeps growing
- A generated column beats an ingestion-time write path
- Why a valid patient filter returned nothing
- `init.sql` only runs on a fresh volume: shipping migrations from day one

**Code to highlight.** `db/init.sql`, `db/migrations/001_add_text_search.sql`, the `SET LOCAL enable_indexscan = off` block in `src/retrieval/hybrid_search.py`.

**Audience.** Fullstack devs, healthcare IT, ML engineers.

**Length.** Medium (2000-2500).

**Reference links.**
- https://github.com/pgvector/pgvector#hnsw
- https://www.postgresql.org/docs/current/textsearch-controls.html
- https://www.postgresql.org/docs/current/ddl-generated-columns.html
- https://tembo.io/blog/vector-indexes-in-pgvector

---

### 6. My Hybrid Search Was Not Hybrid: A Retrieval Arm That Silently Matched Nothing

**Angle.** The single best story in the project. `websearch_to_tsquery` joins terms with AND, so a full question needs every stemmed term present in one short clinical chunk, which never happens. The lexical arm returned zero rows on every realistic question for weeks, and end-to-end answers still looked fine because the vector arm carried the fusion. A failing component that improves nothing looks exactly like a working one from the outside.

**Key sections.**
- The plan: vector arm plus lexical arm, fused with RRF
- The tsquery that matched nothing, shown as stemmed output
- Why it went unnoticed: the other arm carried the result
- Rewriting AND to OR while keeping `websearch_to_tsquery` for tokenising
- OR-matching over-fires, so the fusion is weighted at 0.5
- The lesson: assert per-arm row counts, not just fused quality

**Code to highlight.** The `lexical_query` CTE and its `replace(... ' & ', ' | ')` rewrite, `LEXICAL_WEIGHT`, the stemmed tsquery examples from debugging note §15.

**Audience.** ML engineers, fullstack devs. This one travels beyond healthcare.

**Length.** Medium (2000-2500).

**Reference links.**
- https://www.postgresql.org/docs/current/textsearch-controls.html#TEXTSEARCH-PARSING-QUERIES
- https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
- https://weaviate.io/blog/hybrid-search-fusion-algorithms

---

### 7. A CTE Referenced Twice Turned a 5 ms Query Into 3.9 Seconds

**Angle.** A short, sharp Postgres piece. PostgreSQL materialises a CTE referenced more than once, which put a sequential scan between the query and both the HNSW and GIN indexes. One keyword, `NOT MATERIALIZED`, restored both. The wider point is that an index existing is not evidence an index is used.

**Key sections.**
- The query: one filter CTE, two arms, one join
- Reading the plan that told the truth
- Why PostgreSQL materialises multiply-referenced CTEs
- `NOT MATERIALIZED`, and when you want the opposite
- Making `EXPLAIN (ANALYZE)` part of the change, not the postmortem

**Code to highlight.** The `filtered AS NOT MATERIALIZED` CTE, the before/after `EXPLAIN` output from debugging note §15.

**Audience.** Fullstack devs, anyone running vector search inside Postgres.

**Length.** Short (1000-1400).

**Reference links.**
- https://www.postgresql.org/docs/current/queries-with.html#QUERIES-WITH-CTE-MATERIALIZATION
- https://www.postgresql.org/docs/current/using-explain.html
- https://github.com/pgvector/pgvector#filtering

---

### 8. Following the Graph: Two-Hop FHIR Reference Resolution as Free Context

**Angle.** Vector search retrieves the resource that matches the question. The answer often needs the one next to it: the Encounter a BMI was taken at, the Condition a MedicationRequest treats. Because FHIR resources carry their own outbound references, a bounded graph walk supplies that context for the price of one indexed lookup per hop.

**Key sections.**
- The question vector search cannot answer alone
- Storing outbound references as a `TEXT[]` at ingestion
- Breadth-first, deduplicated, capped at two hops
- Marking supplementary context so the model ranks it correctly
- When to stop: why hop three was not worth it

**Code to highlight.** `src/retrieval/reference_resolver.py` in full, `extract_references` in the parser, `_render_grouped` in `context_builder.py`.

**Audience.** FHIR devs, ML engineers interested in graph RAG.

**Length.** Medium (1500-2000).

**Reference links.**
- https://hl7.org/fhir/R4/references.html
- https://neo4j.com/blog/genai/what-is-graphrag/
- https://hl7.org/fhir/R4/search.html#include

---

### 9. Synthetic Data Lies: When 12 Identical Conditions Ate Every Retrieval Slot

**Angle.** Asking "what are this patient's active problems?" returned exactly one: "Medication review due". Synthea emits one of those per visit, they embed to nearly the same vector, and twelve of them took every Condition slot in the top 25. Top-k retrieval assumes candidates are informative and distinct, and near-duplicates violate the second half quietly.

**Key sections.**
- The answer that was technically correct and clinically useless
- The resource-type histogram that showed the problem in one line
- Why asking the model to exclude duplicates cannot work
- What actually fixed it, and why that fix was luck
- MMR and code-collapsing: the robust fix I have not shipped yet

**Code to highlight.** The histogram query, `ADMINISTRATIVE_CONDITIONS` in `src/api/suggestions.py`, a sketch of `(resource_type, code)` collapsing before `top_k`.

**Audience.** ML engineers, healthcare IT evaluating synthetic data.

**Length.** Medium (1500-2000).

**Reference links.**
- https://www.cs.cmu.edu/~jgc/publication/The_Use_MMR_Diversity_Based_LTMIR_1998.pdf
- https://synthetichealth.github.io/synthea/docs/
- https://docs.haystack.deepset.ai/docs/diversityranker

---

### 10. Insufficient Data Is a Feature: Designing Refusal Into a Clinical RAG System

**Angle.** Most RAG demos are judged on whether the answer sounds right. In a clinical system the more important property is that the system declines when the record does not support an answer. This covers the prompt rules, the citation mapper that verifies every id against the retrieved set, and the three-state grounding verdict surfaced to the user.

**Key sections.**
- Why a plausible fabricated HbA1c is the worst possible output
- The prompt contract: cite `[ResourceType/id]` or refuse
- Verification is not trust: regex-matching citations back to retrieved rows
- Grounded, partially grounded, ungrounded, and what each means to a reader
- Negative controls: asking a six-year-old about their HbA1c

**Code to highlight.** `src/generation/citation_mapper.py` in full, `clinical_qa.jinja2`, the `confidenceLabel` getter in `src/frontend/app.js`.

**Audience.** Healthcare IT, ML engineers, anyone shipping RAG into a regulated domain.

**Length.** Medium (1800-2200).

**Reference links.**
- https://arxiv.org/abs/2305.14627
- https://www.nature.com/articles/s41746-023-00873-0
- https://docs.claude.com/en/docs/build-with-claude/citations

---

### 11. Gemini's Thinking Tokens Ate 85% of My Output Budget

**Angle.** Answers stopped mid-word, sometimes after 182 characters, and were reported as ungrounded because the cut landed inside a citation marker. `gemini-2.5-flash` charges internal reasoning against `maxOutputTokens`, and at a 2048 cap it spent 1742 tokens thinking and 302 answering. HTTP 200 is not evidence of a complete answer.

**Key sections.**
- The symptom: truncated answers scored as hallucination
- Reading `finishReason` and `thoughtsTokenCount` instead of guessing
- Three configurations, measured side by side
- Bounding `thinkingBudget` uses fewer thinking tokens than the default
- Treating provider response metadata as an assertion target

**Code to highlight.** `_google_generation_config`, the `MAX_TOKENS` warning branch in `src/generation/llm_client.py`, the three-row measurement table from debugging note §13.

**Audience.** ML engineers, anyone using thinking models for extraction.

**Length.** Short-to-medium (1200-1600).

**Reference links.**
- https://ai.google.dev/gemini-api/docs/thinking
- https://ai.google.dev/api/generate-content#FinishReason
- https://docs.claude.com/en/docs/build-with-claude/extended-thinking

---

### 12. One Client, Four LLM Providers, No Framework

**Angle.** The project talks to Claude, Gemini, Vertex Express, and Ollama through 160 lines of `httpx` and one dataclass, with no orchestration framework. This argues that for a fixed, single-turn prompt shape, a provider abstraction you wrote is cheaper to debug than one you imported, and shows exactly where the provider differences actually are.

**Key sections.**
- What the four providers genuinely disagree about (system prompts, roles, usage fields)
- Vertex Express accepts only user and model roles
- A normalised `LLMResponse` and why token counts belong in it
- The case against a framework at this size
- Where I would reach for one instead

**Code to highlight.** `src/generation/llm_client.py:generate` and `_generate_google`, the provider selection in `src/api/main.py:lifespan`.

**Audience.** Fullstack devs, ML engineers.

**Length.** Medium (1500-2000).

**Reference links.**
- https://ai.google.dev/gemini-api/docs/quickstart
- https://cloud.google.com/vertex-ai/generative-ai/docs/start/express-mode/overview
- https://docs.claude.com/en/api/messages
- https://github.com/ollama/ollama/blob/main/docs/api.md

---

### 13. Evaluating a Clinical RAG System Against Records That Actually Exist

**Angle.** The first version of the evaluation set used placeholder patient refs and invented expectations, which measures nothing. Rebuilding it against real ids from the generated corpus, across two deliberately different cohorts, turned the harness from decoration into the thing that catches regressions. Includes the two scoring rules that keep correct refusals from being punished.

**Key sections.**
- Four metrics: retrieval recall, citation accuracy, keyword coverage, latency
- Grounding questions in a real corpus, and validating that at load time
- Two cohorts on purpose: adult diabetes and a pediatric atopic child
- Negative questions need different scoring, not zero scores
- Reading a breakdown: which categories are weak and why

**Code to highlight.** `eval/evaluate.py:load_questions` with its `patient_ref` validation, `_retrieval_recall`, `_aggregate` and the `citable` filter, a sample entry from `eval/questions.json`.

**Audience.** ML engineers, healthcare IT.

**Length.** Long (2500-3000).

**Reference links.**
- https://docs.ragas.io/en/stable/concepts/metrics/
- https://github.com/explodinggradients/ragas
- https://arxiv.org/abs/2309.15217
- https://www.evidentlyai.com/llm-guide/rag-evaluation

---

### 14. FHIR RAG Is Not Document RAG, and the Difference Starts at Ingestion

**Angle.** A comparative piece. Document RAG optimises for finding the right passage in prose; FHIR RAG optimises for assembling the right set of typed records and proving where each fact came from. Every layer changes: chunking, metadata, filtering, citation, and what "correct" means. Written for people about to point a generic RAG stack at clinical data.

**Key sections.**
- Passages versus records
- Structured filters do work that similarity cannot (patient, date, type)
- Citations to ids, not page numbers
- Terminology codes are a retrieval signal a text splitter throws away
- Where document RAG techniques still apply

**Code to highlight.** The `hybrid_search` parameter list as the argument in miniature, the `codes` JSONB column, a contrast between a generic splitter and `chunk_resource`.

**Audience.** ML engineers, healthcare IT, FHIR devs.

**Length.** Medium (1800-2200).

**Reference links.**
- https://hl7.org/fhir/R4/search.html
- https://www.hl7.org/fhir/R4/terminologies.html
- https://arxiv.org/abs/2312.10997

---

### 15. Why FHIR Makes a Better Foundation for Healthcare RAG Than Flat Tables

**Status: already drafted.** Full text in `docs/article/article-fhir-rag-vs-tabular.md` (142 lines, ~1700 words). The notes below are revision notes, not a brief.

**Angle.** The comparative piece of the series, and the argument that sits upstream of every other article: data representation is chosen before the vector store or the embedding model, and choosing flat tables means rebuilding by hand what FHIR already gives you. Six structural advantages (resource-as-chunk, self-describing fields, terminology bindings, reference traversal, preserved nesting, portability across sites) against one honest cost, verbosity.

**Key sections.** As drafted: each resource is already a meaningful chunk; semantic structure the LLM can use; terminology bindings give precision; references create a traversable graph; nested and polymorphic data stays intact; interoperability makes the pipeline portable; the honest trade-off; a practical architecture.

**Code to highlight.** Currently uses illustrative FHIR JSON only. Two swaps would make it much stronger and tie it into the series:
- Replace the hand-written `Condition` snippet with a real Synthea resource next to its `render_condition` output from `src/ingestion/text_renderer.py`. That demonstrates the verbosity trade-off and its solution in one before/after, which the draft currently only asserts.
- Replace the `MedicationRequest` reference snippet with `src/retrieval/reference_resolver.py`, so section 4's claim about traversal is backed by the 52 lines that actually do it.

**Two claims to reconcile with the repo before publishing.**
- The practical architecture says "parse each resource using a FHIR library (e.g. `fhir.resources` in Python)". The project deliberately abandoned exactly that: whole-Bundle validation was expensive on large Synthea bundles and incompatible with some emitted fields, so ingestion parses raw JSON and validates shape explicitly (debugging note §6, and the comment in `parse_bundle`). Recommending the library while the repo does not use it is the kind of gap a reader who opens the code will notice. Rewriting it as "parse the JSON directly, and here is why I stopped using the library" turns a contradiction into a credible aside.
- It also says to "store vectors in pgvector alongside the full FHIR JSON". The project stores rendered `text_content` plus structured metadata, not the source JSON. Either soften the step or note that keeping the raw resource is the natural extension and say why it was not needed.

**Style pass against the series guidelines.** Retitle `## Conclusion` to something substantive; drop or shorten the numbered `## 1.` through `## 6.` headings, which read as a listicle where the rest of the series uses prose headings; replace the generic closing bio with the project repo link used across the series. The voice, the first person, and the honest trade-off section already match. No em dashes present.

**Overlap with article 14.** Both are comparative and both argue from structure, so they cannibalise each other if published close together. Keep them distinct on the axis of comparison: 14 is FHIR RAG versus *document* RAG (passages against records, page numbers against ids), 15 is FHIR versus *flat tables* (reconstructing a schema against inheriting one). Publish them at least a month apart, and cross-link so each names what the other covers.

**Audience.** Healthcare IT, ML engineers entering healthcare, FHIR devs. The most linkable piece in the series for the interoperability community, which is why the draft's `chat.fhir.org` sign-off is a good instinct.

**Length.** Medium, currently ~1700 words. The two code swaps take it to roughly 2200.

**Reference links.** Add to what the draft already implies:
- https://hl7.org/fhir/R4/references.html
- https://www.hl7.org/fhir/R4/terminologies.html
- https://build.fhir.org/ig/HL7/fhir-omop-ig/ (the tabular counterpart worth naming: OMOP CDM is the serious flat-table alternative, and the draft is stronger for engaging with it rather than with generic CSV exports)
- https://ohdsi.github.io/CommonDataModel/

---

### 16. Why I Put the Vector Index in Postgres Instead of a Vector Database

**Angle.** An opinion piece with the receipts. Patient-scoped filtering, reference resolution, patient listing, and suggestion building are all relational queries against the same rows the vectors live on. A dedicated vector store would have meant a second system and a join across the network for every one of them. Honest about the ceiling, including the HNSW-plus-filter failure the design forced me to handle.

**Key sections.**
- The queries that are not vector queries
- One table, four access patterns, zero synchronisation
- Operational cost: one Compose service instead of two
- What I gave up (managed scaling, purpose-built filtering)
- The threshold where I would move

**Code to highlight.** The four distinct query shapes in `routes.py` and `hybrid_search.py` against `fhir_chunks`, `docker-compose.yml`.

**Audience.** Fullstack devs, healthcare IT, ML engineers.

**Length.** Medium (1500-2000).

**Reference links.**
- https://github.com/pgvector/pgvector
- https://supabase.com/blog/pgvector-vs-pinecone
- https://www.timescale.com/blog/pgvector-vs-pinecone/

---

### 17. The Re-Embed That Computed 77,466 Vectors and Saved None of Them

**Angle.** Ten minutes of CPU, a success message reading `chunks_stored: 77466`, and not one vector changed. Two silent failures compounded: `ON CONFLICT DO NOTHING` against rows that all already existed, and a Docker image built before the fix that would have mattered. The exit status was green throughout. The fix is a habit, not a patch: assert on the stored data.

**Key sections.**
- Idempotent and refreshing upserts are not the same thing
- Why the job reported success (attempted rows, not written rows)
- The second failure: `docker compose up` reuses a stale image
- The one-line check that would have caught it in seconds
- Turning that check into a documented repeatable

**Code to highlight.** The `ON CONFLICT ... DO UPDATE` block in `src/ingestion/ingest.py`, the `avg_zeros` verification query, the cosine before/after numbers from debugging note §11.

**Audience.** ML engineers, data engineers. Broadly applicable.

**Length.** Short-to-medium (1200-1600).

**Reference links.**
- https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT
- https://docs.docker.com/reference/cli/docker/compose/up/
- https://www.getdbt.com/blog/data-quality-testing

---

### 18. Suggestions That Read the Chart: Generating Example Questions Per Patient

**Angle.** A small feature with a disproportionate effect on how the system is perceived. Offering "What is the latest HbA1c?" to a six-year-old with no glucose results invites a question the record cannot answer and makes a correct refusal look like a bug. The suggestion builder reads the patient's own active conditions and available resource types, and ranks out Synthea's social-determinant findings so it does not ask when "Unemployed" was diagnosed.

**Key sections.**
- Static examples set up your system to fail
- Deriving questions from the indexed record
- Ranking: clinical conditions first, social findings last, administrative never
- Naming conditions explicitly to steer retrieval
- The frontend contract, in about forty lines of Alpine

**Code to highlight.** `src/api/suggestions.py:_condition_names` and `build_suggestions`, the `/api/suggestions` route, `loadSuggestions` and the `$watch` in `app.js`.

**Audience.** Fullstack devs, healthcare IT, product-minded engineers.

**Length.** Medium (1500-1800).

**Reference links.**
- https://hl7.org/fhir/R4/condition.html
- https://alpinejs.dev/directives/data
- https://www.hl7.org/gravity/

---

### 19. 90 Lines of Alpine.js and No Build Step

**Angle.** The frontend is one HTML file, one 90-line JS file, and Pico CSS, with vendored dependencies and no bundler, transpiler, or `node_modules`. For an interface that is a patient picker, a textarea, and a result panel, React would have added a build pipeline to maintain and nothing the user can see. Also honest about where this stops scaling.

**Key sections.**
- What the interface actually has to do
- Alpine's component model in one function
- Vendoring instead of a CDN, and what that buys under a strict setup
- Serving static files straight from FastAPI
- The point where I would switch

**Code to highlight.** `src/frontend/app.js` in full, the `StaticFiles` mount in `create_app`, the script-order bug from debugging note §1.

**Audience.** Fullstack devs.

**Length.** Short (1000-1400).

**Reference links.**
- https://alpinejs.dev/start-here
- https://picocss.com/docs
- https://fastapi.tiangolo.com/tutorial/static-files/

---

### 20. What Software Engineers Get Wrong About Clinical Data

**Angle.** The domain piece, and the one that most reflects eight years inside a clinical research unit. Engineers arrive expecting rows and find a graph of assertions with provenance, status, and negation, where absence of a record is not absence of a condition and a code is a claim rather than a fact. Written to make the earlier technical articles legible to people who have never seen a real chart.

**Key sections.**
- A record is a history of assertions, not a current-state table
- `clinicalStatus` versus `verificationStatus`, and why both exist
- Missing is not negative
- Coded does not mean comparable: SNOMED, LOINC, RxNorm, and local codes
- Synthetic data is safe and it is also not real
- What this means when an LLM sits on top

**Code to highlight.** `_status` in `text_renderer.py` walking two status fields, the `expected_codes` structure in `questions.json`, the negative-control questions.

**Audience.** ML engineers, fullstack devs entering healthcare. Highest shareability of the series.

**Length.** Long (2500-3000).

**Reference links.**
- https://hl7.org/fhir/R4/condition-definitions.html#Condition.clinicalStatus
- https://www.snomed.org/what-is-snomed-ct
- https://www.nlm.nih.gov/research/umls/rxnorm/index.html
- https://pubmed.ncbi.nlm.nih.gov/23304284/

---

### 21. Debugging RAG Systems: 15 Defects and the Measurement That Found Each One

**Angle.** The capstone. Every defect in this project fell into one of three buckets, and telling them apart took one measurement each. The recurring lesson across all fifteen: end-to-end quality is a lagging indicator that hides component failures, and a green exit status is never evidence that state changed.

**Key sections.**
- Three buckets: data never indexed, data never retrieved, data never rendered
- The one measurement that separates a retrieval bug from a reasoning bug
- Failures that look like success (silent arms, attempted-row counts, HTTP 200)
- Keeping a defect log with evidence, not just fixes
- A checklist for the next clinical RAG system

**Code to highlight.** The rank-the-known-answer probe, the per-arm row-count assertion, the repeatable checks block from `docs/notes/fhir-rag-debugging.md`.

**Audience.** ML engineers, anyone operating a RAG system in production.

**Length.** Long (3000+).

**Reference links.**
- https://arxiv.org/abs/2401.05856
- https://www.anthropic.com/engineering/built-multi-agent-research-system
- https://eugeneyan.com/writing/llm-patterns/

---

## Suggested publishing cadence

One article per week, twenty-one weeks. The order above is deliberate: articles 1 through 5 build the mental model a reader needs before the debugging stories land, and articles 6, 9, 11, and 17 are the ones most likely to travel outside healthcare, so they should not be spent while the series has no back catalogue to link into.

Priority tiers if you cannot sustain weekly:

- **Must publish (the spine).** 1, 3, 6, 10, 13, 20. These six stand alone and cover introduction, chunking, the best debugging story, the grounding thesis, evaluation, and the domain piece that shows the healthcare experience.
- **High value, publish second.** 4, 5, 7, 9, 11, 15, 17, 21.
- **Fill and breadth.** 2, 8, 12, 14, 16, 18, 19.

Publish 1 and 2 in the same week so the anchor has something to link forward to. Hold 21 for last; it is the retrospective and it needs the other twenty to reference.

One scheduling exception. Article 15 is already drafted, so the temptation is to publish it immediately, and its argument genuinely is upstream of the rest of the series. But it asserts things the later articles prove: that resources are natural chunks (article 3), that references are traversable for free (article 8), that terminology codes are a retrieval signal (article 14). Publishing it before those exist means it lands as opinion with no receipts, and it cannot link forward to anything. Slot it where it sits, after article 14 has drawn the document-RAG contrast, and it reads as a conclusion the series has earned. If you want it out sooner, publish 1 and 2 first at minimum so it has an anchor to link back to, and expect to update it with links once 3 and 8 exist.

## Quick wins

Four articles that can be drafted fastest, because the source material is already written and the code is clean enough to quote without editing.

**Article 15 (FHIR versus flat tables).** Already drafted at ~1700 words in `docs/article/article-fhir-rag-vs-tabular.md`. What remains is a revision pass, not a write: swap two illustrative JSON snippets for real code from the repo, reconcile the `fhir.resources` and "store the full FHIR JSON" claims with what ingestion actually does, and replace the listicle headings and generic conclusion. Half a day rather than two.

**Article 11 (Gemini thinking tokens).** Debugging note §13 already contains the symptom, the JSON evidence, the three-configuration comparison table, and the lesson. The code is 15 lines. This is a copy-edit away from a draft, and it is the most immediately useful piece to non-healthcare readers.

**Article 7 (the materialised CTE).** Debugging note §15 has the `EXPLAIN` output before and after, the timing numbers, and a one-keyword fix. Short, self-contained, and the kind of Postgres post that gets bookmarked. No new measurement needed.

**Article 17 (the silent re-embed).** Debugging note §11 has both failure modes, the cosine numbers before and after, and the verification query. The narrative arc (green build, ten minutes of CPU, nothing changed) writes itself, and the lesson generalises to any derived-column pipeline.

A fifth near-win: **article 8 (reference resolution)**, because `reference_resolver.py` is 52 lines, fully commented, and needs no accompanying war story to be worth reading.

## Drafts on disk

| Article | File | State |
| --- | --- | --- |
| 15 | `docs/article/article-fhir-rag-vs-tabular.md` | Complete draft, needs the revision pass described in its entry |
