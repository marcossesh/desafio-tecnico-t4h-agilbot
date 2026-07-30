"""Vector store em PostgreSQL + pgvector."""
from __future__ import annotations

from functools import lru_cache

from langchain_core.documents import Document

from src.core.config import get_settings
from src.core.logging import get_logger
from src.providers.embeddings import dimensao, get_embeddings

logger = get_logger(__name__)

TABELA = "base_conhecimento"


class VectorStoreIndisponivelError(RuntimeError):
    """Postgres fora, sem embeddings ou coleção inacessível."""


def _url_async(url: str) -> str:
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


@lru_cache(maxsize=1)
def get_vectorstore():
    """Coleção pronta para uso, criando a tabela na primeira execução."""
    settings = get_settings()
    if not settings.postgres_url:
        raise VectorStoreIndisponivelError("POSTGRES_URL não configurada.")

    embeddings = get_embeddings()
    if embeddings is None:
        raise VectorStoreIndisponivelError("Embeddings indisponíveis.")

    from langchain_postgres import PGEngine, PGVectorStore

    engine = PGEngine.from_connection_string(url=_url_async(settings.postgres_url))

    try:
        engine.init_vectorstore_table(
            table_name=TABELA, vector_size=dimensao(embeddings)
        )
    except Exception as exc:
        logger.debug("Tabela de vetores já existente ou não recriada: %s", exc)

    return PGVectorStore.create_sync(
        engine=engine, embedding_service=embeddings, table_name=TABELA
    )


def buscar_similares(pergunta: str, k: int = 3) -> list[Document]:
    """Busca por similaridade. Erros sobem para o `KnowledgeService`, que degrada."""
    return get_vectorstore().similarity_search(pergunta, k=k)


def reset_vectorstore() -> None:
    get_vectorstore.cache_clear()
