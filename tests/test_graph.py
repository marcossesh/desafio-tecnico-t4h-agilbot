"""Orquestração completa, com LLM falso — nenhuma chamada externa.

Cobre os fluxos que o enunciado descreve de ponta a ponta, inclusive o handoff invisível
e a memória entre turnos, que é a propriedade mais frágil do desenho.
"""
from __future__ import annotations

import re

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from src.core.constants import MAX_TENTATIVAS_AUTH, REGEX_VAZAMENTO
from src.core.utils import texto_da_mensagem
from src.orchestration.graph import compile_graph
from src.orchestration.state import estado_inicial
from tests.conftest import CPF_ANA, CPF_DIEGO
from tests.fakes import FakeChatModel, chama, fala


@pytest.fixture
def conversa(monkeypatch, servicos):
    """Roda turnos contra o grafo, com o roteiro do LLM controlado por turno.

    Usa checkpointer e envia apenas o delta, exatamente como a UI: reenviar o estado
    inteiro substituiria a lista de mensagens e o teste passaria a exercitar um fluxo
    que a aplicação não executa.
    """
    grafo = compile_graph(MemorySaver())

    class Sessao:
        def __init__(self) -> None:
            self.config = {"configurable": {"thread_id": "teste"}}
            self.estado: dict = {}
            self.modelos: list[FakeChatModel] = []

        def turno(self, mensagem: str, *respostas: AIMessage) -> dict:
            fake = FakeChatModel(list(respostas))
            self.modelos.append(fake)
            monkeypatch.setattr("src.agents.base.get_chat_model", lambda: fake)

            delta = {"messages": [HumanMessage(content=mensagem)]}
            entrada = delta if self.estado else {**estado_inicial(), **delta}
            self.estado = grafo.invoke(entrada, config=self.config)
            return self.estado

        @property
        def falas(self) -> list[str]:
            return [
                texto for m in self.estado["messages"]
                if isinstance(m, AIMessage) and (texto := texto_da_mensagem(m.content))
            ]

        @property
        def ultima_fala(self) -> str:
            return self.falas[-1] if self.falas else ""

    return Sessao()


class TestAutenticacao:
    def test_cpf_num_turno_e_data_no_seguinte(self, conversa):
        """A asserção que protege o desenho: o CPF coletado no turno 1 continua
        disponível no turno 2, mesmo com o histórico sanitizado."""
        conversa.turno(
            "Oi, meu CPF é 111.444.777-35",
            chama("verificar_cpf", cpf="111.444.777-35"),
            fala("Certo! Qual é a sua data de nascimento?"),
        )
        assert conversa.estado["cpf_informado"] == CPF_ANA

        # O modelo autentica sem que o cliente repita o CPF — ele vem do contexto.
        conversa.turno(
            "14/05/1990",
            chama("autenticar_cliente", cpf=CPF_ANA, data_nascimento="14/05/1990"),
            fala("Olá, Ana! Em que posso ajudar?"),
        )

        assert conversa.estado["authenticated"] is True
        assert conversa.estado["cliente"]["nome"] == "Ana Souza"

    def test_cpf_no_contexto_do_segundo_turno(self, conversa):
        conversa.turno("meu CPF é 111.444.777-35", chama("verificar_cpf", cpf=CPF_ANA),
                       fala("Qual sua data de nascimento?"))
        conversa.turno("14/05/1990", fala("Só um instante."))

        prompt = conversa.modelos[-1].prompt_da_chamada(0)
        assert "111.444.777-35" in prompt

    def test_cpf_invalido_nao_consome_tentativa(self, conversa):
        conversa.turno(
            "CPF 111.444.777-00",
            chama("verificar_cpf", cpf="11144477700"),
            fala("Esse CPF não é válido. Pode conferir?"),
        )

        assert conversa.estado["auth_attempts"] == 0
        assert conversa.estado["cpf_informado"] == ""

    def test_tres_falhas_encerram_com_cordialidade(self, conversa):
        for i in range(MAX_TENTATIVAS_AUTH):
            conversa.turno(
                f"tentativa {i}",
                chama("autenticar_cliente", cpf=CPF_ANA, data_nascimento="01/01/1900"),
                fala("Não consegui confirmar seus dados."),
            )

        assert conversa.estado["auth_attempts"] == MAX_TENTATIVAS_AUTH
        assert conversa.estado["finished"] is True

    def test_quarta_tentativa_e_recusada_pelo_handler(self, conversa):
        """A guarda vive no handler, não no prompt: mesmo que o modelo insista, não passa."""
        for _ in range(MAX_TENTATIVAS_AUTH):
            conversa.turno("x", chama("autenticar_cliente", cpf=CPF_ANA,
                                      data_nascimento="01/01/1900"), fala("Não confere."))

        conversa.turno(
            "tenta de novo",
            chama("autenticar_cliente", cpf=CPF_ANA, data_nascimento="14/05/1990"),
            fala("Sinto muito, não posso continuar."),
        )
        assert conversa.estado["authenticated"] is False

    def test_direcionamento_bloqueado_sem_autenticacao(self, conversa):
        conversa.turno(
            "quero aumentar meu limite",
            chama("atender_credito"),
            fala("Antes preciso confirmar seus dados. Qual seu CPF?"),
        )

        assert conversa.estado["current_agent"] == "triagem"
        assert conversa.estado["authenticated"] is False


