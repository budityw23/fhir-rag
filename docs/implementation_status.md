# Implementation Status

Updated: 2026-08-25

## Completed

### Phase 0: Project Scaffolding

- Task 0.1: Python project structure initialized with `pyproject.toml`.
- Added `src` package layout for ingestion, retrieval, generation, and API components.
- Added environment-backed `Settings` in `src/config.py`.
- Added asyncpg connection-pool lifecycle helpers in `src/database.py`.
- Task 0.2: Added Docker Compose, multi-stage Dockerfile, `.env.example`, and database initialization script.
- Added pgvector extension and `fhir_chunks` schema with a 384-dimensional embedding column.
- Added HNSW cosine-similarity index with `m = 16` and `ef_construction = 64`.
- Task 0.3: Added vendored Alpine.js and Pico CSS assets.
- Added placeholder frontend files: `index.html`, `app.js`, and `style.css`.
- Added Synthea data output path to `.gitignore`.

### Phase 1: Data and Ingestion

- Task 1.1: Added `src/ingestion/fhir_parser.py`.
- Parses and validates FHIR R4 Bundles with `fhir.resources`.
- Filters resources to the supported Patient, Condition, Observation, MedicationRequest, Encounter, AllergyIntolerance, Procedure, DiagnosticReport, Immunization, and CarePlan types.
- Resolves patient references and recursively extracts deduplicated FHIR references.
- Logs and skips invalid Bundles, malformed entries, unsupported resource types, and resources without IDs.
- Task 1.2: Added `src/ingestion/text_renderer.py`.
- Added dedicated human-readable renderers for all supported resource types.
- Added diabetes-aware rendering for Type 1/Type 2 Conditions, HbA1c/glucose/BMI Observations, Metformin/insulin MedicationRequests, and diabetes CarePlans.
- Added a readable scalar-field fallback for unknown resource types.
- Task 1.3: Added `src/ingestion/chunker.py`.
- Converts each `ParsedResource` into exactly one `FHIRChunk`.
- Extracts resource dates using the documented priority: `effectiveDateTime`, `onsetDateTime`, `recordedDate`, `authoredOn`, then `period.start`.
- Extracts deduplicated coded values from nested FHIR `coding` collections, including SNOMED, LOINC, RxNorm, and vaccine codes.
- Uses `render_resource_text` for chunk text content.
- Task 1.4: Added `src/ingestion/embedder.py`.
- Wraps `sentence-transformers` with lazy model loading.
- Supports batch text embedding and single query embedding using the same model.
- Validates and returns 384-dimensional float vectors.
- Task 1.5: Added `src/ingestion/ingest.py` CLI pipeline.
- Orchestrates Bundle parsing, one-resource chunking, 32-item batch embedding, and pgvector storage.
- Uses pgvector asyncpg codecs and `ON CONFLICT (resource_id) DO NOTHING` for idempotent ingestion.
- Prints parsing, embedding progress, and final `{bundles, resources, chunks_stored}` statistics.
- Handles empty or unsupported-only data directories without opening a database connection.

### Phase 2: Retrieval

- Task 2.1: Added `src/retrieval/hybrid_search.py`.
- Combines pgvector cosine similarity with optional patient, resource-type, and date-range filters.
- Uses parameterized SQL only and returns typed, similarity-ranked `SearchResult` values.
- Handles empty result sets without special-case database errors.
- Task 2.2: Added `src/retrieval/reference_resolver.py`.
- Resolves referenced resources through direct `resource_id` lookups, capped at two hops by default.
- Deduplicates primary and supplementary resources and assigns supplementary similarity `0.0`.
- Task 2.3: Added `src/retrieval/context_builder.py`.
- Builds citation-ready context grouped by resource type.
- Separates ranked primary resources from supporting resolved references and includes resource IDs in brackets.

### Phase 3: Generation

- Task 3.1: Added `src/generation/prompts/clinical_qa.jinja2`.
- Defines strict FHIR grounding rules, citation syntax, insufficient-data behavior, and no-fabrication requirements.
- Renders with `context` and `question` variables.
- Task 3.2: Added `src/generation/llm_client.py`.
- Provides a common async `LLMClient` interface for Claude and Ollama.
- Claude uses the async Anthropic SDK with `claude-sonnet-4-6`.
- Ollama uses the `/api/generate` endpoint with non-streaming responses.
- Both providers return content, model, input-token, and output-token metadata.
- Task 3.3: Added `src/generation/citation_mapper.py`.
- Extracts `[ResourceType/id]` citations and matches them against retrieved `SearchResult` resources.
- Produces citation snippets and dates with grounded, partially grounded, or ungrounded confidence.

### Phase 4: API

- Task 4.1: Added `src/api/schemas.py` with the documented request and response models.
- Task 4.1: Added `src/api/routes.py` with query orchestration, patient listing, resource lookup, and health endpoints.
- Task 4.1: Added `src/api/main.py` with FastAPI app factory, lifecycle initialization/cleanup, and frontend static mounting.
- Query errors return HTTP 500, validation errors return HTTP 422, and missing resources return HTTP 404.
- Constrained FastAPI to the documented 0.115 release line for compatible Starlette/httpx behavior.
- Task 4.2: Implemented the Alpine.js frontend in `src/frontend/index.html`, `app.js`, and `style.css`.
- Added patient loading, patient selection, Enter-to-submit question input, diabetes example questions, loading/error states, confidence badges, and expandable citation evidence.
- Added responsive Pico CSS overrides for grounded/partial/ungrounded confidence states, citations, and loading feedback.
- All frontend assets remain local and are loaded from `/vendor/` without CDN references.

## Verification

- Editable installation succeeded in the project virtual environment with `pip install -e ".[dev]"`.
- Python package and configuration imports passed.
- `docker compose config` passed.
- Frontend assets are loaded from `/vendor/`; no CDN references are present.
- Database schema checks passed, including the HNSW index and absence of IVFFlat.
- Full parser, renderer, chunker, embedder, ingestion, retrieval, generation, and API test suite passed: `35 passed`.
- Frontend static checks passed for vendored assets, API references, citation bindings, and no CDN references.
- Python compilation checks passed for `src/` and `tests/`.

The system-wide install command was blocked by Debian's externally managed Python policy. Verification was completed using the project-local `.venv` environment.

## Pending

- Phase 1 complete: FHIR parsing, rendering, chunking, embedding, and ingestion pipeline.
- Phase 2 complete: hybrid retrieval, reference resolution, and context building.
- Phase 3 complete: prompt template, LLM provider abstraction, and citation mapping.
- Phase 4 complete: FastAPI application and functional frontend.
- Phase 5: evaluation harness, Docker integration testing, and polish.
