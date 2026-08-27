# Diabetes FHIR RAG

Diabetes FHIR RAG is a clinical data assistant for grounded question answering over patient records. It ingests Synthea FHIR R4 Bundles, preserves resource boundaries and references, retrieves relevant resources by fusing vector and full-text search over pgvector, and returns answers with resource-level citations.

The evaluation set and example queries are diabetes-focused, but retrieval and generation are condition-agnostic: a generated Synthea cohort contains whatever conditions Synthea produced, and the system answers over those records as readily as over diabetes ones.

## Architecture

```mermaid
graph TD
    subgraph Data["Data Layer"]
        SY[Synthea Generator] --> FP[FHIR Resource Parser]
    end

    subgraph Ingestion["Ingestion Pipeline"]
        FP --> CH[FHIR-Aware Chunker]
        CH --> EM[Embedding Service<br/>all-MiniLM-L6-v2]
        EM --> PG[(pgvector<br/>fhir_chunks)]
    end

    subgraph Retrieval["Retrieval Layer"]
        HS[Hybrid Search<br/>vector + structured filters]
        CRL[Cross-Resource Linker<br/>FHIR reference resolver]
        CB[Context Builder<br/>Jinja2 templates]
        HS --> CRL --> CB
    end

    subgraph Generation["Generation Layer"]
        LLM[LLM Client<br/>Claude API / Ollama]
        CM[Citation Mapper]
        CB --> LLM --> CM
    end

    subgraph API["API + Interface"]
        FA[FastAPI<br/>JSON API]
        FE[Frontend<br/>Alpine.js + Pico CSS]
        DC[Docker Compose]
        CM --> FA --> FE
    end

    PG --> HS
```

## Module Map

```mermaid
graph LR
    subgraph ingestion["src/ingestion/"]
        FP2[fhir_parser.py<br/>parse_all_bundles]
        TR[text_renderer.py<br/>render_resource_text]
        CH2[chunker.py<br/>chunk_resource<br/>extract_date / extract_codes]
        EM2[embedder.py<br/>Embedder]
        ING[ingest.py<br/>ingest_bundles CLI]
        FP2 --> TR --> CH2 --> EM2 --> ING
    end

    subgraph retrieval["src/retrieval/"]
        HS2[hybrid_search.py<br/>hybrid_search]
        RR[reference_resolver.py<br/>resolve_references<br/>2-hop max]
        CTX[context_builder.py<br/>build_context<br/>group by type]
        HS2 --> RR --> CTX
    end

    subgraph generation["src/generation/"]
        TMPL[prompts/clinical_qa.jinja2]
        LLC[llm_client.py<br/>LLMClient<br/>Claude / Ollama]
        CM2[citation_mapper.py<br/>map_citations<br/>grounded / partial / none]
        TMPL --> LLC --> CM2
    end

    subgraph api["src/api/"]
        SCH[schemas.py<br/>QueryRequest / Response]
        RT[routes.py<br/>POST /api/query<br/>GET /api/patients<br/>GET /api/resources/:id<br/>GET /health]
        MAIN[main.py<br/>FastAPI app factory]
        SCH --> RT --> MAIN
    end

    subgraph frontend["src/frontend/"]
        HTML[index.html]
        JS[app.js — Alpine.js]
        CSS[style.css + Pico CSS]
    end

    ING -->|writes| DB[(PostgreSQL<br/>pgvector)]
    DB -->|reads| HS2
    CTX --> TMPL
    CM2 --> RT
    MAIN --> HTML
```

## How It Works

### Ingestion Pipeline

```mermaid
flowchart LR
    A[Synthea FHIR<br/>Bundles] --> B[Bundle Parser<br/>fhir.resources]
    B --> C{Supported<br/>Resource?}
    C -->|Yes| D[Text Renderer<br/>Human-readable]
    C -->|No| X[Skip]
    D --> E[FHIR Chunker<br/>1 resource = 1 chunk]
    E --> F[Extract Metadata<br/>dates, codes, refs]
    F --> G[Embedder<br/>all-MiniLM-L6-v2 by default]
    G --> H[(pgvector<br/>384-dim HNSW + GIN tsvector)]

    style A fill:#f4f6ef,stroke:#d7dfd5
    style H fill:#dff3e5,stroke:#176536
    style X fill:#ffe0da,stroke:#9d301d
```

