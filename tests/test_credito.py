"""Crédito, entrevista e o fluxo-vitrine — tudo determinístico, sem LLM."""
from __future__ import annotations

import csv
from pathlib import Path

from src.core.constants import HEADER_SOLICITACOES
from src.domain.enums import StatusPedido
from src.repositories.solicitacoes import SolicitacaoRepository
from src.services.credito_service import CreditoService
from src.services.entrevista_service import EntrevistaService
from tests.conftest import CPF_ANA, CPF_BRUNO, CPF_DIEGO


def _servico(cliente_repo, faixa_repo, solicitacao_repo) -> CreditoService:
    return CreditoService(faixa_repo, solicitacao_repo, cliente_repo)


class TestConsultaDeLimite:
    def test_traz_limite_score_teto_e_taxa(self, cliente_repo, faixa_repo, solicitacao_repo):
        cliente = cliente_repo.buscar_por_cpf(CPF_ANA)
        resumo = _servico(cliente_repo, faixa_repo, solicitacao_repo).consultar_limite(cliente)

        assert resumo.ok
        assert resumo.limite_atual == 5000.0
        assert resumo.score == 540
        assert resumo.limite_maximo == 15000.0
        assert resumo.taxa_juros_mensal == 0.0599

    def test_politica_ilegivel_vira_mensagem_controlada(
        self, cliente_repo, solicitacao_repo, tmp_path: Path
    ):
        from src.repositories.score_limite import FaixaScoreRepository

        vazio = FaixaScoreRepository(tmp_path / "nao_existe.csv")
        cliente = cliente_repo.buscar_por_cpf(CPF_ANA)
        resumo = CreditoService(vazio, solicitacao_repo, cliente_repo).consultar_limite(cliente)

        assert not resumo.ok
        assert "política de crédito" in resumo.mensagem


class TestSolicitacaoDeAumento:
    def test_aprovacao_persiste_o_novo_limite(self, cliente_repo, faixa_repo, solicitacao_repo):
        servico = _servico(cliente_repo, faixa_repo, solicitacao_repo)
        cliente = cliente_repo.buscar_por_cpf(CPF_ANA)  # score 540 -> teto 15.000

        resultado = servico.solicitar_aumento(cliente, 10000)

        assert resultado.status is StatusPedido.APROVADO
        assert cliente_repo.buscar_por_cpf(CPF_ANA).limite_atual == 10000.0
        assert "5,99%" in resultado.mensagem  # a taxa da faixa é informada ao cliente

    def test_rejeicao_nao_altera_o_limite(self, cliente_repo, faixa_repo, solicitacao_repo):
        servico = _servico(cliente_repo, faixa_repo, solicitacao_repo)
        cliente = cliente_repo.buscar_por_cpf(CPF_DIEGO)  # score 380 -> teto 5.000

        resultado = servico.solicitar_aumento(cliente, 10000)

        assert resultado.status is StatusPedido.REJEITADO
        assert cliente_repo.buscar_por_cpf(CPF_DIEGO).limite_atual == 800.0

    def test_valor_menor_que_o_atual_nao_gera_pedido(
        self, cliente_repo, faixa_repo, solicitacao_repo
    ):
        servico = _servico(cliente_repo, faixa_repo, solicitacao_repo)
        cliente = cliente_repo.buscar_por_cpf(CPF_ANA)

        resultado = servico.solicitar_aumento(cliente, 1000)

        assert resultado.status is StatusPedido.INVALIDO
        assert solicitacao_repo.listar() == []  # nada registrado

    def test_pedido_nasce_pendente_e_transiciona_na_mesma_linha(
        self, cliente_repo, faixa_repo, solicitacao_repo
    ):
        servico = _servico(cliente_repo, faixa_repo, solicitacao_repo)
        cliente = cliente_repo.buscar_por_cpf(CPF_BRUNO)  # score 280 -> teto 1.000

        resultado = servico.solicitar_aumento(cliente, 900)

        linhas = solicitacao_repo.listar()
        assert len(linhas) == 1, "a transição reescreve a linha, não acrescenta outra"
        assert linhas[0]["status_pedido"] == StatusPedido.APROVADO.value
        assert resultado.linha_idx == 0

    def test_csv_tem_exatamente_as_cinco_colunas_do_enunciado(
        self, cliente_repo, faixa_repo, solicitacao_repo
    ):
        servico = _servico(cliente_repo, faixa_repo, solicitacao_repo)
        servico.solicitar_aumento(cliente_repo.buscar_por_cpf(CPF_DIEGO), 10000)

        with solicitacao_repo.csv.path.open(encoding="utf-8") as f:
            linhas = list(csv.reader(f))

        assert linhas[0] == HEADER_SOLICITACOES
        assert len(linhas[1]) == 5

    def test_falha_ao_registrar_nao_derruba_o_atendimento(
        self, cliente_repo, faixa_repo, tmp_path: Path, monkeypatch
    ):
        repo = SolicitacaoRepository(tmp_path / "sub" / "s.csv")
        monkeypatch.setattr(
            repo, "registrar", lambda _s: (_ for _ in ()).throw(_erro_repositorio())
        )
        servico = CreditoService(faixa_repo, repo, cliente_repo)

        resultado = servico.solicitar_aumento(cliente_repo.buscar_por_cpf(CPF_ANA), 10000)

        assert resultado.status is StatusPedido.ERRO
        assert "Tente em instantes" in resultado.mensagem


