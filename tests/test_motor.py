"""Motor de turno: sanitização, injeção de contexto, handoff e redes de segurança.

Estes testes protegem o desenho descrito em `agents/base.py`. Sem eles, uma regressão na
sanitização só apareceria como "o atendente pediu meu CPF três vezes" numa demo.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.base import CHAVE_HANDOFF, run_agent_turn, sanitizar_historico
from src.agents.contexto import render_contexto
from src.core.constants import MAX_TENTATIVAS_AUTH, MSG_INSTABILIDADE
from tests.fakes import FakeChatModel, chama, fala


@pytest.fixture
def modelo(monkeypatch):
    """Substitui o provider por um LLM roteirizado."""

    def instalar(*respostas: AIMessage) -> FakeChatModel:
        fake = FakeChatModel(list(respostas))
        monkeypatch.setattr("src.agents.base.get_chat_model", lambda: fake)
        return fake

    return instalar


def estado(**kwargs) -> dict:
    base = {
        "messages": [], "cpf_informado": "", "cpf": "", "authenticated": False,
        "auth_attempts": 0, "cliente": None, "current_agent": "triagem",
        "finished": False, "ultima_solicitacao": None, "entrevista_oferecida": False,
    }
    return {**base, **kwargs}


class TestSanitizacao:
    def test_descarta_tool_messages_e_tool_calls(self):
        historico = [
            HumanMessage(content="meu CPF é 111.444.777-35"),
            AIMessage(content="", tool_calls=[{"name": "verificar_cpf", "args": {}, "id": "1"}]),
            ToolMessage(content="[interno] CPF válido", tool_call_id="1", name="verificar_cpf"),
            AIMessage(content="Qual sua data de nascimento?"),
            HumanMessage(content="14/05/1990"),
        ]

        limpo = sanitizar_historico(historico)

        assert [type(m).__name__ for m in limpo] == [
            "HumanMessage", "AIMessage", "HumanMessage"
        ]
        assert not any(getattr(m, "tool_calls", None) for m in limpo)

    def test_agente_nao_recebe_ferramenta_que_nao_declara(self, modelo):
        """A raiz do problema: o nó de destino receberia tool calls de ferramentas fora
        do seu `bind_tools`, e provedores com function calling recusam isso."""
        historico = [
            HumanMessage(content="oi"),
            AIMessage(
                content="", tool_calls=[{"name": "ferramenta_de_outro", "args": {}, "id": "9"}]
            ),
            ToolMessage(content="x", tool_call_id="9", name="ferramenta_de_outro"),
        ]
        fake = modelo(fala("Olá!"))

        run_agent_turn(estado(messages=historico), "credito", "PROMPT", [], {})

        recebido = fake.historico_da_chamada(0)
        assert all(not getattr(m, "tool_calls", None) for m in recebido)


class TestInjecaoDeContexto:
    def test_cpf_informado_sobrevive_ao_turno_seguinte(self, modelo):
        """O caso que a sanitização quebraria: CPF no turno 1, data no turno 2."""
        fake = modelo(fala("Qual sua data de nascimento?"))

        run_agent_turn(
            estado(cpf_informado="11144477735", messages=[HumanMessage(content="14/05/1990")]),
            "triagem", "PROMPT", [], {},
        )

        prompt = fake.prompt_da_chamada(0)
        assert "111.444.777-35" in prompt
        assert "JÁ informou o CPF" in prompt

    def test_contexto_do_cliente_autenticado(self):
        bloco = render_contexto(
            estado(
                authenticated=True,
                cliente={
                    "cpf": "11144477735", "nome": "Ana Souza",
                    "data_nascimento": "1990-05-14", "limite_atual": 5000.0, "score": 540,
                },
            )
        )
        assert "Ana Souza" in bloco
        assert "R$ 5.000,00" in bloco
        assert "540" in bloco

    def test_contexto_mostra_tentativas_restantes(self):
        bloco = render_contexto(estado(auth_attempts=2))
        assert f"2 de {MAX_TENTATIVAS_AUTH}" in bloco
        assert "restam 1" in bloco

    def test_contexto_vazio_no_inicio(self):
        assert "NÃO autenticado" in render_contexto(estado())


class TestHandoff:
    def test_handoff_encerra_o_turno_e_silencia_o_agente_de_origem(self, modelo):
        """Se as duas falas saíssem, o cliente veria a costura da transição."""
        modelo(
            AIMessage(
                content="Vou ver isso para você.",
                tool_calls=[{"name": "ir", "args": {}, "id": "1"}],
            ),
            fala("esta fala não deveria acontecer"),
        )
        handlers = {"ir": lambda _a, _s: ("[interno] ok", {CHAVE_HANDOFF: "credito"})}

        updates, destino = run_agent_turn(estado(), "triagem", "P", [], handlers)

        assert destino == "credito"
        textos = [m.content for m in updates["messages"] if isinstance(m, AIMessage)]
        assert all(not t for t in textos), "o agente de origem não fala com o cliente"

    def test_tool_calls_do_handoff_ficam_no_estado_para_auditoria(self, modelo):
        modelo(chama("ir"))
        handlers = {"ir": lambda _a, _s: ("[interno] ok", {CHAVE_HANDOFF: "credito"})}

        updates, _ = run_agent_turn(estado(), "triagem", "P", [], handlers)

        assert any(isinstance(m, ToolMessage) for m in updates["messages"])

    def test_efeitos_do_handler_viram_atualizacao_de_estado(self, modelo):
        modelo(chama("ir"), fala("pronto"))
        handlers = {
            "ir": lambda _a, _s: ("[interno] ok", {"authenticated": True, "cpf": "123"})
        }

        updates, destino = run_agent_turn(estado(), "triagem", "P", [], handlers)

        assert destino is None
        assert updates["authenticated"] is True
        assert updates["cpf"] == "123"


class TestRedesDeSeguranca:
    def test_turno_sem_texto_forca_redacao_final(self, modelo):
        """Modelos menores às vezes param após a tool call; o cliente ficaria sem resposta."""
        fake = modelo(chama("consultar"), fala("Seu limite é R$ 5.000,00."))
        handlers = {"consultar": lambda _a, _s: ("[interno] limite 5000", {})}

        updates, _ = run_agent_turn(estado(), "credito", "P", [], handlers)

        textos = [
            m.content for m in updates["messages"] if isinstance(m, AIMessage) and m.content
        ]
        assert textos == ["Seu limite é R$ 5.000,00."]
        # A redação final enxerga o resultado da ferramenta (roda antes da sanitização).
        assert any(isinstance(m, ToolMessage) for m in fake.chamadas[-1])

    def test_ferramenta_desconhecida_nao_quebra_o_turno(self, modelo):
        modelo(chama("inexistente"), fala("Desculpe, não consegui fazer isso."))

        updates, _ = run_agent_turn(estado(), "triagem", "P", [], {})

        assert any(
            "indisponível neste contexto" in str(m.content)
            for m in updates["messages"] if isinstance(m, ToolMessage)
        )

    def test_llm_fora_do_ar_vira_mensagem_controlada(self, monkeypatch):
        class Explode(FakeChatModel):
            def _generate(self, *a, **k):
                raise RuntimeError("cota estourada")

        monkeypatch.setattr("src.agents.base.get_chat_model", lambda: Explode([]))

        updates, destino = run_agent_turn(estado(), "triagem", "P", [], {})

        assert destino is None
        assert updates["messages"][-1].content == MSG_INSTABILIDADE

    def test_sem_chave_configurada_nao_levanta(self, monkeypatch):
        from src.providers.llm import LLMIndisponivelError

        def sem_llm():
            raise LLMIndisponivelError("sem chave")

        monkeypatch.setattr("src.agents.base.get_chat_model", sem_llm)

        updates, _ = run_agent_turn(estado(), "triagem", "P", [], {})

        assert updates["messages"][-1].content == MSG_INSTABILIDADE


class TestGuardaDeVazamento:
    def test_acusa_mencao_a_transferencia(self, modelo):
        modelo(fala("Vou transferir você para o setor de crédito."))

        updates, _ = run_agent_turn(estado(), "triagem", "P", [], {})

        assert updates["vazamento_detectado"] is True

    def test_resposta_limpa_nao_acusa(self, modelo):
        modelo(fala("Claro! Seu limite atual é R$ 5.000,00."))

        updates, _ = run_agent_turn(estado(), "triagem", "P", [], {})

        assert updates["vazamento_detectado"] is False


class TestHandlerHostil:
    """O ponto de extensão mais provável do sistema é escrever handlers novos."""

    def test_handler_que_levanta_nao_derruba_o_turno(self, modelo):
        modelo(chama("boom"), fala("Desculpe, não consegui concluir agora."))

        def boom(_a, _s):
            raise RuntimeError("falha inesperada")

        updates, destino = run_agent_turn(estado(), "credito", "P", [], {"boom": boom})

        assert destino is None
        assert any(
            isinstance(m, AIMessage) and m.content for m in updates["messages"]
        ), "o cliente precisa receber alguma resposta"

    def test_falha_de_handler_vira_texto_interno_para_o_modelo(self, modelo):
        modelo(chama("boom"), fala("ok"))

        def boom(_a, _s):
            raise ValueError("x")

        updates, _ = run_agent_turn(estado(), "credito", "P", [], {"boom": boom})

        internos = [
            str(m.content) for m in updates["messages"] if isinstance(m, ToolMessage)
        ]
        assert any("não pôde ser concluída" in t for t in internos)

    def test_tool_call_sem_id_e_tolerado(self, modelo):
        modelo(
            AIMessage(content="", tool_calls=[{"name": "ok", "args": {}, "id": None}]),
            fala("pronto"),
        )
        handlers = {"ok": lambda _a, _s: ("[interno] feito", {})}

        updates, _ = run_agent_turn(estado(), "credito", "P", [], handlers)

        assert any(isinstance(m, ToolMessage) for m in updates["messages"])

    def test_estado_sem_messages_nao_levanta(self, modelo):
        modelo(fala("olá"))
        sem_messages = {k: v for k, v in estado().items() if k != "messages"}

        updates, _ = run_agent_turn(sem_messages, "triagem", "P", [], {})

        assert updates["messages"]