### Query Pipeline

```mermaid
flowchart TD
    Q[User Question] --> E[Embed Query<br/>all-MiniLM-L6-v2]
    E --> S[Hybrid Search<br/>vector + full-text, RRF fused]
    S --> R[Reference Resolver<br/>2-hop max]
    R --> C[Context Builder<br/>group by type]
    C --> P[Render Prompt<br/>clinical_qa.jinja2]
    P --> L[LLM Generate<br/>Claude / Gemini / Vertex / Ollama]
    L --> M[Citation Mapper<br/>extract ResourceType/id]
    M --> A{All citations<br/>match?}
    A -->|All| G[Grounded]
    A -->|Some| PG[Partially Grounded]
    A -->|None| U[Ungrounded]

    G --> RES[JSON Response<br/>answer + citations]
    PG --> RES
    U --> RES

    style Q fill:#f4f6ef,stroke:#d7dfd5
    style G fill:#dff3e5,stroke:#176536
    style PG fill:#fff0c7,stroke:#805900
    style U fill:#ffe0da,stroke:#9d301d
    style RES fill:#dff3e5,stroke:#176536
```

### API Request Flow

```mermaid
sequenceDiagram
    participant UI as Frontend<br/>(Alpine.js)
    participant API as FastAPI<br/>routes.py
    participant EMB as Embedder<br/>all-MiniLM-L6-v2 by default
    participant PG as pgvector<br/>fhir_chunks
    participant REF as reference_resolver
    participant CTX as context_builder
    participant TMPL as clinical_qa.jinja2
    participant LLM as LLMClient<br/>Claude / Ollama
    participant CM as citation_mapper

    UI->>API: POST /api/query {question, patient_ref}
    API->>EMB: embed_query(question) → 384-dim vector
    EMB-->>API: query_embedding
    API->>PG: hybrid_search(embedding, patient_ref, resource_types, top_k)
    PG-->>API: primary[SearchResult…]
    API->>REF: resolve_references(primary, max_hops=2)
    REF->>PG: fetch linked resource_ids (up to 2 hops)
    PG-->>REF: supplementary rows
    REF-->>API: supplementary[SearchResult…]
    API->>CTX: build_context(primary, supplementary)
    CTX-->>API: grouped text block (ResourceType headers + [id] labels)
    API->>TMPL: render clinical_qa.jinja2(context, question)
    TMPL-->>API: system_prompt
    API->>LLM: generate(system_prompt, question)
    LLM-->>API: LLMResponse{content, model, tokens}
    API->>CM: map_citations(content, question, primary+supplementary)
    CM-->>API: GroundedAnswer{answer, citations, confidence}
    API-->>UI: QueryResponse{answer, citations[], confidence, query}
```

### Database Schema

```mermaid
erDiagram
    fhir_chunks {
        uuid        id             PK
        text        resource_id    UK "FHIR ResourceType/uuid"
        text        resource_type  "Patient, Observation, etc."
        text        patient_ref    "Patient/uuid FK-like"
        timestamptz resource_date  "effectiveDateTime or best match"
        jsonb       codes          "SNOMED/LOINC/RxNorm coding[]"
        text[]      references     "outbound FHIR refs"
        text        text_content   "human-readable render"
        vector_384  embedding      "HNSW index (cosine)"
        tsvector    text_search    "generated from text_content, GIN index"
        timestamptz created_at
    }
```

### Evaluation Flow

