"""Configuração da aplicação, lida do ambiente ou de um `.env` na raiz do projeto."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.constants import ENV_FILE


class Settings(BaseSettings):
    """Configurações da aplicação."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    gemini_model: str = Field(default="gemini-3.5-flash-lite", alias="GEMINI_MODEL")
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")
    temperatura: float | None = Field(default=None, alias="LLM_TEMPERATURE")

    postgres_url: str = Field(default="", alias="POSTGRES_URL")
    embedding_model: str = Field(default="models/gemini-embedding-001", alias="EMBEDDING_MODEL")
    rag_top_k: int = Field(default=3, alias="RAG_TOP_K")

    awesomeapi_base_url: str = Field(
        default="https://economia.awesomeapi.com.br/json/last", alias="AWESOMEAPI_BASE_URL"
    )

    @property
    def tem_gemini(self) -> bool:
        return bool(self.google_api_key)

    @property
    def tem_groq(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def rag_enabled(self) -> bool:
        """RAG exige embeddings (Gemini) E o Postgres com pgvector."""
        return self.tem_gemini and bool(self.postgres_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Instância única de configurações."""
    return Settings()