def _erro_repositorio():
    from src.repositories.base import RepositoryError

    return RepositoryError("falha simulada")


class TestHistoricoDeScore:
    """Sem esta trilha, o score que produziu cada decisão não sobreviveria em dado
    nenhum: `clientes.csv` guarda só o vigente e o CSV de pedidos tem as 5 colunas."""

    def test_arquivo_ausente_lista_vazio(self, historico_repo):
        assert historico_repo.listar() == []

    def test_entrevista_registra_a_mudanca(self, cliente_repo, historico_repo):
        cliente = cliente_repo.buscar_por_cpf(CPF_DIEGO)
        EntrevistaService(cliente_repo, historico_repo).registrar(
            cliente, renda_mensal=4200, tipo_emprego="autônomo", despesas_fixas=1200,
            num_dependentes=0, tem_dividas="não",
        )

        linhas = historico_repo.do_cliente(CPF_DIEGO)
        assert len(linhas) == 1
        assert linhas[0]["score_anterior"] == "380"
        assert linhas[0]["score_novo"] == "505"
        assert linhas[0]["origem"] == "entrevista"
        assert "T" in linhas[0]["data_hora"]  # ISO 8601

    def test_entrevista_invalida_nao_registra(self, cliente_repo, historico_repo):
        cliente = cliente_repo.buscar_por_cpf(CPF_DIEGO)
        EntrevistaService(cliente_repo, historico_repo).registrar(
            cliente, renda_mensal="abacaxi", tipo_emprego="autônomo",
            despesas_fixas=1200, num_dependentes=0, tem_dividas="não",
        )
        assert historico_repo.listar() == []

    def test_falha_ao_gravar_historico_nao_invalida_o_score(
        self, cliente_repo, historico_repo, monkeypatch
    ):
        """Mesmo princípio do resto do sistema: a trilha é importante, mas não pode
        derrubar a operação que ela apenas documenta."""
        monkeypatch.setattr(
            historico_repo, "registrar",
            lambda _r: (_ for _ in ()).throw(_erro_repositorio()),
        )
        cliente = cliente_repo.buscar_por_cpf(CPF_DIEGO)

        resultado = EntrevistaService(cliente_repo, historico_repo).registrar(
            cliente, renda_mensal=4200, tipo_emprego="autônomo", despesas_fixas=1200,
            num_dependentes=0, tem_dividas="não",
        )

        assert resultado.ok
        assert cliente_repo.buscar_por_cpf(CPF_DIEGO).score == 505

    def test_decisao_de_credito_e_reconstruivel(
        self, cliente_repo, faixa_repo, solicitacao_repo, historico_repo
    ):
        """O objetivo da trilha: cruzando os dois CSVs por timestamp, dá para explicar
        por que o primeiro pedido foi rejeitado e o segundo, idêntico, aprovado."""
        credito = CreditoService(faixa_repo, solicitacao_repo, cliente_repo)
        diego = cliente_repo.buscar_por_cpf(CPF_DIEGO)

        credito.solicitar_aumento(diego, 10000)
        EntrevistaService(cliente_repo, historico_repo).registrar(
            diego, renda_mensal=4200, tipo_emprego="autônomo", despesas_fixas=1200,
            num_dependentes=0, tem_dividas="não",
        )
        credito.solicitar_aumento(cliente_repo.buscar_por_cpf(CPF_DIEGO), 10000)

        pedidos = solicitacao_repo.listar()
        mudanca = historico_repo.do_cliente(CPF_DIEGO)[0]

        assert [p["status_pedido"] for p in pedidos] == ["rejeitado", "aprovado"]
        # O recálculo acontece entre os dois pedidos — é o que explica a virada.
        assert pedidos[0]["data_hora_solicitacao"] < mudanca["data_hora"]
        assert mudanca["data_hora"] < pedidos[1]["data_hora_solicitacao"]
        assert int(mudanca["score_anterior"]) < int(mudanca["score_novo"])