```mermaid
flowchart LR
    QS[50 Diabetes<br/>Questions] --> LOOP[Run Each Through<br/>Query Pipeline]
    LOOP --> MET[Measure Metrics]
    MET --> RR[Retrieval Recall<br/>expected types found?]
    MET --> CA[Citation Accuracy<br/>cited IDs valid?]
    MET --> AC[Answer Contains<br/>expected phrases?]
    MET --> LAT[Latency ms]
    RR --> OUT[Terminal Table<br/>+ JSON Report]
    CA --> OUT
    AC --> OUT
    LAT --> OUT

    style QS fill:#f4f6ef,stroke:#d7dfd5
    style OUT fill:#dff3e5,stroke:#176536
```

## Quickstart

1. Copy `.env.example` to `.env` and set the key for your provider: `ANTHROPIC_API_KEY` (`LLM_PROVIDER=claude`), `GEMINI_API_KEY` (`gemini`), `VERTEX_API_KEY` (`vertex`), or select `LLM_PROVIDER=ollama` for a local model.
2. Install Synthea and generate FHIR data. Synthea requires Java 17 or newer:

   ```bash
   curl -L https://github.com/synthetichealth/synthea/releases/download/master-branch-latest/synthea-with-dependencies.jar -o synthea-with-dependencies.jar
   mkdir -p data/synthea
   java -jar synthea-with-dependencies.jar -p 70 --exporter.fhir.export=true
   cp output/fhir/*.json data/synthea/
   ```

   Do not use `-m diabetes` or `-m type1_diabetes` for this application: `-m` filters Synthea's loaded modules and can omit the observations, conditions, and medication records this RAG app needs. Normal generation produces a broader synthetic record set; diabetes-specific cohorts require a dedicated Synthea module/configuration rather than `-m` alone.

   If you already downloaded the JAR, run the commands from the directory containing `synthea-with-dependencies.jar`. The generated FHIR Bundles must be copied into `data/synthea/` before ingestion.
3. Start the stack:

   ```bash
   docker compose up
   ```

4. In another shell, ingest the data:

   ```bash
   docker compose exec app python -m src.ingestion.ingest --data-dir data/synthea/
   ```

Open `http://localhost:8000` for the UI or `http://localhost:8000/docs` for the API documentation.

`EMBEDDING_BACKEND` defaults to `transformer` (`all-MiniLM-L6-v2`, CPU). The image installs PyTorch from the CPU wheel index and bakes the model weights in, which costs roughly 2 GB of image size and no GPU. Set `EMBEDDING_BACKEND=hash` only for dependency-free smoke tests: the hash backend matches tokens literally, retrieves poorly, and is not suitable for evaluation.

Both backends produce 384-dimensional vectors, so switching does not require a schema change — but it **does** require re-running ingestion, which upserts embeddings in place. Confirm the vectors match the configured backend afterwards; hash vectors are sparse, transformer vectors are dense:

```bash
docker compose exec -T db psql -U fhir -d fhir_rag -c \
  "SELECT round(avg(cardinality(array_positions(embedding::real[], 0)))) AS avg_zeros
   FROM (SELECT embedding FROM fhir_chunks LIMIT 500) s"
```

## Example Queries

- "What is this patient's most recent HbA1c result?" should answer from `Observation` resources and cite the HbA1c record.
- "What diabetes medications is this patient currently taking?" should identify active `MedicationRequest` resources and cite each medication used.
- "When was this patient's last diabetic eye examination?" should retrieve the relevant `Procedure` and report its recorded date.
- "What insulin pump model is this patient using?" should say "insufficient data" when the FHIR context does not contain a device model.

Retrieval is not diabetes-specific. Against a pediatric atopic patient in the same corpus, the following are answered with citations:

- "Which allergies are documented, and what reaction did each cause?" returns each `AllergyIntolerance` with its manifestations and severity.
- "What was his BMI percentile at the most recent well-child visit?" joins the BMI `Observation` to the `Encounter` typed as a well-child visit.
- "Did any positive IgE result correspond to an allergy recorded on his list?" cross-references `Observation` results against `AllergyIntolerance` entries.

