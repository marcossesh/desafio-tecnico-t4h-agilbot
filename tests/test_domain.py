"""Normalização de entrada em linguagem natural e modelos do domínio."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.utils import (
    formatar_brl,
    formatar_cpf,
    formatar_percentual,
    normalizar,
    parse_valor_monetario,
    texto_da_mensagem,
)
from src.domain.enums import StatusPedido, TipoEmprego, texto_para_booleano
from src.domain.models import Cliente, DadosEntrevista, SolicitacaoAumento


class TestUtils:
    def test_normalizar_remove_acento_e_caixa(self):
        assert normalizar("  AutônoMO ") == "autonomo"

    def test_formatar_cpf(self):
        assert formatar_cpf("11144477735") == "111.444.777-35"
        assert formatar_cpf("123") == "123"  # inalterado quando não dá para formatar

    def test_formatar_brl_usa_padrao_brasileiro(self):
        assert formatar_brl(1234.5) == "R$ 1.234,50"
        assert formatar_brl(15000) == "R$ 15.000,00"

    def test_formatar_percentual(self):
        assert formatar_percentual(0.0599) == "5,99%"


class TestTextoDaMensagem:
    """Modelos novos devolvem blocos tipados em vez de string.

    Sem normalizar, o cliente veria o `repr` de uma lista de dicionários na tela — foi
    exatamente o que aconteceu no primeiro spike contra o Gemini 3.x.
    """

    def test_string_passa_direto(self):
        assert texto_da_mensagem("Olá!") == "Olá!"

    def test_blocos_tipados_viram_texto(self):
        content = [
            {"type": "text", "text": "Olá, Diego!", "extras": {"signature": "abc"}},
        ]
        assert texto_da_mensagem(content) == "Olá, Diego!"

    def test_concatena_multiplos_blocos_de_texto(self):
        content = [{"type": "text", "text": "Olá. "}, {"type": "text", "text": "Tudo bem?"}]
        assert texto_da_mensagem(content) == "Olá. Tudo bem?"

    def test_ignora_blocos_que_nao_sao_texto(self):
        content = [
            {"type": "thinking", "thinking": "raciocínio interno"},
            {"type": "text", "text": "Resposta."},
        ]
        assert texto_da_mensagem(content) == "Resposta."

    @pytest.mark.parametrize("vazio", [None, "", [], [{"type": "thinking"}]])
    def test_conteudo_sem_texto_e_falsy(self, vazio):
        assert not texto_da_mensagem(vazio)


class TestTipoEmprego:
    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("formal", TipoEmprego.FORMAL),
            ("CLT", TipoEmprego.FORMAL),
            ("carteira assinada", TipoEmprego.FORMAL),
            ("autônomo", TipoEmprego.AUTONOMO),
            ("autonomo", TipoEmprego.AUTONOMO),
            ("PJ", TipoEmprego.AUTONOMO),
            ("sou empresário", TipoEmprego.AUTONOMO),
            ("trabalho por conta própria", TipoEmprego.AUTONOMO),
            ("desempregado", TipoEmprego.DESEMPREGADO),
            ("estou sem emprego", TipoEmprego.DESEMPREGADO),
        ],
    )
    def test_mapeia_texto_livre(self, texto: str, esperado: TipoEmprego):
        assert TipoEmprego.from_texto(texto) == esperado

    def test_desempregado_nao_e_confundido_com_formal(self):
        # "desempregado" contém "empregado"; a ordem de avaliação precisa proteger isso.
        assert TipoEmprego.from_texto("desempregado") == TipoEmprego.DESEMPREGADO

    def test_texto_irreconhecivel_levanta(self):
        with pytest.raises(ValueError, match="não reconhecido"):
            TipoEmprego.from_texto("abacaxi")


class TestBooleano:
    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("sim", True), ("Sim, tenho", True), ("tenho dívidas", True), ("s", True),
            ("não", False), ("nao", False), ("Não tenho dívidas", False), ("n", False),
            ("nenhuma", False),
        ],
    )
    def test_interpreta_sim_e_nao(self, texto: str, esperado: bool):
        assert texto_para_booleano(texto) is esperado

    def test_ambiguo_levanta(self):
        with pytest.raises(ValueError, match="não entendi"):
            texto_para_booleano("talvez")


class TestDadosEntrevista:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("4200", 4200.0),
            ("R$ 4.200", 4200.0),      # ponto + 3 dígitos = separador de milhar em pt-BR
            ("4.200,50", 4200.50),
            ("4200.50", 4200.50),      # ponto decimal também é aceito
            ("1.234.567", 1234567.0),
            (3500, 3500.0),
            # Abreviações: o cliente fala assim, e a conversão precisa ser determinística
            # em vez de depender de o LLM interpretar certo.
            ("10 mil", 10_000.0),
            ("10k", 10_000.0),
            ("10 mil reais", 10_000.0),
            ("R$ 4 mil", 4_000.0),
            ("1,5 milhão", 1_500_000.0),
            ("2 mi", 2_000_000.0),
        ],
    )
    def test_aceita_valor_monetario_em_varios_formatos(self, entrada, esperado):
        dados = DadosEntrevista(
            renda_mensal=entrada, tipo_emprego="formal", despesas_fixas=0,
            num_dependentes=0, tem_dividas="não",
        )
        assert dados.renda_mensal == pytest.approx(esperado)

    def test_valor_invalido_levanta(self):
        with pytest.raises(ValidationError):
            DadosEntrevista(
                renda_mensal="muito", tipo_emprego="formal", despesas_fixas=0,
                num_dependentes=0, tem_dividas=False,
            )

    def test_dependentes_negativo_rejeitado(self):
        with pytest.raises(ValidationError):
            DadosEntrevista(
                renda_mensal=1000, tipo_emprego="formal", despesas_fixas=0,
                num_dependentes=-1, tem_dividas=False,
            )


class TestModelos:
    def test_cliente_normaliza_cpf_e_expoe_primeiro_nome(self):
        cliente = Cliente(
            cpf="111.444.777-35", nome="Ana Souza Lima", data_nascimento="1990-05-14"
        )
        assert cliente.cpf == "11144477735"
        assert cliente.primeiro_nome == "Ana"
        assert cliente.cpf_formatado == "111.444.777-35"
        assert cliente.conta_ativa is True

    def test_conta_bloqueada_nao_e_ativa(self):
        cliente = Cliente(
            cpf="98765432100", nome="Felipe", data_nascimento="1988-09-08",
            status_conta="bloqueada",
        )
        assert cliente.conta_ativa is False

    def test_solicitacao_serializa_exatamente_as_cinco_colunas(self):
        linha = SolicitacaoAumento(
            cpf_cliente="22255588846", limite_atual=800, novo_limite_solicitado=10000
        ).para_csv()
        assert list(linha) == [
            "cpf_cliente", "data_hora_solicitacao", "limite_atual",
            "novo_limite_solicitado", "status_pedido",
        ]
        assert linha["status_pedido"] == "pendente"
        assert "T" in linha["data_hora_solicitacao"]  # ISO 8601

    def test_timestamp_tem_microssegundos(self):
        # Sem chave primária no CSV, dois pedidos no mesmo segundo precisam se distinguir.
        a = SolicitacaoAumento(cpf_cliente="1", limite_atual=1, novo_limite_solicitado=2)
        b = SolicitacaoAumento(cpf_cliente="1", limite_atual=1, novo_limite_solicitado=2)
        assert a.data_hora_solicitacao.microsecond or b.data_hora_solicitacao.microsecond

    def test_status_terminal(self):
        assert StatusPedido.APROVADO.e_terminal
        assert StatusPedido.REJEITADO.e_terminal
        assert not StatusPedido.PENDENTE.e_terminal


class TestValoresHostis:
    """Entradas que o `float()` aceita e o resto do sistema não sobrevive."""

    @pytest.mark.parametrize("v", ["inf", "-inf", "Infinity", "1e999", "-1e999"])
    def test_valor_nao_finito_e_rejeitado(self, v):
        """Um infinito passa pelo `ge=0` do modelo e só estoura no `int()` do score."""
        with pytest.raises(ValueError):
            parse_valor_monetario(v)

    def test_valor_implausivel_e_rejeitado(self):
        with pytest.raises(ValueError):
            parse_valor_monetario("1e12")

    @pytest.mark.parametrize("v", ["inf", "1e999"])
    def test_entrevista_com_valor_nao_finito_nao_estoura(self, v):
        """O erro precisa voltar como campo inválido, não como exceção até o grafo."""
        with pytest.raises(ValidationError):
            DadosEntrevista(
                renda_mensal=v, tipo_emprego="formal", despesas_fixas=0,
                num_dependentes=0, tem_dividas=False,
            )

    def test_score_nunca_estoura_para_valores_validos(self):
        from src.services.scoring import calcular_score

        dados = DadosEntrevista(
            renda_mensal="999999999", tipo_emprego="formal", despesas_fixas=0,
            num_dependentes=0, tem_dividas=False,
        )
        assert calcular_score(dados) == 1000
