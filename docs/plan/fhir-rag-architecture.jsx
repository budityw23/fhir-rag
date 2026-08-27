import { useState } from "react";

const layers = [
  {
    id: "data",
    label: "Data Layer",
    color: "#1a5276",
    accent: "#2980b9",
    components: [
      {
        name: "Synthea Generator",
        desc: "Generate realistic FHIR R4 patient bundles — conditions, observations, medications, encounters. 50–100 patients gives you enough variety.",
        tech: "synthea, FHIR R4 JSON",
      },
      {
        name: "FHIR Resource Parser",
        desc: "Walk each Bundle, extract individual resources. Flatten nested references (e.g. Observation → Patient, MedicationRequest → Encounter).",
        tech: "fhir.resources (Python), pydantic",
      },
    ],
  },
  {
    id: "ingestion",
    label: "Ingestion Pipeline",
    color: "#6c3461",
    accent: "#a569bd",
    components: [
      {
        name: "FHIR-Aware Chunker",
        desc: "NOT naive text splitting. Each FHIR resource = 1 chunk, preserving resource boundaries. Attach structured metadata: resourceType, patient ref, date, code system.",
        tech: "custom Python",
        highlight: true,
      },
      {
        name: "Embedding Service",
        desc: "Convert each chunk to a vector. Use a medical-domain model for better clinical term matching, or a general-purpose one to keep it simple.",
        tech: "sentence-transformers or OpenAI embeddings",
      },
      {
        name: "Vector Store",
        desc: "Store embeddings + metadata. pgvector keeps it Postgres-native (you know Postgres). Metadata columns enable structured pre-filtering before semantic search.",
        tech: "pgvector / Qdrant",
      },
    ],
  },
  {
    id: "retrieval",
    label: "Retrieval Layer",
    color: "#1e6e3e",
    accent: "#27ae60",
    components: [
      {
        name: "Hybrid Search",
        desc: "Combine semantic similarity (vector) with structured FHIR filters — by resourceType, patient, date range, code. This is your differentiator vs generic RAG.",
        tech: "pgvector + SQL WHERE clauses",
        highlight: true,
      },
      {
        name: "Cross-Resource Linker",
        desc: "Follow FHIR references to pull related resources. Query about a Condition? Also retrieve linked Observations, MedicationRequests, relevant Encounters.",
        tech: "FHIR reference resolver",
        highlight: true,
      },
      {
        name: "Context Builder",
        desc: "Assemble retrieved FHIR resources into a structured prompt context with clear resource boundaries. Include provenance (resource ID, type, date) for citation.",
        tech: "Jinja2 templates",
      },
    ],
  },
  {
    id: "generation",
    label: "Generation Layer",
    color: "#7d5a00",
    accent: "#d4a017",
    components: [
      {
        name: "LLM + Grounded Prompt",
        desc: "System prompt instructs the model to answer ONLY from provided FHIR context, cite specific resource IDs, and flag when data is insufficient.",
        tech: "Claude API / Ollama (local)",
      },
      {
        name: "Citation Mapper",
        desc: "Parse the LLM response, match cited resource IDs back to actual FHIR resources. Return structured answer with linked evidence.",
        tech: "custom Python",
      },
    ],
  },
  {
    id: "api",
    label: "API + Interface",
    color: "#5d4037",
    accent: "#8d6e63",
    components: [
      {
        name: "FastAPI (JSON API)",
        desc: "Pure JSON endpoints — POST /api/query, GET /api/patients, GET /api/resources/{id}. Mounts frontend/ as static files. Clean separation: API returns data, frontend renders it.",
        tech: "FastAPI, Pydantic, StaticFiles",
      },
      {
        name: "Alpine.js + Pico CSS",
        desc: "Separate static frontend: index.html + app.js + style.css. Alpine.js fetches JSON from the API, handles state and rendering. Pico CSS styles semantic HTML automatically. Two CDN tags, ~60 lines of JS.",
        tech: "~17KB total, no node_modules, no build",
        highlight: true,
      },
      {
        name: "Docker Compose",
        desc: "One command to run everything: FastAPI + Postgres/pgvector + (optional) Ollama. Easy for reviewers to spin up.",
        tech: "docker-compose.yml",
      },
    ],
  },
];

const exampleQueries = [
  "What medications is patient X currently taking for diabetes?",
  "Show me all abnormal lab results from the last 6 months",
  "Has this patient had any drug interactions flagged?",
  "Summarize the treatment history for patient Y's hypertension",
  "Which patients have uncontrolled HbA1c levels?",
];

