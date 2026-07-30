"""Ingestão da base de conhecimento no pgvector."""
from __future__ import annotations

from src.core.logging import get_logger
from src.providers.vectorstore import VectorStoreIndisponivelError, get_vectorstore
from src.rag.loader import carregar_documentos, hash_do_corpus

logger = get_logger(__name__)


def _ja_indexado(store, versao: str) -> bool:
    """Uma sondagem por similaridade basta: se vier algo com a versão atual, está feito."""
    try:
        achados = store.similarity_search("política de crédito do banco", k=1)
    except Exception:
        return False
    return bool(achados) and achados[0].metadata.get("versao_corpus") == versao


def ingerir(forcar: bool = False) -> int:
    """Indexa os documentos. Devolve quantos chunks foram gravados (0 se já estava em dia)."""
    try:
        store = get_vectorstore()
    except VectorStoreIndisponivelError as exc:
        logger.warning("Ingestão ignorada: %s", exc)
        return 0

    versao = hash_do_corpus()
    if not forcar and _ja_indexado(store, versao):
        logger.info("Base de conhecimento já está na versão %s; nada a fazer.", versao)
        return 0

    chunks = carregar_documentos()
    if not chunks:
        logger.warning("Nenhum documento encontrado para indexar.")
        return 0

    store.add_documents(chunks)
    logger.info("Base de conhecimento indexada: %d chunks (versão %s).", len(chunks), versao)
    return len(chunks)


if __name__ == "__main__":
    import sys

    total = ingerir(forcar="--forcar" in sys.argv)
    print(f"{total} chunks indexados.")
