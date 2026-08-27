# FHIR RAG — working notes for Claude

Grounded clinical Q&A over Synthea FHIR R4 bundles. Architecture, pipeline
diagrams, and quickstart live in `README.md`. This file covers only what is
easy to get wrong and not visible in the code.

## The source is baked into the image, not mounted

The `app` service mounts only `./data/synthea` (read-only). `src/` is copied in
at build time, so `docker compose up -d` reuses the existing image and
**editing a file and restarting runs the old code silently**. Always:

```bash
docker compose build app && docker compose up -d --force-recreate app
```

Build *after* the last edit. Getting this backwards once cost a full 10-minute
re-embed that appeared to succeed and changed nothing — see
`docs/notes/fhir-rag-debugging.md` §11.

Verify what is actually running rather than assuming:

```bash
docker exec fhir_rag-app-1 md5sum src/api/routes.py; md5sum src/api/routes.py
```

Adding FHIR bundles to `data/synthea/` needs no rebuild — that path is mounted.
Frontend edits do need one, plus a browser hard-refresh, since `src/frontend`
is served as static files and gets cached.

## Tests run in the container

The host Python lacks `asyncpg`, `httpx`, and `pgvector`. Run:

```bash
docker exec fhir_rag-app-1 pip install -q pytest pytest-asyncio
docker exec fhir_rag-app-1 rm -rf /app/tests   # docker cp nests into an existing dir
docker cp tests fhir_rag-app-1:/app/tests
docker exec fhir_rag-app-1 python -m pytest -q
```

Omitting the `rm -rf` produces `/app/tests/tests` and a wall of collection
errors that look like import bugs.

## Changing the embedding backend requires a re-ingest

`EMBEDDING_BACKEND` (`transformer` default, `hash` for dependency-free runs)
changes how vectors are computed but not the column type — both are 384-dim.
Existing rows keep their old vectors until ingestion re-runs and upserts them.
Ingestion prints the number of *attempted* rows, so its summary is not evidence
the vectors changed. Check the data:

```bash
docker compose exec -T db psql -U fhir -d fhir_rag -c \
  "SELECT round(avg(cardinality(array_positions(embedding::real[], 0)))) AS avg_zeros
   FROM (SELECT embedding FROM fhir_chunks LIMIT 500) s"
```

`0` means dense transformer vectors. A large number means sparse hash vectors,
i.e. the re-embed did not land. A full re-ingest of ~77k chunks takes about
12 minutes on 16 CPU cores; run it in the background.

## `db/init.sql` only runs on a fresh volume

Schema edits do not reach a running database. Apply them with `psql` against
`fhir_rag-db-1` as well as editing the file, or the two drift apart.

## Never commit

`.gitignore` covers these, but they are the reason it exists: a live GCP
service-account key in the repo root (`*credentials*.json`), the 188 MB Synthea
JAR, `output/`, and `data/` (bulk patient bundles). Check `git status` before
any `git add -A`.

## Retrieval facts worth knowing before changing it

- `hybrid_search` fuses a vector arm and a Postgres full-text arm with
  Reciprocal Rank Fusion. Both arms over-fetch `TOP_K * 5` before fusion.
- Patient-scoped queries disable index scans on purpose: HNSW picks global
  neighbours before the patient filter is applied and can return nothing.
- Synthea emits one `Medication review due` Condition per visit. These are
  near-identical, cluster tightly, and can occupy every `Condition` slot, so
  generic "active problems" questions under-report. Naming conditions in the
  query works around it; the real fix is diversity-aware retrieval (MMR, or
  collapsing by `(resource_type, code)`).
- If an answer names the right entities but misses attributes, read the stored
  `text_content` for that resource before suspecting retrieval or the model —
  a renderer that drops a field makes it uncitable.

## Gemini/Vertex generation

`gemini-2.5-flash` charges internal reasoning against `maxOutputTokens`.
`thinkingBudget` is set explicitly in `src/generation/llm_client.py`; without
it, reasoning consumed 85% of the budget and truncated answers mid-citation.
Treat `finishReason` as a value to check — HTTP 200 is not a complete answer.

## Commit conventions

Never add `Co-Authored-By` or any other attribution trailer. Conventional-commit
subjects, with a body explaining why rather than restating the diff. Full rules
live in `~/.claude/CLAUDE.md` alongside the general behavioral guidelines.

## Debugging posture

When a grounded answer says "insufficient data", check retrieval before the
model. Rank the known-correct resource against the query and compare with
`TOP_K`; that one measurement separates a retrieval bug from a reasoning bug.
Each defect found so far is written up in `docs/notes/fhir-rag-debugging.md`
with its evidence — read it before re-diagnosing something.
