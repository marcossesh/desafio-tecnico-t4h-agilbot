"""Carrega e fatia os documentos da base de conhecimento."""
from __future__ import annotations

import hashlib
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.core.logging import get_logger

logger = get_logger(__name__)

DOCUMENTOS_DIR = Path(__file__).resolve().parent / "documents"
TAMANHO_CHUNK = 500
SOBREPOSICAO = 80


def hash_do_corpus() -> str:
    """Impressão digital do conteúdo dos documentos."""
    digest = hashlib.sha256()
    for caminho in sorted(DOCUMENTOS_DIR.glob("*.md")):
        digest.update(caminho.name.encode("utf-8"))
        digest.update(caminho.read_bytes())
    return digest.hexdigest()[:16]


def carregar_documentos() -> list[Document]:
    """Lê os `.md` e devolve os chunks, cada um com sua fonte nos metadados."""
    versao = hash_do_corpus()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=TAMANHO_CHUNK,
        chunk_overlap=SOBREPOSICAO,
        separators=["\n## ", "\n### ", "\n\n", "\n", " "],
    )

    chunks: list[Document] = []
    for caminho in sorted(DOCUMENTOS_DIR.glob("*.md")):
        try:
            texto = caminho.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Falha ao ler documento %s: %s", caminho.name, exc)
            continue

        for pedaco in splitter.split_text(texto):
            chunks.append(
                Document(
                    page_content=pedaco,
                    metadata={"fonte": caminho.stem, "versao_corpus": versao},
                )
            )

    logger.info("Base de conhecimento: %d chunks de %s.", len(chunks), DOCUMENTOS_DIR.name)
    return chunks
