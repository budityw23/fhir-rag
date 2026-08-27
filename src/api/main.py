"""FastAPI application factory and lifecycle configuration."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..config import settings
from ..database import close_pool, init_pool
from ..generation.llm_client import LLMClient
from ..ingestion.embedder import Embedder
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared pipeline services and close the database pool."""
    owns_pool = app.state.pool is None
    if owns_pool:
        app.state.pool = await init_pool()
    if app.state.embedder is None:
        app.state.embedder = Embedder(settings.embedding_model, settings.embedding_backend)
        # The transformer backend loads its weights lazily on first use, which
        # would otherwise stall the first real query by ~10s. Pay that cost at
        # startup instead, off the request path.
        await asyncio.to_thread(app.state.embedder.embed_query, "warmup")
    if app.state.llm_client is None:
        app.state.llm_client = LLMClient(
            settings.llm_provider,
            api_key=(
                settings.gemini_api_key
                if settings.llm_provider == "gemini"
                else (
                    settings.vertex_api_key
                    if settings.llm_provider == "vertex"
                    else settings.anthropic_api_key
                )
            ),
            ollama_url=settings.ollama_base_url,
            gemini_model=settings.gemini_model,
        )
    try:
        yield
    finally:
        if owns_pool:
            await close_pool()


def create_app() -> FastAPI:
    """Create and configure the FHIR RAG FastAPI application."""
    application = FastAPI(title="FHIR RAG", lifespan=lifespan)
    application.state.pool = None
    application.state.embedder = None
    application.state.llm_client = None
    application.include_router(router)
    frontend_dir = Path(__file__).parent.parent / "frontend"
    application.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return application


app = create_app()
