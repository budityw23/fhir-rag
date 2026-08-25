CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS fhir_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_id TEXT NOT NULL UNIQUE,
    resource_type TEXT NOT NULL,
    patient_ref TEXT NOT NULL,
    resource_date TIMESTAMPTZ,
    codes JSONB DEFAULT '[]',
    references TEXT[] DEFAULT '{}',
    text_content TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fhir_chunks_embedding ON fhir_chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_resource_type ON fhir_chunks (resource_type);
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_patient_ref ON fhir_chunks (patient_ref);
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_resource_date ON fhir_chunks (resource_date);
CREATE INDEX IF NOT EXISTS idx_fhir_chunks_resource_id ON fhir_chunks (resource_id);

