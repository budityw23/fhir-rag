"""CLI pipeline for loading FHIR resources into pgvector."""

import argparse
import asyncio
import json
from pathlib import Path

import asyncpg
from pgvector.asyncpg import register_vector

from ..config import settings
from .chunker import FHIRChunk, chunk_resource
from .embedder import Embedder
from .fhir_parser import parse_all_bundles

EMBED_BATCH_SIZE = 32


async def ingest_bundles(data_dir: Path, db_url: str) -> dict:
    """Main ingestion pipeline. Returns stats dict."""
    bundle_paths = sorted(data_dir.glob("*.json"))
    stats = {"bundles": len(bundle_paths), "resources": 0, "chunks_stored": 0}
    if not bundle_paths:
        print(f"No FHIR bundles found in {data_dir}")
        print(f"Final stats: {stats}")
        return stats

    parsed_resources = parse_all_bundles(data_dir)
    stats["resources"] = len(parsed_resources)
    chunks = [chunk_resource(resource) for resource in parsed_resources]
    if not chunks:
        print(f"No supported resources found in {data_dir}")
        print(f"Final stats: {stats}")
        return stats

    print(f"Parsed {len(parsed_resources)} resources from {len(bundle_paths)} bundles")
    embedder = Embedder(settings.embedding_model, settings.embedding_backend)
    embeddings: list[list[float]] = []
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[start:start + EMBED_BATCH_SIZE]
        embeddings.extend(embedder.embed_texts([chunk.text_content for chunk in batch]))
        print(f"Embedded {min(start + len(batch), len(chunks))}/{len(chunks)} chunks")

    pool = await asyncpg.create_pool(db_url)
    try:
        stats["chunks_stored"] = await store_chunks(pool, chunks, embeddings)
    finally:
        await pool.close()

    print(f"Final stats: {stats}")
    return stats


async def store_chunks(pool, chunks: list[FHIRChunk], embeddings: list[list[float]]) -> int:
    """Batch insert chunks into fhir_chunks table. Returns count stored."""
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"Expected one embedding per chunk, got {len(embeddings)} for {len(chunks)} chunks"
        )
    if not chunks:
        return 0

    query = """
        INSERT INTO fhir_chunks (
            resource_id, resource_type, patient_ref, resource_date,
            codes, "references", text_content, embedding
        ) VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)
        ON CONFLICT (resource_id) DO UPDATE SET
            resource_type = EXCLUDED.resource_type,
            patient_ref = EXCLUDED.patient_ref,
            resource_date = EXCLUDED.resource_date,
            codes = EXCLUDED.codes,
            "references" = EXCLUDED."references",
            text_content = EXCLUDED.text_content,
            embedding = EXCLUDED.embedding
    """
    records = [
        (
            chunk.resource_id,
            chunk.resource_type,
            chunk.patient_ref,
            chunk.resource_date,
            json.dumps(chunk.codes),
            chunk.references,
            chunk.text_content,
            embedding,
        )
        for chunk, embedding in zip(chunks, embeddings)
    ]

    async with pool.acquire() as connection:
        await register_vector(connection)
        await connection.executemany(query, records)
    # asyncpg executemany does not return affected-row counts. The upsert is
    # idempotent; callers receive the number of attempted stored chunks.
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest FHIR Bundles into pgvector")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/synthea"),
        help="Directory containing FHIR Bundle JSON files",
    )
    parser.add_argument(
        "--db-url",
        default=settings.database_url,
        help="PostgreSQL connection URL",
    )
    args = parser.parse_args()
    asyncio.run(ingest_bundles(args.data_dir, args.db_url))


if __name__ == "__main__":
    main()