class TestEntrevista:
    def test_recalcula_e_persiste_o_score(self, cliente_repo, historico_repo):
        cliente = cliente_repo.buscar_por_cpf(CPF_DIEGO)
        resultado = EntrevistaService(cliente_repo, historico_repo).registrar(
            cliente,
            renda_mensal="4200", tipo_emprego="autônomo", despesas_fixas="1200",
            num_dependentes=0, tem_dividas="não",
        )

        assert resultado.ok
        assert resultado.score_anterior == 380
        assert resultado.score_novo == 505
        assert cliente_repo.buscar_por_cpf(CPF_DIEGO).score == 505

    def test_dado_invalido_devolve_o_campo_especifico(self, cliente_repo, historico_repo):
        """O agente precisa saber *qual* campo falhou para repergunta só aquele."""
        cliente = cliente_repo.buscar_por_cpf(CPF_DIEGO)
        resultado = EntrevistaService(cliente_repo, historico_repo).registrar(
            cliente,
            renda_mensal="quatro mil", tipo_emprego="autônomo", despesas_fixas="1200",
            num_dependentes=0, tem_dividas="não",
        )

        assert not resultado.ok
        assert "renda_mensal" in resultado.mensagem
        assert cliente_repo.buscar_por_cpf(CPF_DIEGO).score == 380  # inalterado

    def test_emprego_irreconhecivel_nao_persiste_nada(self, cliente_repo, historico_repo):
        cliente = cliente_repo.buscar_por_cpf(CPF_DIEGO)
        resultado = EntrevistaService(cliente_repo, historico_repo).registrar(
            cliente,
            renda_mensal=4200, tipo_emprego="abacaxi", despesas_fixas=1200,
            num_dependentes=0, tem_dividas=False,
        )

        assert not resultado.ok
        assert cliente_repo.buscar_por_cpf(CPF_DIEGO).score == 380


class TestFluxoVitrine:
    """Regressão do cenário central: rejeitado -> entrevista -> aprovado.

    É a demonstração principal da entrega. Sem este teste, um ajuste em `clientes.csv`
    ou em `score_limite.csv` quebraria o fluxo em silêncio.
    """

    def test_rejeitado_entrevista_aprovado(
        self, cliente_repo, faixa_repo, solicitacao_repo, historico_repo
    ):
        credito = CreditoService(faixa_repo, solicitacao_repo, cliente_repo)
        entrevista = EntrevistaService(cliente_repo, historico_repo)

        # 1) Diego (score 380, teto 5.000) pede 10.000 e é rejeitado.
        diego = cliente_repo.buscar_por_cpf(CPF_DIEGO)
        score_semeado = diego.score
        faixa_antes = faixa_repo.faixa_para(score_semeado)

        primeira = credito.solicitar_aumento(diego, 10000)
        assert primeira.status is StatusPedido.REJEITADO

        # 2) A entrevista revela a renda atual (o cadastro estava desatualizado).
        assert diego.renda_declarada == 2600.0, "o cadastro precisa estar desatualizado"
        recalculo = entrevista.registrar(
            diego,
            renda_mensal=4200, tipo_emprego="autônomo", despesas_fixas=1200,
            num_dependentes=0, tem_dividas="não",
        )
        assert recalculo.ok

        # O score sobe E cruza uma faixa — as duas asserções que sustentam a demo.
        assert recalculo.score_novo > score_semeado
        faixa_depois = faixa_repo.faixa_para(recalculo.score_novo)
        assert faixa_depois.score_min != faixa_antes.score_min
        assert faixa_depois.limite_maximo > faixa_antes.limite_maximo

        # 3) Reavaliação: pedido NOVO, o rejeitado permanece como trilha de auditoria.
        atualizado = cliente_repo.buscar_por_cpf(CPF_DIEGO)
        segunda = credito.solicitar_aumento(atualizado, 10000)
        assert segunda.status is StatusPedido.APROVADO
        assert cliente_repo.buscar_por_cpf(CPF_DIEGO).limite_atual == 10000.0

        linhas = solicitacao_repo.listar()
        assert len(linhas) == 2, "a reavaliação cria um pedido novo, não reescreve o antigo"
        assert linhas[0]["status_pedido"] == StatusPedido.REJEITADO.value
        assert linhas[1]["status_pedido"] == StatusPedido.APROVADO.value

    def test_gatilho_de_reavaliacao_e_computavel(
        self, cliente_repo, faixa_repo, solicitacao_repo, historico_repo
    ):
        """O nó de crédito reavalia quando o pedido foi rejeitado E o score mudou desde
        a avaliação. `score_avaliado` é o que torna essa condição verificável."""
        credito = CreditoService(faixa_repo, solicitacao_repo, cliente_repo)
        diego = cliente_repo.buscar_por_cpf(CPF_DIEGO)

        rejeitada = credito.solicitar_aumento(diego, 10000)
        assert rejeitada.score_avaliado == 380

        EntrevistaService(cliente_repo, historico_repo).registrar(
            diego, renda_mensal=4200, tipo_emprego="autônomo", despesas_fixas=1200,
            num_dependentes=0, tem_dividas=False,
        )
        atual = cliente_repo.buscar_por_cpf(CPF_DIEGO)

        deve_reavaliar = (
            rejeitada.status is StatusPedido.REJEITADO
            and atual.score != rejeitada.score_avaliado
        )
        assert deve_reavaliar is True
