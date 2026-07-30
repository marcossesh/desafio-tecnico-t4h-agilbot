"""RAG: carregamento dos documentos e degradação segura sem infraestrutura."""
from __future__ import annotations

import pytest
from langchain_core.documents import Document

from src.core.config import Settings
from src.rag.loader import DOCUMENTOS_DIR, carregar_documentos, hash_do_corpus
from src.services.knowledge_service import KnowledgeService

# Os módulos importam `get_settings` por nome, então o patch precisa alcançar cada
# consumidor — não basta trocar em `src.core.config`.
CONSUMIDORES_DE_SETTINGS = (
    "src.core.config",
    "src.services.knowledge_service",
    "src.agents.credito",
    "src.agents.cambio",
)


def usar_settings(monkeypatch, **valores) -> Settings:
    settings = Settings(**valores)
    for modulo in CONSUMIDORES_DE_SETTINGS:
        monkeypatch.setattr(f"{modulo}.get_settings", lambda: settings)
    return settings


class TestLoader:
    def test_carrega_todos_os_documentos(self):
        fontes = {d.metadata["fonte"] for d in carregar_documentos()}
        assert fontes == {
            "politica_credito", "tarifas", "cambio", "seguranca_lgpd", "geral"
        }

    def test_chunks_carregam_a_versao_do_corpus(self):
        versao = hash_do_corpus()
        assert all(d.metadata["versao_corpus"] == versao for d in carregar_documentos())

    def test_hash_muda_quando_o_conteudo_muda(self, tmp_path, monkeypatch):
        antes = hash_do_corpus()
        extra = DOCUMENTOS_DIR / "_temporario_teste.md"
        extra.write_text("# Novo documento\n\nConteúdo.", encoding="utf-8")
        try:
            assert hash_do_corpus() != antes
        finally:
            extra.unlink()
        assert hash_do_corpus() == antes


class TestDegradacao:
    """Sem Postgres ou sem chave de embeddings, o RAG some — sem quebrar nada."""

    @pytest.mark.parametrize(
        ("google", "postgres"),
        [("", ""), ("", "postgresql://x"), ("chave", "")],
    )
    def test_rag_desabilitado_sem_infraestrutura(self, monkeypatch, google, postgres):
        settings = usar_settings(monkeypatch, GOOGLE_API_KEY=google, POSTGRES_URL=postgres)

        assert settings.rag_enabled is False
        assert KnowledgeService().consultar("qual a tarifa do TED?").ok is False

    def test_rag_habilitado_com_ambos(self, monkeypatch):
        settings = usar_settings(
            monkeypatch, GOOGLE_API_KEY="chave", POSTGRES_URL="postgresql://x"
        )
        assert settings.rag_enabled is True

    def test_falha_na_busca_nao_propaga(self, monkeypatch):
        usar_settings(monkeypatch, GOOGLE_API_KEY="chave", POSTGRES_URL="postgresql://x")

        def explode(*_a, **_k):
            raise RuntimeError("banco fora do ar")

        monkeypatch.setattr("src.providers.vectorstore.buscar_similares", explode)

        assert KnowledgeService().consultar("tarifas").ok is False

    def test_resultado_agrega_contexto_e_fontes(self, monkeypatch):
        usar_settings(monkeypatch, GOOGLE_API_KEY="chave", POSTGRES_URL="postgresql://x")
        monkeypatch.setattr(
            "src.providers.vectorstore.buscar_similares",
            lambda _p, k=3: [
                Document(page_content="TED custa R$ 8,50.", metadata={"fonte": "tarifas"}),
                Document(page_content="Pix é isento.", metadata={"fonte": "tarifas"}),
            ],
        )

        resultado = KnowledgeService().consultar("quanto custa um TED?")

        assert resultado.ok
        assert "8,50" in resultado.contexto
        assert resultado.fontes == ["tarifas"]


class TestFerramentaCondicional:
    """A flag age no `bind_tools`: sem RAG, o modelo nem enxerga a ferramenta."""

    def test_ferramenta_ausente_sem_rag(self, monkeypatch):
        from src.agents import cambio, credito

        usar_settings(monkeypatch, GOOGLE_API_KEY="", POSTGRES_URL="")

        for agente in (credito, cambio):
            nomes = {t.name for t in agente.tools()}
            assert "consultar_base_conhecimento" not in nomes

    def test_ferramenta_presente_com_rag(self, monkeypatch):
        from src.agents import cambio, credito

        usar_settings(monkeypatch, GOOGLE_API_KEY="k", POSTGRES_URL="postgresql://x")

        for agente in (credito, cambio):
            nomes = {t.name for t in agente.tools()}
            assert "consultar_base_conhecimento" in nomes

    def test_triagem_nunca_recebe_a_ferramenta(self, monkeypatch):
        """Responder sobre tarifas está fora do escopo que o enunciado dá à triagem."""
        from src.agents import triagem

        usar_settings(monkeypatch, GOOGLE_API_KEY="k", POSTGRES_URL="postgresql://x")

        assert "consultar_base_conhecimento" not in {t.name for t in triagem.TOOLS}