class TestHandoffInvisivel:
    def test_transicao_para_credito_no_mesmo_turno(self, conversa, cliente_repo):
        _autenticar(conversa, CPF_ANA, "14/05/1990")

        conversa.turno(
            "queria saber meu limite",
            chama("atender_credito"),          # triagem entrega...
            chama("consultar_limite"),          # ...e o crédito já responde
            fala("Seu limite atual é de R$ 5.000,00."),
        )

        assert conversa.estado["current_agent"] == "credito"
        assert "R$ 5.000,00" in conversa.ultima_fala

    def test_cliente_nunca_ve_mencao_a_transferencia(self, conversa):
        _autenticar(conversa, CPF_ANA, "14/05/1990")
        conversa.turno("quero ver meu limite", chama("atender_credito"),
                       chama("consultar_limite"), fala("Seu limite é R$ 5.000,00."))

        padrao = re.compile(REGEX_VAZAMENTO, re.IGNORECASE)
        for texto in conversa.falas:
            assert not padrao.search(texto), f"vazou transição: {texto!r}"
        assert conversa.estado["vazamento_detectado"] is False


class TestFluxoVitrineNoGrafo:
    def test_rejeitado_entrevista_reavaliacao_aprovada(
        self, conversa, cliente_repo, solicitacao_repo
    ):
        _autenticar(conversa, CPF_DIEGO, "19/07/1995")

        # Pedido rejeitado, com oferta de entrevista.
        conversa.turno(
            "quero aumentar meu limite para 10 mil",
            chama("atender_credito"),
            chama("solicitar_aumento", novo_limite=10000),
            fala("Infelizmente não foi possível. Posso fazer algumas perguntas rápidas?"),
        )
        assert conversa.estado["ultima_solicitacao"]["status"] == "rejeitado"
        assert conversa.estado["entrevista_oferecida"] is True

        # Entrevista: o cliente revela a renda atual (o cadastro estava desatualizado).
        conversa.turno(
            "pode perguntar",
            chama("iniciar_entrevista"),
            fala("Qual é a sua renda mensal hoje?"),
        )
        assert conversa.estado["current_agent"] == "entrevista"

        conversa.turno(
            "4200, autônomo, 1200 de despesas, sem dependentes e sem dívidas",
            chama(
                "registrar_entrevista", renda_mensal="4200", tipo_emprego="autônomo",
                despesas_fixas="1200", num_dependentes=0, tem_dividas="não",
            ),
            fala("Boa notícia: seu limite de R$ 10.000,00 foi aprovado!"),
        )

        # O score subiu e a reavaliação aconteceu sozinha, de volta no crédito.
        assert cliente_repo.buscar_por_cpf(CPF_DIEGO).score == 505
        assert conversa.estado["current_agent"] == "credito"
        assert conversa.estado["ultima_solicitacao"]["status"] == "aprovado"
        assert cliente_repo.buscar_por_cpf(CPF_DIEGO).limite_atual == 10000.0

        # Trilha de auditoria: o pedido rejeitado permanece, o novo é outra linha.
        linhas = solicitacao_repo.listar()
        assert [linha["status_pedido"] for linha in linhas] == ["rejeitado", "aprovado"]

    def test_reavaliacao_nao_dispara_sem_mudanca_de_score(self, conversa, solicitacao_repo):
        _autenticar(conversa, CPF_DIEGO, "19/07/1995")
        conversa.turno("aumenta para 10 mil", chama("atender_credito"),
                       chama("solicitar_aumento", novo_limite=10000), fala("Não deu certo."))

        conversa.turno("entendi, obrigado", fala("Posso ajudar em algo mais?"))

        assert len(solicitacao_repo.listar()) == 1


