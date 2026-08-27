"""Application configuration loaded from environment variables."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the FHIR RAG application."""

    database_url: str = "postgresql://fhir:fhir@localhost:5432/fhir_rag"
    llm_provider: Literal["claude", "gemini", "vertex", "ollama"] = "claude"
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    vertex_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    ollama_base_url: str = "http://localhost:11434"
    embedding_backend: Literal["hash", "transformer"] = "hash"
    embedding_model: str = "all-MiniLM-L6-v2"
    top_k: int = 25
    max_reference_hops: int = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