Negative controls behave the same way: HbA1c, spirometry, and hospitalization questions all return "insufficient data" for a patient who has none of those records.

## Design Decisions

- **HNSW over IVFFlat:** HNSW is insert-friendly and does not require list tuning or retraining after bulk ingestion. It is appropriate for the variable-sized development dataset.
- **FHIR-aware chunking:** one resource is one chunk, with resource type, patient reference, dates, codes, and outbound references retained as metadata. This keeps citations precise and prevents clinically unrelated resources from being merged.
- **Hybrid search:** a vector arm and a Postgres full-text arm each retrieve `TOP_K * 5` candidates and are combined with weighted Reciprocal Rank Fusion (k=60, lexical weight 0.5); SQL filters apply patient, resource-type, and date constraints to both. The lexical arm exists because pure vector search missed questions whose wording named a resource type outright — "immunization schedule" ranked the patient's `Immunization` resources at #33. Its tsquery is OR-joined: the AND semantics of `websearch_to_tsquery` require every question term in one short chunk and matched nothing. The half weight keeps an OR match from outvoting semantic similarity.
- **`NOT MATERIALIZED` filters:** the shared `filtered` CTE is referenced by both arms and the final join. PostgreSQL materialises a CTE referenced more than once, which turned every query into a sequential scan and put the HNSW and GIN indexes out of reach.
- **Semantic embeddings by default:** `all-MiniLM-L6-v2` on CPU. The earlier hash backend matched tokens literally and could not connect "allergies" to `AllergyIntolerance`. The hash backend remains available for dependency-free runs but is not recommended for real retrieval.
- **Bounded thinking budget:** Gemini 2.5 charges internal reasoning against `maxOutputTokens`, which truncated answers mid-citation. Requests set `thinkingBudget` explicitly so the visible answer is always allocated room.
- **Strict grounding:** the prompt requires citations in `[ResourceType/id]` format and an "insufficient data" response when retrieved context cannot support an answer.

## Evaluation

The 50-question diabetes evaluation set is in `eval/questions.json` and covers diagnosis, HbA1c monitoring, medications, complications, vitals/labs, care plans, cross-resource reasoning, temporal trends, preventive screening, and negative/boundary questions.

Run it against a populated stack with:

```bash
python -m eval.evaluate
```

The harness prints per-question and aggregate metrics for retrieval recall, citation accuracy, answer-keyword coverage, confidence, and latency. JSON output is written to `eval/results/evaluation_results.json`. Baseline results are intentionally left as a placeholder until a representative Synthea dataset and configured LLM are available.

## Limitations and V2 Roadmap

The v1 system is limited to indexed FHIR resources and cannot infer facts absent from the data. Synthea does not provide every clinical workflow, including continuous glucose monitor history and insulin pump model details. It also does not replace clinical judgment.

**Near-duplicate chunks compete for retrieval slots.** Synthea emits one `Medication review due` Condition per visit. These are near-identical, so they embed to nearly the same vector and once occupied every `Condition` slot, making a generic "what are the active problems?" question return only the administrative entry. The lexical arm now surfaces the clinical conditions and this answers correctly, but nothing prevents the same crowding on another corpus. Diversity-aware retrieval — MMR re-ranking, or collapsing candidates by `(resource_type, code)` before applying `top_k` — remains the robust fix and is not implemented. See `docs/notes/fhir-rag-debugging.md`.

**No authentication or authorization.** Every endpoint trusts the caller-supplied `patient_ref`, so anyone who can reach the API can read any patient in the corpus. That is acceptable for a local demo over synthetic data and is not acceptable for real records; access control is v2 work.

Planned v2 work includes diversity-aware retrieval, HAPI FHIR and SMART on FHIR integration, graph-based reference reasoning, cross-encoder reranking, temporal query decomposition, cohort analytics, caching, audit logging, access control, and production observability.

`docs/notes/fhir-rag-debugging.md` records each defect found while bringing this system up, with the evidence used to identify it and the fix applied.
