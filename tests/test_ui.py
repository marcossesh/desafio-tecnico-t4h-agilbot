"""UI e camada de sessão — sem subir o Streamlit."""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError

from src.core.constants import MSG_INSTABILIDADE
from tests.fakes import chama, fala
from ui.service import Atendimento, _ultima_fala, historico_visivel


@pytest.fixture
def atendimento(monkeypatch, servicos) -> Atendimento:
    """Atendimento isolado de qualquer infraestrutura externa.

    O patch precisa alcançar cada módulo que importou `get_settings` por nome — trocar só
    em `src.core.config` deixaria o checkpointer tentando conectar no Postgres real.
    """
    from src.core.config import Settings

    settings = Settings(POSTGRES_URL="", GOOGLE_API_KEY="", GROQ_API_KEY="")
    for modulo in ("src.core.config", "src.providers.checkpointer", "src.providers.llm"):
        monkeypatch.setattr(f"{modulo}.get_settings", lambda: settings)
    return Atendimento()


class TestImports:
    def test_modulos_da_ui_importam(self):
        """Erro de import na UI só apareceria ao subir o Streamlit — barato de cobrir aqui."""
        import ui.components.chat
        import ui.components.sidebar
        import ui.state
        import ui.streamlit_app
        import ui.styles  # noqa: F401


class TestSessao:
    def test_sem_postgres_cai_para_memoria(self, atendimento: Atendimento):
        assert "memória" in atendimento.persistencia

    def test_conversa_mantem_contexto_entre_chamadas(self, monkeypatch, atendimento):
        """O histórico vive no checkpointer, indexado pelo thread_id — não na UI."""
        from tests.fakes import FakeChatModel

        fake = FakeChatModel([chama("verificar_cpf", cpf="111.444.777-35"),
                              fala("Qual sua data de nascimento?")])
        monkeypatch.setattr("src.agents.base.get_chat_model", lambda: fake)
        atendimento.responder("sessao-1", "meu CPF é 111.444.777-35")

        fake2 = FakeChatModel([fala("Obrigado!")])
        monkeypatch.setattr("src.agents.base.get_chat_model", lambda: fake2)
        atendimento.responder("sessao-1", "14/05/1990")

        # O CPF do primeiro turno chegou ao segundo pelo bloco de contexto.
        assert "111.444.777-35" in fake2.prompt_da_chamada(0)

    def test_sessoes_diferentes_nao_se_misturam(self, monkeypatch, atendimento):
        from tests.fakes import FakeChatModel

        fake = FakeChatModel([chama("verificar_cpf", cpf="111.444.777-35"), fala("ok")])
        monkeypatch.setattr("src.agents.base.get_chat_model", lambda: fake)
        atendimento.responder("sessao-A", "CPF 111.444.777-35")

        fake2 = FakeChatModel([fala("Qual seu CPF?")])
        monkeypatch.setattr("src.agents.base.get_chat_model", lambda: fake2)
        atendimento.responder("sessao-B", "oi")

        assert "111.444.777-35" not in fake2.prompt_da_chamada(0)

    def test_historico_visivel_omite_mensagens_internas(self, monkeypatch, atendimento):
        from tests.fakes import FakeChatModel

        fake = FakeChatModel([chama("verificar_cpf", cpf="111.444.777-35"),
                              fala("Qual sua data de nascimento?")])
        monkeypatch.setattr("src.agents.base.get_chat_model", lambda: fake)
        atendimento.responder("sessao-hist", "meu CPF é 111.444.777-35")

        visivel = historico_visivel(atendimento, "sessao-hist")

        assert [m["role"] for m in visivel] == ["user", "assistant"]
        assert all("[interno]" not in m["content"] for m in visivel)


class TestErros:
    def test_recursion_error_vira_mensagem_amigavel(self, monkeypatch, atendimento):
        def estoura(*_a, **_k):
            raise GraphRecursionError("limite")

        monkeypatch.setattr(atendimento.grafo, "invoke", estoura)
        resposta = atendimento.responder("s", "oi")

        assert resposta.debug["erro"] == "recursion_limit"
        assert "reformular" in resposta.texto

    def test_falha_inesperada_nao_propaga(self, monkeypatch, atendimento):
        def explode(*_a, **_k):
            raise RuntimeError("pane")

        monkeypatch.setattr(atendimento.grafo, "invoke", explode)
        resposta = atendimento.responder("s", "oi")

        assert resposta.texto == MSG_INSTABILIDADE

    def test_estado_sem_fala_devolve_mensagem_controlada(self):
        assert _ultima_fala({"messages": [HumanMessage(content="oi")]}) == MSG_INSTABILIDADE
        assert _ultima_fala({"messages": [AIMessage(content="olá")]}) == "olá"