class TestCambioEEncerramento:
    def test_cotacao_usa_a_moeda_pedida(self, conversa, requests_mock):
        requests_mock.get(
            "https://economia.awesomeapi.com.br/json/last/EUR-BRL",
            json={"EURBRL": {"bid": "5.85", "pctChange": "0.1", "create_date": "hoje"}},
        )
        _autenticar(conversa, CPF_ANA, "14/05/1990")

        conversa.turno(
            "quanto está o euro?",
            chama("atender_cambio"),
            chama("consultar_cotacao", moeda="EUR"),
            fala("O euro está cotado a R$ 5,85."),
        )

        assert conversa.estado["current_agent"] == "cambio"
        assert "euro" in conversa.ultima_fala.lower()

    def test_encerramento_marca_a_sessao(self, conversa):
        _autenticar(conversa, CPF_ANA, "14/05/1990")
        conversa.turno("era só isso, obrigado",
                       chama("encerrar_atendimento"), fala("Foi um prazer! Até logo."))

        assert conversa.estado["finished"] is True


def _autenticar(conversa, cpf: str, nascimento: str) -> None:
    conversa.turno(
        f"oi, meu CPF é {cpf}",
        chama("verificar_cpf", cpf=cpf),
        fala("Qual sua data de nascimento?"),
    )
    conversa.turno(
        nascimento,
        chama("autenticar_cliente", cpf=cpf, data_nascimento=nascimento),
        fala("Olá! Em que posso ajudar?"),
    )


class TestCicloDeVida:
    """`finished` precisa ser barreira de domínio, não `disabled` do widget de chat."""

    def _encerrar(self, conversa) -> None:
        _autenticar(conversa, CPF_ANA, "14/05/1990")
        conversa.turno("era só isso, obrigado",
                       chama("encerrar_atendimento"), fala("Foi um prazer! Até logo."))
        assert conversa.estado["finished"] is True

    def test_atendimento_encerrado_nao_executa_operacao_de_credito(
        self, conversa, solicitacao_repo, cliente_repo
    ):
        self._encerrar(conversa)
        limite_antes = cliente_repo.buscar_por_cpf(CPF_ANA).limite_atual

        conversa.turno(
            "quero aumentar meu limite para 9 mil",
            chama("atender_credito"),
            chama("solicitar_aumento", novo_limite=9000),
            fala("aprovado!"),
        )

        assert solicitacao_repo.listar() == [], "nenhum pedido pode ser gravado após encerrar"
        assert cliente_repo.buscar_por_cpf(CPF_ANA).limite_atual == limite_antes

    def test_encerrado_responde_sem_chamar_o_llm(self, conversa):
        self._encerrar(conversa)
        antes = len(conversa.modelos)

        conversa.turno("oi de novo?")

        assert "encerrado" in conversa.ultima_fala.lower()
        # O nó-sentinela é determinístico: não consome cota nem depende do provedor.
        assert conversa.modelos[antes].chamadas == []

    def test_encerramento_por_excesso_de_tentativas_tambem_barra(
        self, conversa, solicitacao_repo
    ):
        for _ in range(MAX_TENTATIVAS_AUTH):
            conversa.turno("tentativa", chama("autenticar_cliente", cpf=CPF_ANA,
                                              data_nascimento="01/01/1900"), fala("não confere"))
        assert conversa.estado["finished"] is True

        conversa.turno("me dá um aumento", chama("atender_credito"),
                       chama("solicitar_aumento", novo_limite=9000), fala("ok"))

        assert solicitacao_repo.listar() == []
