"""Procedência dos números e das respostas.

Três defeitos observados numa sessão real contra o Gemini, todos da mesma família: o
modelo produziu um dado que ninguém lhe deu. O disco dizia `540 -> 467` e o cliente leu
"seu novo score é 780"; a entrevista concluiu sem nunca perguntar sobre dívidas ativas; e
um pedido de R$ 1 bilhão foi respondido com a oferta de uma entrevista que não poderia
aprová-lo.
"""
from __future__ import annotations

from typing import ClassVar

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.base import _detectar_numeros_inventados
from src.agents.entrevista import _handler_registrar, _perguntas_nao_feitas
from src.core.utils import numeros_do_texto
from src.domain.enums import StatusPedido
from src.domain.models import Cliente
from tests.fakes import chama, fala

CPF_ANA = "11144477735"


class TestNumerosDoTexto:
    @pytest.mark.parametrize(
        ("texto", "esperados"),
        [
            ("Seu score é 467.", {467.0}),
            ("R$ 15.000,00", {15000.0}),
            ("taxa de 5,99% ao mês", {5.99}),
            ("R$ 1.000.000.000,00", {1_000_000_000.0}),
            ("sem número nenhum", set()),
        ],
    )
    def test_extrai_valores_canonicos(self, texto: str, esperados: set[float]):
        assert numeros_do_texto(texto) >= esperados

    def test_milhar_ambiguo_devolve_as_duas_leituras(self):
        """`15.000` é milhar em pt-BR e decimal em inglês; acusar por isso seria ruído."""
        assert numeros_do_texto("15.000") == {15.0, 15000.0}


class TestNumerosInventados:
    """A guarda que teria pego o "780" antes de ele chegar ao cliente."""

    def _ferramenta(self, texto: str) -> ToolMessage:
        return ToolMessage(content=texto, tool_call_id="x", name="registrar_entrevista")

    def test_score_inventado_e_acusado(self):
        novas = [
            self._ferramenta("[interno] O novo score do cliente é 467."),
            AIMessage(content="Seu novo score calculado é 780."),
        ]
        assert 780.0 in _detectar_numeros_inventados(novas, "", [], "entrevista")

    def test_numero_devolvido_pela_ferramenta_passa(self):
        novas = [
            self._ferramenta("[interno] Limite atual: R$ 15.000,00. Score: 467."),
            AIMessage(content="Seu limite é de R$ 15.000,00 e o score, 467."),
        ]
        assert _detectar_numeros_inventados(novas, "", [], "credito") == []

    def test_numero_dito_pelo_proprio_cliente_passa(self):
        historico = [HumanMessage(content="quero aumentar para 10 mil")]
        novas = [AIMessage(content="Registrei seu pedido de 10 mil.")]
        assert _detectar_numeros_inventados(novas, "", historico, "credito") == []

    def test_numero_do_prompt_passa(self):
        """"restam 2 tentativas" vem do bloco de contexto, não de ferramenta alguma."""
        prompt = "CONTEXTO: Tentativas usadas: 1 de 3 (restam 2)."
        novas = [AIMessage(content="Você ainda tem 2 tentativas.")]
        assert _detectar_numeros_inventados(novas, prompt, [], "triagem") == []


