-- Adds the lexical arm of hybrid retrieval to an existing database.
--
-- db/init.sql only runs when the Postgres volume is empty, so a deployment
-- created before this column existed will not pick it up. Apply once with:
--
--   docker compose exec -T db psql -U fhir -d fhir_rag \
--     -f - < db/migrations/001_add_text_search.sql
--
-- Safe to re-run. Building the GIN index over a large table takes a few
-- minutes and holds a lock, so schedule it accordingly.

ALTER TABLE fhir_chunks
    ADD COLUMN IF NOT EXISTS text_search TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('english', text_content)) STORED;

CREATE INDEX IF NOT EXISTS idx_fhir_chunks_text_search
    ON fhir_chunks USING gin (text_search);
