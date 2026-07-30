"""Embeddings para o RAG. Sem `GOOGLE_API_KEY`, devolve `None` e o RAG fica desligado."""
from __future__ import annotations

from functools import lru_cache

from langchain_core.embeddings import Embeddings

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings | None:
    settings = get_settings()
    if not settings.tem_gemini:
        logger.info("Sem GOOGLE_API_KEY: RAG desligado.")
        return None

    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(
            model=settings.embedding_model, google_api_key=settings.google_api_key
        )
    except Exception as exc:
        logger.error("Falha ao inicializar embeddings: %s", exc)
        return None


def dimensao(embeddings: Embeddings) -> int:
    """Descobre a dimensão do vetor embutindo uma sonda."""
    return len(embeddings.embed_query("sonda de dimensão"))
