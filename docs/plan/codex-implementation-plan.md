# fhir-rag — Codex Technical Implementation Plan (Diabetics Use Case)

Step-by-step implementation tasks designed for Codex (OpenAI's coding agent).
Each task is self-contained with clear inputs, outputs, and acceptance criteria.
**Domain focus: Type 1 and Type 2 Diabetes management.**

> Created 2026-08-25. Companion to `fhir-rag-project-plan.md`.
> Validation questions: `docs/diabetics-validation-questions.md`.

---

## How to Use This With Codex

Each task below is a Codex prompt unit. Feed them sequentially — each task's output becomes the next task's input. Tasks within a phase can sometimes be parallelized (noted where applicable).

**Codex environment setup:**
```bash
# Before starting, ensure the repo has:
# 1. pyproject.toml with dependencies
# 2. A running postgres+pgvector instance (or Docker)
# 3. .env with ANTHROPIC_API_KEY (for generation tasks)
```

---

## Phase 0 — Project Scaffolding

### Task 0.1: Initialize project structure

**Prompt for Codex:**
> Create a Python project using pyproject.toml with the following structure. Use src layout. Dependencies: fastapi[standard]>=0.115, uvicorn[standard], asyncpg, pgvector, fhir.resources>=7.1, sentence-transformers>=3.0, anthropic, jinja2, pydantic-settings, httpx. Dev dependencies: pytest, pytest-asyncio, httpx (for TestClient). Python requires >=3.11.

**Files to create:**
```
pyproject.toml
src/__init__.py
src/config.py
src/database.py
src/ingestion/__init__.py
src/retrieval/__init__.py
src/generation/__init__.py
src/api/__init__.py
```

**Acceptance criteria:**
- `pip install -e ".[dev]"` succeeds
- All `__init__.py` files exist
- `src/config.py` contains a pydantic `Settings` class reading from env:
  - `DATABASE_URL` (default: `postgresql://fhir:fhir@localhost:5432/fhir_rag`)
  - `LLM_PROVIDER` (default: `claude`, enum: `claude|ollama`)
  - `ANTHROPIC_API_KEY` (optional)
  - `OLLAMA_BASE_URL` (default: `http://localhost:11434`)
  - `EMBEDDING_MODEL` (default: `all-MiniLM-L6-v2`)
  - `TOP_K` (default: 10)
  - `MAX_REFERENCE_HOPS` (default: 2)
- `src/database.py` contains async connection pool setup using asyncpg

### Task 0.2: Docker Compose and database schema

**Prompt for Codex:**
> Create docker-compose.yml with two services: `db` (pgvector/pgvector:pg16) and `app` (builds from Dockerfile). Create Dockerfile for FastAPI app. Create db/init.sql with the fhir_chunks table schema using HNSW index.

**Files to create:**
```
docker-compose.yml
Dockerfile
.env.example
db/init.sql
```

**Acceptance criteria:**
- `docker compose up db -d` starts Postgres with pgvector extension enabled
- `db/init.sql` runs on first boot (mounted as `/docker-entrypoint-initdb.d/`)
- Schema matches plan: `fhir_chunks` table with HNSW index on `embedding vector_cosine_ops`
- `.env.example` contains all env vars with safe defaults
- Dockerfile: multi-stage build, copies src/, installs deps, runs uvicorn

**Data generation note:**
Generate diabetic patient data using Synthea diabetes modules:
```bash
# Type 2 Diabetes patients (majority)
java -jar synthea.jar -m diabetes -p 50

# Type 1 Diabetes patients
java -jar synthea.jar -m type1_diabetes -p 20
```
Store output in `data/synthea/`. ~70 patients with diabetes-specific resources (HbA1c, Metformin, insulin, complications, care plans).

### Task 0.3: Vendor frontend assets

**Prompt for Codex:**
> Download Alpine.js 3.x (alpinejs.min.js) and Pico CSS 2.x (pico.min.css) into src/frontend/vendor/. Create placeholder index.html, app.js, style.css in src/frontend/.

**Files to create:**
```
src/frontend/vendor/alpine.min.js
src/frontend/vendor/pico.min.css
src/frontend/index.html     (minimal placeholder)
src/frontend/app.js         (empty function stub)
src/frontend/style.css      (empty)
```

**Acceptance criteria:**
- No CDN references in index.html — vendor files loaded from `/vendor/`
- index.html has proper HTML5 structure

---

## Phase 1 — Data & Ingestion

### Task 1.1: FHIR Bundle parser

**Prompt for Codex:**
> Create src/ingestion/fhir_parser.py. It should parse FHIR R4 Bundle JSON files and extract individual resources. Use the fhir.resources library for validation.

**Function signatures:**
```python
# src/ingestion/fhir_parser.py
from fhir.resources.bundle import Bundle
from dataclasses import dataclass

@dataclass
class ParsedResource:
    resource_id: str           # e.g., "Patient/abc-123"
    resource_type: str         # e.g., "Patient"
    resource_json: dict        # raw FHIR JSON
    patient_ref: str | None    # resolved patient reference
    references: list[str]      # other resource IDs this references

SUPPORTED_TYPES = [
    "Patient", "Condition", "Observation", "MedicationRequest",
    "Encounter", "AllergyIntolerance", "Procedure", "DiagnosticReport",
    "Immunization", "CarePlan",
]

def parse_bundle(bundle_path: Path) -> list[ParsedResource]:
    """Parse a FHIR Bundle JSON file, return individual resources."""
    ...

def parse_all_bundles(data_dir: Path) -> list[ParsedResource]:
    """Parse all .json files in a directory."""
    ...

def resolve_patient_ref(resource: dict, resource_type: str) -> str | None:
    """Extract patient reference from a resource. Handles subject, patient fields."""
    ...

def extract_references(resource: dict) -> list[str]:
    """Walk resource JSON and collect all Reference values."""
    ...
```

**Acceptance criteria:**
- Parses Synthea-generated Bundle JSON without errors
- Filters to SUPPORTED_TYPES only
- Correctly resolves patient references for each resource type
- Extracts FHIR references from nested structures
- Skips invalid/unparseable resources with a warning log

**Test file:** `tests/test_fhir_parser.py`
- Test with a minimal hand-crafted Bundle JSON (2-3 resources)
- Test reference extraction from nested objects
- Test patient_ref resolution for Condition, Observation, MedicationRequest

### Task 1.2: FHIR-aware text renderer

**Prompt for Codex:**
> Create src/ingestion/text_renderer.py. It converts a FHIR resource JSON into a human-readable text representation suitable for embedding. Each resource type has its own rendering logic. Output should be a natural language paragraph, not raw JSON.

**Function signatures:**
```python
# src/ingestion/text_renderer.py

def render_resource_text(resource_json: dict, resource_type: str) -> str:
    """Convert a FHIR resource to human-readable text for embedding."""
    ...

def render_patient(resource: dict) -> str: ...
def render_condition(resource: dict) -> str: ...
def render_observation(resource: dict) -> str: ...
def render_medication_request(resource: dict) -> str: ...
def render_encounter(resource: dict) -> str: ...
def render_allergy_intolerance(resource: dict) -> str: ...
def render_procedure(resource: dict) -> str: ...
def render_diagnostic_report(resource: dict) -> str: ...
```

**Example outputs for diabetes resources:**
```
Condition: Diabetes mellitus type 2 (SNOMED: 44054006).
Status: active. Onset: 2019-03-15.
Patient: Patient/abc-123.

Observation: Hemoglobin A1c (LOINC: 4548-4).
Value: 7.2 %. Date: 2024-06-15.
Patient: Patient/abc-123.

MedicationRequest: Metformin 500 MG (RxNorm: 860975).
Status: active. Authored: 2019-04-01.
Patient: Patient/abc-123.

CarePlan: Diabetes self-management plan (SNOMED: 698360004).
Status: active. Period: 2019-04-01 to ongoing.
Activities: Diet/exercise counseling, glucose monitoring, medication review.
Patient: Patient/abc-123.
```

**Acceptance criteria:**
- Each supported resource type has a dedicated renderer
- Extracts: display names, codes (SNOMED/LOINC/RxNorm), dates, status
- Falls back to generic key-value rendering for unknown resource types
- Never outputs raw JSON — always human-readable prose

**Test file:** `tests/test_text_renderer.py`

### Task 1.3: FHIR-aware chunker

**Prompt for Codex:**
> Create src/ingestion/chunker.py. It takes ParsedResource objects and produces FHIRChunk objects with structured metadata. One resource = one chunk.

**Function signatures:**
```python
# src/ingestion/chunker.py
from dataclasses import dataclass
from datetime import datetime

@dataclass
class FHIRChunk:
    resource_id: str
    resource_type: str
    patient_ref: str
    resource_date: datetime | None
    codes: list[dict]           # [{"system": "...", "code": "...", "display": "..."}]
    references: list[str]
    text_content: str           # from text_renderer
    # embedding added later by embedder

def chunk_resource(parsed: ParsedResource) -> FHIRChunk:
    """Convert a ParsedResource into a FHIRChunk with structured metadata."""
    ...

def extract_date(resource_json: dict, resource_type: str) -> datetime | None:
    """Extract the most relevant date from a resource.
    Priority: effectiveDateTime > onsetDateTime > recordedDate > authoredOn > period.start
    """
    ...

def extract_codes(resource_json: dict) -> list[dict]:
    """Extract all coded values (SNOMED, LOINC, RxNorm) from a resource."""
    ...
```

**Acceptance criteria:**
- One chunk per resource, never splits or merges
- Extracts resource-type-specific dates correctly
- Extracts codes from `code.coding`, `medicationCodeableConcept.coding`, `valueCodeableConcept.coding` etc.
- text_content comes from text_renderer

**Test file:** `tests/test_chunker.py`

### Task 1.4: Embedding service

**Prompt for Codex:**
> Create src/ingestion/embedder.py. Wraps sentence-transformers to embed text chunks. Returns 384-dim vectors.

**Function signatures:**
```python
# src/ingestion/embedder.py

class Embedder:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of 384-dim vectors."""
        ...

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query text."""
        ...
```

**Acceptance criteria:**
- Loads model lazily on first call
- Batch embedding for ingestion efficiency
- Returns 384-dim float vectors
- Query embedding uses same model (no prefix difference for MiniLM)

**Test file:** `tests/test_embedder.py` (mock the model for unit tests)

### Task 1.5: Ingestion pipeline CLI

**Prompt for Codex:**
> Create src/ingestion/ingest.py. CLI entrypoint that orchestrates: parse bundles -> chunk -> embed -> store in pgvector. Should be runnable as `python -m src.ingestion.ingest --data-dir data/synthea/`.

**Function signatures:**
```python
# src/ingestion/ingest.py
import asyncio

async def ingest_bundles(data_dir: Path, db_url: str) -> dict:
    """Main ingestion pipeline. Returns stats dict."""
    # 1. parse_all_bundles(data_dir) -> list[ParsedResource]
    # 2. chunk each ParsedResource -> list[FHIRChunk]
    # 3. embed all chunks in batches
    # 4. insert into pgvector (batch insert with ON CONFLICT DO NOTHING)
    # Returns: {"bundles": N, "resources": N, "chunks_stored": N}
    ...

async def store_chunks(pool, chunks: list[FHIRChunk], embeddings: list[list[float]]) -> int:
    """Batch insert chunks into fhir_chunks table. Returns count stored."""
    ...
```

**Acceptance criteria:**
- Processes all .json files in the data directory
- Batch embeds (32 texts per batch)
- Uses `ON CONFLICT (resource_id) DO NOTHING` for idempotent re-runs
- Prints progress and final stats
- Handles empty directories gracefully

---

## Phase 2 — Retrieval

### Task 2.1: Hybrid search

**Prompt for Codex:**
> Create src/retrieval/hybrid_search.py. Combines pgvector similarity search with structured SQL filters on resource_type, patient_ref, and date range.

**Function signatures:**
```python
# src/retrieval/hybrid_search.py
from dataclasses import dataclass

@dataclass
class SearchResult:
    resource_id: str
    resource_type: str
    patient_ref: str
    resource_date: datetime | None
    codes: list[dict]
    references: list[str]
    text_content: str
    similarity: float

async def hybrid_search(
    pool,
    query_embedding: list[float],
    patient_ref: str | None = None,
    resource_types: list[str] | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    top_k: int = 10,
) -> list[SearchResult]:
    """Vector similarity search with optional structured filters."""
    ...
```

**Acceptance criteria:**
- All filters are optional (pass None to skip)
- SQL uses parameterized queries (no string interpolation)
- Returns results sorted by descending similarity
- Works correctly with zero results

**Test file:** `tests/test_hybrid_search.py`

### Task 2.2: Cross-resource reference resolver

**Prompt for Codex:**
> Create src/retrieval/reference_resolver.py. For a set of search results, follow FHIR references to pull related resources from the database. Max 2 hops.

**Function signatures:**
```python
# src/retrieval/reference_resolver.py

async def resolve_references(
    pool,
    results: list[SearchResult],
    max_hops: int = 2,
) -> list[SearchResult]:
    """Follow FHIR references from search results. Returns additional resources.
    Does not duplicate resources already in results.
    """
    ...
```

**Acceptance criteria:**
- Follows `references` field from each SearchResult
- Fetches referenced resources by resource_id (direct DB lookup, not vector search)
- Caps at max_hops to prevent explosion
- Deduplicates — never returns a resource already in the input results
- Returns supplementary resources with similarity=0.0 (they're context, not matches)

**Test file:** `tests/test_reference_resolver.py`

### Task 2.3: Context builder

**Prompt for Codex:**
> Create src/retrieval/context_builder.py. Assembles retrieved + resolved resources into a structured text block for the LLM prompt.

**Function signatures:**
```python
# src/retrieval/context_builder.py

def build_context(
    primary_results: list[SearchResult],
    supplementary_results: list[SearchResult],
) -> str:
    """Build structured context string for LLM prompt.
    Groups by resource type. Includes resource IDs for citation.
    Primary results first, then supplementary (marked as supporting context).
    """
    ...
```

**Expected output format (diabetes example):**
```
=== Retrieved FHIR Resources (ranked by relevance) ===

[MedicationRequest/abc-456] (similarity: 0.87)
Metformin 500 MG oral tablet (RxNorm: 860975), active. Authored: 2024-03-15.
Patient: Patient/abc-123.

[Condition/def-789] (similarity: 0.82)
Diabetes mellitus type 2 (SNOMED: 44054006). Status: active. Onset: 2019-03-15.
Patient: Patient/abc-123.

[Observation/ghi-012] (similarity: 0.78)
Hemoglobin A1c (LOINC: 4548-4). Value: 7.2 %. Date: 2024-06-15.
Patient: Patient/abc-123.

=== Supporting Context (referenced resources) ===

[Patient/abc-123]
John Smith, male, born 1965-04-12.

[CarePlan/jkl-345]
Diabetes self-management plan (SNOMED: 698360004). Status: active.
Activities: Diet/exercise counseling, glucose monitoring.
```

**Acceptance criteria:**
- Clear separation between primary and supplementary results
- Each resource prefixed with its resource_id in brackets (for citation)
- Similarity score shown for primary results
- Readable without domain knowledge

---

## Phase 3 — Generation

### Task 3.1: Prompt template

**Prompt for Codex:**
> Create src/generation/prompts/clinical_qa.jinja2. System prompt for clinical Q&A with strict grounding rules.

**Template content:**
```jinja2
You are a clinical data assistant. Answer questions using ONLY the FHIR resources provided below.

Rules:
1. Base your answer exclusively on the provided FHIR context.
2. Cite specific resource IDs using [ResourceType/id] format (e.g., [MedicationRequest/abc-456]).
3. If the provided context does not contain enough information to answer, say: "Insufficient data in the available FHIR resources to answer this question."
4. Never fabricate clinical information, medications, diagnoses, or dates.
5. When multiple resources are relevant, synthesize them into a coherent answer.
6. Include relevant dates and coded values when available.

{{ context }}

Question: {{ question }}
```

**Acceptance criteria:**
- Template renders with `context` and `question` variables
- Rules are specific and actionable

### Task 3.2: LLM client abstraction

**Prompt for Codex:**
> Create src/generation/llm_client.py. Abstracts Claude API and Ollama behind a common interface.

**Function signatures:**
```python
# src/generation/llm_client.py
from dataclasses import dataclass

@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int

class LLMClient:
    def __init__(self, provider: str, api_key: str | None = None, ollama_url: str | None = None):
        ...

    async def generate(self, system_prompt: str, user_message: str) -> LLMResponse:
        """Send prompt to LLM and return response."""
        ...
```

**Acceptance criteria:**
- Claude path uses anthropic SDK async client
- Ollama path uses httpx to call `/api/generate`
- Both return LLMResponse with token counts
- Claude uses `claude-sonnet-4-6` model

**Test file:** `tests/test_llm_client.py` (mock both providers)

### Task 3.3: Citation mapper

**Prompt for Codex:**
> Create src/generation/citation_mapper.py. Parses LLM response text to extract cited resource IDs and matches them against actual retrieved resources.

**Function signatures:**
```python
# src/generation/citation_mapper.py
import re
from dataclasses import dataclass

@dataclass
class Citation:
    resource_id: str
    resource_type: str
    text_snippet: str
    date: str | None

@dataclass
class GroundedAnswer:
    answer: str
    citations: list[Citation]
    confidence: str       # "grounded" | "partially_grounded" | "ungrounded"
    query: str

def map_citations(
    llm_response: str,
    query: str,
    available_resources: list[SearchResult],
) -> GroundedAnswer:
    """Parse LLM response for [ResourceType/id] citations.
    Match against available_resources. Classify confidence.
    """
    ...
```

**Confidence classification:**
- `grounded`: all cited resource IDs exist in available_resources
- `partially_grounded`: some cited IDs exist, some don't
- `ungrounded`: no valid citations found, or LLM fabricated resource IDs

**Acceptance criteria:**
- Regex extracts `[ResourceType/id]` patterns from response text
- Matches against actual resources (case-insensitive on type)
- Confidence reflects citation validity
- Citations include text_snippet from the matched resource

**Test file:** `tests/test_citation_mapper.py`

---

## Phase 4 — API & Frontend

### Task 4.1: FastAPI application

**Prompt for Codex:**
> Create src/api/main.py with FastAPI app factory, lifespan (DB pool init/cleanup), and static file mount. Create src/api/schemas.py with pydantic request/response models. Create src/api/routes.py with all endpoints.

**Endpoints:**

```python
# src/api/schemas.py
from pydantic import BaseModel

class QueryRequest(BaseModel):
    question: str
    patient_ref: str | None = None
    resource_types: list[str] | None = None

class CitationResponse(BaseModel):
    resource_id: str
    resource_type: str
    text_snippet: str
    date: str | None

class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]
    confidence: str
    query: str

class PatientSummary(BaseModel):
    id: str
    name: str
    birth_date: str | None

class HealthResponse(BaseModel):
    status: str
    db_connected: bool
    chunks_count: int
```

**Acceptance criteria:**
- `POST /api/query` orchestrates: embed query -> hybrid search -> resolve refs -> build context -> LLM generate -> map citations
- `GET /api/patients` returns distinct patients from fhir_chunks
- `GET /api/resources/{resource_id}` returns single resource text + metadata
- `GET /health` checks DB connection and returns chunk count
- Static files mounted at `/` from `src/frontend/`
- Proper error responses (422 for validation, 500 for internal errors)

**Test file:** `tests/test_api.py` (use FastAPI TestClient)

### Task 4.2: Frontend implementation

**Prompt for Codex:**
> Implement src/frontend/index.html, app.js, and style.css. Alpine.js app that calls the JSON API. Use vendored Alpine.js and Pico CSS from /vendor/.

**Acceptance criteria:**
- Patient dropdown populated from `GET /api/patients`
- Question input with Enter-to-submit
- Loading state while API call is in flight
- Answer displayed with confidence indicator
- Citations as expandable details sections
- Responsive layout (works on mobile)
- No CDN references — all assets from vendor/

---

## Phase 5 — Evaluation & Polish

### Task 5.1: Evaluation dataset (Diabetes-focused)

**Prompt for Codex:**
> Create eval/questions.json with 50 diabetes-focused question/answer pairs sourced from
> `docs/diabetics-validation-questions.md`. Each has: id, question, expected_resource_types,
> expected_codes, expected_answer_contains, category, and diabetes_type.
> Cover both Type 1 and Type 2 Diabetes across all 10 categories.

**Schema:**
```json
[
  {
    "id": "DM-013",
    "question": "What diabetes medications is this patient currently taking?",
    "patient_ref": "Patient/abc-123",
    "expected_resource_types": ["MedicationRequest"],
    "expected_codes": [{"system": "RxNorm", "code": "860975", "display": "Metformin 500 MG"}],
    "expected_answer_contains": ["Metformin", "active"],
    "category": "medications",
    "diabetes_type": "both"
  }
]
```

**Categories (10):** `diagnosis`, `hba1c_monitoring`, `medications`, `complications`, `vitals_labs`, `care_plan`, `cross_resource`, `temporal`, `preventive`, `negative`

**Reference:** See `docs/diabetics-validation-questions.md` for all 50 questions with expected codes and answer keywords.

### Task 5.2: Evaluation harness

**Prompt for Codex:**
> Create eval/evaluate.py. Runs each question through the full pipeline and measures retrieval recall, answer faithfulness, and citation accuracy.

**Metrics:**
```python
@dataclass
class EvalResult:
    question: str
    retrieval_recall: float     # % of expected resource types retrieved
    citation_accuracy: float    # % of citations that match real resources
    answer_contains: float      # % of expected phrases found in answer
    confidence: str
    latency_ms: int
```

**Acceptance criteria:**
- Runs all questions, prints per-question results + aggregated summary
- Outputs results as both terminal table and JSON file
- Runnable as `python -m eval.evaluate`

### Task 5.3: README

**Prompt for Codex:**
> Create README.md with: project description, Mermaid architecture diagram, quickstart (docker compose up), example queries, design decisions, evaluation results placeholder, and limitations.

---

## Task Dependency Graph

```mermaid
graph LR
    T01[0.1 Scaffolding] --> T02[0.2 Docker]
    T01 --> T03[0.3 Vendor Assets]
    T01 --> T11[1.1 FHIR Parser]
    T11 --> T12[1.2 Text Renderer]
    T11 --> T13[1.3 Chunker]
    T12 --> T13
    T01 --> T14[1.4 Embedder]
    T13 --> T15[1.5 Ingest CLI]
    T14 --> T15
    T02 --> T15
    T14 --> T21[2.1 Hybrid Search]
    T15 --> T21
    T21 --> T22[2.2 Ref Resolver]
    T21 --> T23[2.3 Context Builder]
    T22 --> T23
    T23 --> T31[3.1 Prompt Template]
    T23 --> T32[3.2 LLM Client]
    T31 --> T33[3.3 Citation Mapper]
    T32 --> T33
    T33 --> T41[4.1 FastAPI App]
    T03 --> T42[4.2 Frontend]
    T41 --> T42
    T41 --> T51[5.1 Eval Dataset]
    T51 --> T52[5.2 Eval Harness]
    T42 --> T53[5.3 README]
    T52 --> T53
```

**Parallelizable groups:**
- Task 0.2 + 0.3 (after 0.1)
- Task 1.1 + 1.4 (after 0.1)
- Task 1.2 + 1.3 can overlap if interfaces are agreed
- Task 2.1 + 3.1 + 3.2 (after Phase 1 complete)
- Task 5.1 + 5.3 (after 4.1)

---

## Codex Session Strategy

### Recommended session breakdown

| Session | Tasks | Est. Codex time | Notes |
|---|---|---|---|
| 1 | 0.1, 0.2, 0.3 | 10-15 min | Scaffolding, can be one prompt |
| 2 | 1.1, 1.2 | 15-20 min | Parser + renderer, test with sample Bundle |
| 3 | 1.3, 1.4 | 10-15 min | Chunker + embedder |
| 4 | 1.5 | 10 min | Wire up ingestion pipeline |
| 5 | 2.1, 2.2, 2.3 | 15-20 min | Full retrieval layer |
| 6 | 3.1, 3.2, 3.3 | 15-20 min | Generation layer |
| 7 | 4.1 | 15 min | FastAPI wiring |
| 8 | 4.2 | 10 min | Frontend |
| 9 | 5.1, 5.2, 5.3 | 15-20 min | Eval + README |

**Total: ~9 Codex sessions, ~2-3 hours of Codex time**

### Tips for each session

1. **Start each session** by referencing the existing files — Codex needs to see imports and types from prior tasks
2. **Always include test files** in the same prompt — Codex writes better code when tests constrain it
3. **Pin the function signatures** from this doc — don't let Codex invent its own interfaces
4. **Run tests after each session** before moving to the next task
5. **Synthea data** needs to exist before Task 1.5 — generate it manually or in Task 0.1

### Pre-flight checklist

- [ ] Synthea installed and diabetic patients generated in `data/synthea/`:
  - `java -jar synthea.jar -m diabetes -p 50` (Type 2)
  - `java -jar synthea.jar -m type1_diabetes -p 20` (Type 1)
- [ ] Docker and Docker Compose v2 installed
- [ ] Python 3.11+ available
- [ ] `ANTHROPIC_API_KEY` set in `.env`
- [ ] pgvector-compatible Postgres running (or use Docker)