class TestPerguntasNaoFeitas:
    """A entrevista pulou a 5ª pergunta e preencheu `não` sozinha — 200 pontos de score."""

    def _janela(self, *perguntas: str) -> dict:
        return {
            "entrevista_inicio": 0,
            "messages": [m for p in perguntas for m in (AIMessage(content=p),)],
        }

    def test_acusa_o_campo_nunca_perguntado(self):
        estado = self._janela(
            "Qual a sua renda mensal?",
            "Você é formal, autônomo ou desempregado?",
            "Quais são suas despesas fixas?",
            "Quantos dependentes você possui?",
        )
        assert _perguntas_nao_feitas(estado) == ["tem_dividas"]

    def test_roteiro_completo_nao_acusa(self):
        estado = self._janela(
            "Qual a sua renda mensal?",
            "Qual o seu tipo de emprego?",
            "Quanto somam suas despesas fixas?",
            "Quantos dependentes você possui?",
            "Você possui dívidas ativas?",
        )
        assert _perguntas_nao_feitas(estado) == []

    def test_cliente_que_se_antecipa_nao_e_bloqueado(self):
        """Responder tudo de uma vez é legítimo; exigir 5 perguntas seria obtuso."""
        estado = {
            "entrevista_inicio": 0,
            "messages": [
                AIMessage(content="Qual é a sua renda mensal?"),
                HumanMessage(
                    content="4200, autônomo, 1200 de despesas, sem dependentes "
                    "e sem dívidas"
                ),
            ],
        }
        assert _perguntas_nao_feitas(estado) == []

    def test_a_aceitacao_da_entrevista_fica_fora_da_janela(self):
        """O "sim" que aceita a oferta não pode valer como resposta sobre dívidas."""
        estado = {
            "entrevista_inicio": 2,
            "messages": [
                AIMessage(content="Deseja fazer a entrevista? Ela recalcula seu score."),
                HumanMessage(content="sim"),
                AIMessage(content="Qual a sua renda mensal?"),
            ],
        }
        assert "tem_dividas" in _perguntas_nao_feitas(estado)

    def test_handler_recusa_e_nao_toca_no_score(self, servicos, cliente_repo):
        antes = cliente_repo.buscar_por_cpf(CPF_ANA).score
        estado = {
            "cliente": cliente_repo.buscar_por_cpf(CPF_ANA).model_dump(mode="json"),
            **self._janela(
                "Qual a sua renda?", "Tipo de emprego?", "Despesas fixas?",
                "Quantos dependentes?",
            ),
        }

        conteudo, efeitos = _handler_registrar(
            {
                "renda_mensal": "15000", "tipo_emprego": "autonomo",
                "despesas_fixas": "5200", "num_dependentes": 1, "tem_dividas": "nao",
            },
            estado,
        )

        assert "tem_dividas" in conteudo
        assert efeitos == {}
        assert cliente_repo.buscar_por_cpf(CPF_ANA).score == antes

    def test_handler_registra_quando_tudo_foi_perguntado(self, servicos, cliente_repo):
        estado = {
            "cliente": cliente_repo.buscar_por_cpf(CPF_ANA).model_dump(mode="json"),
            **self._janela(
                "Qual a sua renda?", "Tipo de emprego?", "Despesas fixas?",
                "Quantos dependentes?", "Possui dívidas ativas?",
            ),
        }

        conteudo, efeitos = _handler_registrar(
            {
                "renda_mensal": "15000", "tipo_emprego": "autonomo",
                "despesas_fixas": "5200", "num_dependentes": 1, "tem_dividas": "nao",
            },
            estado,
        )

        # O número vai imperativo e sozinho: a versão anterior soltava "540 -> 467" e o
        # modelo chamou o score novo de "anterior".
        assert "467" in conteudo
        assert cliente_repo.buscar_por_cpf(CPF_ANA).score == 467
        assert efeitos["current_agent"] == "credito"


class TestTetoGlobal:
    """Oferecer entrevista para R$ 1 bilhão é prometer um caminho que não existe."""

    def test_teto_maximo_e_o_maior_da_politica(self, faixa_repo):
        assert faixa_repo.teto_maximo() == 50_000.0

    def test_pedido_acima_de_todas_as_faixas(self, servicos, cliente_repo):
        diego = cliente_repo.buscar_por_cpf("22255588846")
        resultado = servicos.credito.solicitar_aumento(diego, 1_000_000_000.0)

        assert resultado.status is StatusPedido.REJEITADO
        assert resultado.acima_do_teto_global is True

    def test_pedido_alcancavel_por_outra_faixa_nao_marca(self, servicos, cliente_repo):
        """R$ 20.000 é inalcançável para o score do Diego, mas existe na política."""
        diego = cliente_repo.buscar_por_cpf("22255588846")
        resultado = servicos.credito.solicitar_aumento(diego, 20_000.0)

        assert resultado.status is StatusPedido.REJEITADO
        assert resultado.acima_do_teto_global is False

    def test_handler_nao_oferece_entrevista_para_valor_inalcancavel(
        self, servicos, cliente_repo
    ):
        from src.agents.credito import _handler_solicitar_aumento

        diego: Cliente = cliente_repo.buscar_por_cpf("22255588846")
        conteudo, efeitos = _handler_solicitar_aumento(
            {"novo_limite": 1_000_000_000.0},
            {"cliente": diego.model_dump(mode="json")},
        )

        assert "NÃO ofereça a entrevista" in conteudo
        assert "entrevista_oferecida" not in efeitos

    def test_handler_oferece_entrevista_para_valor_alcancavel(self, servicos, cliente_repo):
        from src.agents.credito import _handler_solicitar_aumento

        diego: Cliente = cliente_repo.buscar_por_cpf("22255588846")
        conteudo, efeitos = _handler_solicitar_aumento(
            {"novo_limite": 20_000.0},
            {"cliente": diego.model_dump(mode="json")},
        )

        assert "entrevista financeira" in conteudo
        assert efeitos["entrevista_oferecida"] is True