const repoStructure = `fhir-rag/
├── docker-compose.yml
├── README.md
├── data/
│   └── synthea/              # generated FHIR bundles
├── src/
│   ├── ingestion/
│   │   ├── fhir_parser.py
│   │   ├── chunker.py        # FHIR-aware chunking
│   │   └── embedder.py
│   ├── retrieval/
│   │   ├── hybrid_search.py
│   │   ├── reference_resolver.py
│   │   └── context_builder.py
│   ├── generation/
│   │   ├── prompts/
│   │   │   └── clinical_qa.jinja2
│   │   ├── llm_client.py
│   │   └── citation_mapper.py
│   ├── frontend/              # static files, no build
│   │   ├── index.html         # Alpine.js + Pico CSS
│   │   ├── app.js             # ~60 lines of app logic
│   │   └── style.css          # minimal overrides
│   └── api/
│       ├── main.py            # FastAPI app + static mount
│       ├── routes.py          # JSON API endpoints
│       └── schemas.py
├── tests/
│   ├── test_chunker.py
│   ├── test_retrieval.py
│   └── test_e2e.py
└── eval/
    ├── questions.json         # evaluation dataset
    └── evaluate.py            # retrieval quality metrics`;

export default function FHIRRAGArchitecture() {
  const [activeLayer, setActiveLayer] = useState(null);
  const [activeTab, setActiveTab] = useState("arch");

  return (
    <div style={{
      fontFamily: "'IBM Plex Sans', 'Inter', system-ui, sans-serif",
      background: "#0d1117",
      color: "#c9d1d9",
      minHeight: "100vh",
      padding: "2rem 1.25rem",
      maxWidth: 720,
      margin: "0 auto",
    }}>
      {/* Header */}
      <div style={{ marginBottom: "2.5rem" }}>
        <div style={{
          display: "inline-block",
          background: "#1a5276",
          color: "#7ec8e3",
          fontSize: "0.7rem",
          fontWeight: 600,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          padding: "4px 10px",
          borderRadius: 4,
          marginBottom: 12,
        }}>
          Portfolio Project
        </div>
        <h1 style={{
          fontFamily: "'IBM Plex Mono', 'SF Mono', monospace",
          fontSize: "1.6rem",
          fontWeight: 600,
          color: "#e6edf3",
          margin: 0,
          lineHeight: 1.3,
        }}>
          fhir-rag
        </h1>
        <p style={{
          fontSize: "0.95rem",
          color: "#8b949e",
          margin: "8px 0 0",
          lineHeight: 1.5,
        }}>
          Clinical Q&A over FHIR R4 patient data using retrieval-augmented generation with FHIR-aware chunking, hybrid search, and grounded citations.
        </p>
      </div>

      {/* Tabs */}
      <div style={{
        display: "flex",
        gap: 0,
        borderBottom: "1px solid #21262d",
        marginBottom: "1.5rem",
      }}>
        {[
          { id: "arch", label: "Architecture" },
          { id: "queries", label: "Example Queries" },
          { id: "repo", label: "Repo Structure" },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              background: "none",
              border: "none",
              borderBottom: activeTab === tab.id ? "2px solid #58a6ff" : "2px solid transparent",
              color: activeTab === tab.id ? "#e6edf3" : "#8b949e",
              fontSize: "0.82rem",
              fontWeight: 500,
              padding: "8px 16px",
              cursor: "pointer",
              transition: "color 0.15s",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Architecture Tab */}
      {activeTab === "arch" && (
        <div>
          {layers.map((layer, li) => (
            <div key={layer.id} style={{ marginBottom: "1.25rem" }}>
              {/* Layer header */}
              <button
                onClick={() => setActiveLayer(activeLayer === layer.id ? null : layer.id)}
                style={{
                  width: "100%",
                  background: activeLayer === layer.id ? layer.color : "#161b22",
                  border: `1px solid ${activeLayer === layer.id ? layer.accent : "#21262d"}`,
                  borderRadius: activeLayer === layer.id ? "8px 8px 0 0" : 8,
                  padding: "12px 16px",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  transition: "all 0.2s",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <span style={{
                    fontFamily: "'IBM Plex Mono', monospace",
                    fontSize: "0.7rem",
                    color: layer.accent,
                    fontWeight: 600,
                    minWidth: 18,
                  }}>
                    {String(li + 1).padStart(2, "0")}
                  </span>
                  <span style={{
                    color: "#e6edf3",
                    fontSize: "0.9rem",
                    fontWeight: 600,
                  }}>
                    {layer.label}
                  </span>
                </div>
                <span style={{
                  color: "#8b949e",
                  fontSize: "0.75rem",
                  transform: activeLayer === layer.id ? "rotate(180deg)" : "none",
                  transition: "transform 0.2s",
                }}>
                  ▼
                </span>
              </button>

              {/* Components */}
              {activeLayer === layer.id && (
                <div style={{
                  border: `1px solid ${layer.accent}`,
                  borderTop: "none",
                  borderRadius: "0 0 8px 8px",
                  background: "#0d1117",
                  padding: "4px",
                }}>
                  {layer.components.map((comp, ci) => (
                    <div
                      key={ci}
                      style={{
                        padding: "14px 16px",
                        borderBottom: ci < layer.components.length - 1 ? "1px solid #161b22" : "none",
                        position: "relative",
                      }}
                    >
                      {comp.highlight && (
                        <span style={{
                          position: "absolute",
                          top: 14,
                          right: 16,
                          fontSize: "0.6rem",
                          fontWeight: 700,
                          color: "#f0883e",
                          background: "#2d1a04",
                          padding: "2px 6px",
                          borderRadius: 3,
                          letterSpacing: "0.04em",
                        }}>
                          DIFFERENTIATOR
                        </span>
                      )}
                      <div style={{
                        fontWeight: 600,
                        color: "#e6edf3",
                        fontSize: "0.85rem",
                        marginBottom: 4,
                      }}>
                        {comp.name}
                      </div>
                      <div style={{
                        fontSize: "0.8rem",
                        color: "#8b949e",
                        lineHeight: 1.5,
                        marginBottom: 6,
                      }}>
                        {comp.desc}
                      </div>
                      <div style={{
                        fontFamily: "'IBM Plex Mono', monospace",
                        fontSize: "0.7rem",
                        color: layer.accent,
                      }}>
                        {comp.tech}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Flow arrow */}
              {li < layers.length - 1 && (
                <div style={{
                  textAlign: "center",
                  color: "#30363d",
                  fontSize: "1.2rem",
                  margin: "4px 0",
                }}>
                  ↓
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Queries Tab */}
      {activeTab === "queries" && (
        <div>
          <p style={{ fontSize: "0.82rem", color: "#8b949e", marginBottom: 16, lineHeight: 1.5 }}>
            These are the kinds of questions a clinician would ask. Each exercises different retrieval paths — some need single-resource lookup, others need cross-resource reasoning.
          </p>
          {exampleQueries.map((q, i) => (
            <div
              key={i}
              style={{
                background: "#161b22",
                border: "1px solid #21262d",
                borderRadius: 6,
                padding: "12px 16px",
                marginBottom: 8,
                fontSize: "0.85rem",
                color: "#c9d1d9",
                display: "flex",
                gap: 12,
                alignItems: "flex-start",
              }}
            >
              <span style={{
                fontFamily: "'IBM Plex Mono', monospace",
                color: "#27ae60",
                fontSize: "0.75rem",
                marginTop: 2,
                flexShrink: 0,
              }}>
                Q{i + 1}
              </span>
              <span>{q}</span>
            </div>
          ))}
          <div style={{
            marginTop: 20,
            background: "#1c2128",
            border: "1px solid #2d333b",
            borderRadius: 6,
            padding: "14px 16px",
            fontSize: "0.8rem",
            color: "#8b949e",
            lineHeight: 1.6,
          }}>
            <strong style={{ color: "#d4a017" }}>Eval tip:</strong> Build a JSON file with 20–30 question/expected-resource pairs. Measure retrieval recall (did the right FHIR resources get retrieved?) and answer faithfulness (does the answer only use retrieved context?). This eval harness is what separates a portfolio piece from a tutorial.
          </div>
        </div>
      )}

      {/* Repo Tab */}
      {activeTab === "repo" && (
        <div>
          <pre style={{
            fontFamily: "'IBM Plex Mono', 'SF Mono', monospace",
            fontSize: "0.75rem",
            lineHeight: 1.7,
            color: "#c9d1d9",
            background: "#161b22",
            border: "1px solid #21262d",
            borderRadius: 8,
            padding: "20px",
            overflowX: "auto",
            margin: 0,
          }}>
            {repoStructure}
          </pre>
          <div style={{
            marginTop: 16,
            fontSize: "0.8rem",
            color: "#8b949e",
            lineHeight: 1.6,
          }}>
            <strong style={{ color: "#e6edf3" }}>Key files to polish for portfolio review:</strong>
            <div style={{ marginTop: 8, paddingLeft: 12 }}>
              <div style={{ marginBottom: 4 }}>
                <span style={{ color: "#a569bd", fontFamily: "monospace" }}>chunker.py</span>
                {" "}— shows you understand FHIR resource structure, not just text splitting
              </div>
              <div style={{ marginBottom: 4 }}>
                <span style={{ color: "#a569bd", fontFamily: "monospace" }}>hybrid_search.py</span>
                {" "}— demonstrates structured + semantic retrieval
              </div>
              <div style={{ marginBottom: 4 }}>
                <span style={{ color: "#a569bd", fontFamily: "monospace" }}>clinical_qa.jinja2</span>
                {" "}— your prompt engineering, grounding instructions
              </div>
              <div>
                <span style={{ color: "#a569bd", fontFamily: "monospace" }}>evaluate.py</span>
                {" "}— proves you measure quality, not just ship features
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <div style={{
        marginTop: "2.5rem",
        borderTop: "1px solid #21262d",
        paddingTop: 16,
        fontSize: "0.75rem",
        color: "#484f58",
        lineHeight: 1.6,
      }}>
        Stack: Python · FastAPI · pgvector · FHIR R4 · Docker · Claude API
      </div>
    </div>
  );
}
