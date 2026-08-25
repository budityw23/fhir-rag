# Diabetes FHIR RAG

Diabetes FHIR RAG is a clinical data assistant for grounded question answering over Type 1 and Type 2 diabetes records. It ingests Synthea FHIR R4 Bundles, preserves resource boundaries and references, retrieves relevant resources with pgvector plus structured filters, and returns answers with resource-level citations.

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

## Quickstart

1. Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`, or select `LLM_PROVIDER=ollama`.
2. Generate diabetic FHIR data if needed:

   ```bash
   java -jar synthea.jar -m diabetes -p 50
   java -jar synthea.jar -m type1_diabetes -p 20
   ```

   Place the generated Bundles in `data/synthea/`.
3. Start the stack:

   ```bash
   docker compose up
   ```

4. In another shell, ingest the data:

   ```bash
   docker compose exec app python -m src.ingestion.ingest --data-dir data/synthea/
   ```

Open `http://localhost:8000` for the UI or `http://localhost:8000/docs` for the API documentation.

## Example Queries

- "What is this patient's most recent HbA1c result?" should answer from `Observation` resources and cite the HbA1c record.
- "What diabetes medications is this patient currently taking?" should identify active `MedicationRequest` resources and cite each medication used.
- "When was this patient's last diabetic eye examination?" should retrieve the relevant `Procedure` and report its recorded date.
- "What insulin pump model is this patient using?" should say "insufficient data" when the FHIR context does not contain a device model.

## Design Decisions

- **HNSW over IVFFlat:** HNSW is insert-friendly and does not require list tuning or retraining after bulk ingestion. It is appropriate for the variable-sized development dataset.
- **FHIR-aware chunking:** one resource is one chunk, with resource type, patient reference, dates, codes, and outbound references retained as metadata. This keeps citations precise and prevents clinically unrelated resources from being merged.
- **Hybrid search:** vector similarity handles natural-language questions while SQL filters support exact patient, resource-type, and date constraints.
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

Planned v2 work includes HAPI FHIR and SMART on FHIR integration, graph-based reference reasoning, cross-encoder reranking, temporal query decomposition, cohort analytics, caching, audit logging, access control, and production observability.