class TestMotorPublicaOSinal:
    """A guarda só serve se o resultado chegar ao painel de diagnóstico."""

    def test_turno_registra_numeros_inventados(self, monkeypatch, servicos):
        from src.agents.base import run_agent_turn
        from tests.fakes import FakeChatModel

        fake = FakeChatModel([fala("Seu score é 780.")])
        monkeypatch.setattr("src.agents.base.get_chat_model", lambda: fake)

        updates, _ = run_agent_turn({"messages": []}, "credito", "PROMPT", [], {})

        assert updates["numeros_inventados"] == [780.0]

    def test_turno_limpo_nao_acusa(self, monkeypatch, servicos):
        from src.agents.base import run_agent_turn
        from tests.fakes import FakeChatModel

        fake = FakeChatModel([fala("Posso ajudar com seu limite?")])
        monkeypatch.setattr("src.agents.base.get_chat_model", lambda: fake)

        updates, _ = run_agent_turn({"messages": []}, "credito", "PROMPT", [], {})

        assert updates["numeros_inventados"] == []


class TestEntrevistaTemSaida:
    """A entrevista era um beco sem saída — e o modelo improvisava para escapar.

    Numa sessão real o cliente pediu cotação no meio da entrevista. O agente não tinha
    ferramenta de câmbio nem rota de saída, então afirmou ter cotação de iene e yuan e
    inventou "R$ 0,037 por iene". A guarda de procedência acusou o número, mas a causa era
    a falta de rota: sem ferramenta, o modelo preenche a lacuna com texto.
    """

    def test_entrevista_alcanca_cambio_e_credito(self):
        from src.agents import entrevista

        nomes = {t.name for t in entrevista.TOOLS}
        assert {"atender_cambio", "atender_credito"} <= nomes

    def test_todo_agente_tem_ao_menos_uma_saida(self):
        """Nenhum agente pode prender o cliente: ou encaminha, ou encerra."""
        from src.agents import cambio, credito, entrevista, triagem

        saidas = {"atender_credito", "atender_cambio", "iniciar_entrevista",
                  "encerrar_atendimento"}
        for nome, mod in (("triagem", triagem), ("entrevista", entrevista)):
            assert {t.name for t in mod.TOOLS} & saidas, nome
        for nome, mod in (("credito", credito), ("cambio", cambio)):
            assert {t.name for t in mod.TOOLS_BASE} & saidas, nome

    def test_iniciar_entrevista_zera_a_janela(self, servicos):
        """Voltar para uma segunda entrevista não pode herdar a janela da primeira."""
        from src.agents.credito import _handler_iniciar_entrevista

        _conteudo, efeitos = _handler_iniciar_entrevista({}, {"entrevista_inicio": 7})

        assert efeitos["entrevista_inicio"] is None
        assert efeitos["current_agent"] == "entrevista"


class TestHonestidadeSobreOEscopo:
    """O prompt promete que crédito não registra dado financeiro. Isso precisa ser verdade.

    O agente respondeu "Compreendi sua renda" a um cliente que informou renda fora da
    entrevista — sem ter registrado coisa alguma. A instrução que corrige isso ("aqui você
    NÃO tem como registrar") vira mentira no dia em que alguém adicionar a ferramenta e
    esquecer do prompt. Este teste é o alarme para esse dia.
    """

    FERRAMENTAS_DE_ESCRITA_FINANCEIRA: ClassVar[set[str]] = {
        "registrar_entrevista", "atualizar_score",
    }

    def test_credito_nao_registra_dados_da_entrevista(self, monkeypatch):
        from src.agents import credito

        monkeypatch.setattr(
            "src.agents.credito.get_settings",
            lambda: __import__(
                "src.core.config", fromlist=["Settings"]
            ).Settings(GOOGLE_API_KEY="", POSTGRES_URL=""),
        )
        nomes = {t.name for t in credito.tools()}

        assert not (nomes & self.FERRAMENTAS_DE_ESCRITA_FINANCEIRA)
        assert "iniciar_entrevista" in nomes  # o caminho honesto existe

    def test_so_a_entrevista_escreve_score(self):
        from src.agents import cambio, entrevista, triagem

        assert "registrar_entrevista" in {t.name for t in entrevista.TOOLS}
        for ferramentas in (triagem.TOOLS, cambio.TOOLS_BASE):
            nomes = {t.name for t in ferramentas}
            assert not (nomes & self.FERRAMENTAS_DE_ESCRITA_FINANCEIRA)


def test_chama_disponivel_para_roteiros():
    """Guarda de import: o módulo de fakes é o alicerce de todos os testes de agente."""
    assert chama("x").tool_calls
