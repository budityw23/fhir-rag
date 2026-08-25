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

## Verification

- Editable installation succeeded in the project virtual environment with `pip install -e ".[dev]"`.
- Python package and configuration imports passed.
- `docker compose config` passed.
- Frontend assets are loaded from `/vendor/`; no CDN references are present.
- Database schema checks passed, including the HNSW index and absence of IVFFlat.
- Parser, renderer, chunker, embedder, and ingestion test suite passed: `20 passed`.
- Python compilation checks passed for `src/` and `tests/`.

The system-wide install command was blocked by Debian's externally managed Python policy. Verification was completed using the project-local `.venv` environment.

## Pending

- Phase 1 complete: FHIR parsing, rendering, chunking, embedding, and ingestion pipeline.
- Phase 2: Hybrid retrieval, reference resolution, and context building.
- Phase 3: LLM generation, citation mapping, FastAPI endpoints, and functional frontend.
- Phase 4: Evaluation harness, Docker integration testing, and polish.
