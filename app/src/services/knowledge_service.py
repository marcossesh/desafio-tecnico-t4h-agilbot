"""Base de conhecimento (RAG) sobre as políticas do banco."""
from __future__ import annotations

from src.core.config import get_settings
from src.core.logging import get_logger
from src.domain.results import ResultadoConhecimento

logger = get_logger(__name__)


class KnowledgeService:
    def __init__(self, top_k: int | None = None):
        self.top_k = top_k or get_settings().rag_top_k

    @property
    def disponivel(self) -> bool:
        return get_settings().rag_enabled

    def consultar(self, pergunta: str) -> ResultadoConhecimento:
        if not self.disponivel or not pergunta.strip():
            return ResultadoConhecimento(ok=False)

        try:
            from src.providers.vectorstore import buscar_similares
        except ImportError:
            logger.warning("Vector store não disponível; RAG desligado.")
            return ResultadoConhecimento(ok=False)

        try:
            trechos = buscar_similares(pergunta, k=self.top_k)
        except Exception as exc:
            logger.error("Falha na consulta à base de conhecimento: %s", exc)
            return ResultadoConhecimento(ok=False)

        if not trechos:
            return ResultadoConhecimento(ok=False)

        return ResultadoConhecimento(
            ok=True,
            contexto="\n\n".join(t.page_content for t in trechos),
            fontes=sorted({str(t.metadata.get("fonte", "base")) for t in trechos}),
        )
