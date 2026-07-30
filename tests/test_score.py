"""Fórmula ponderada do enunciado e a calibração da política de crédito.

A classe `TestEscalaReal` documenta em código o limite da fórmula: os pesos não-razão
somam no máximo 500, então a escala alcançável não é 0–1000 uniformemente. As faixas em
`score_limite.csv` são calibradas contra essa escala real.
"""
from __future__ import annotations

import pytest

from src.core.constants import SCORE_MAXIMO, SCORE_MINIMO
from src.domain.models import DadosEntrevista
from src.repositories.score_limite import FaixaScoreRepository
from src.services.scoring import calcular_score, peso_dependentes


def entrevista(**kwargs) -> DadosEntrevista:
    base = {
        "renda_mensal": 5000, "tipo_emprego": "formal", "despesas_fixas": 2000,
        "num_dependentes": 1, "tem_dividas": False,
    }
    return DadosEntrevista(**{**base, **kwargs})


class TestFormula:
    def test_exemplo_conferido_na_mao(self):
        # (5000 / 2001) * 30 = 74,96 + 300 (formal) + 80 (1 dep) + 100 (sem dívidas)
        assert calcular_score(entrevista()) == 555

    def test_dividas_derrubam_duzentos_pontos(self):
        assert calcular_score(entrevista()) - calcular_score(entrevista(tem_dividas=True)) == 200

    @pytest.mark.parametrize(
        ("emprego", "esperado"), [("formal", 555), ("autônomo", 455), ("desempregado", 255)]
    )
    def test_peso_por_tipo_de_emprego(self, emprego: str, esperado: int):
        assert calcular_score(entrevista(tipo_emprego=emprego)) == esperado

    @pytest.mark.parametrize(
        ("dependentes", "peso"), [(0, 100), (1, 80), (2, 60), (3, 30), (7, 30)]
    )
    def test_tres_ou_mais_dependentes_compartilham_o_peso(self, dependentes: int, peso: int):
        assert peso_dependentes(dependentes) == peso

    def test_despesa_zero_nao_divide_por_zero(self):
        assert calcular_score(entrevista(renda_mensal=1000, despesas_fixas=0)) > 0


class TestClamp:
    def test_teto(self):
        # Renda muito acima das despesas satura o termo de razão.
        score = calcular_score(
            entrevista(renda_mensal=1_000_000, despesas_fixas=100, num_dependentes=0)
        )
        assert score == SCORE_MAXIMO

    def test_piso(self):
        score = calcular_score(
            entrevista(
                renda_mensal=0, despesas_fixas=5000, tipo_emprego="desempregado",
                num_dependentes=4, tem_dividas=True,
            )
        )
        assert score == SCORE_MINIMO


class TestEscalaReal:
    """Fixa em código por que as faixas não são uniformes em 0–1000."""

    def test_termos_nao_razao_somam_no_maximo_500(self):
        # Melhor caso sem contribuição de renda: formal + 0 dependentes + sem dívidas.
        sem_renda = calcular_score(
            entrevista(renda_mensal=0, despesas_fixas=0, num_dependentes=0)
        )
        assert sem_renda == 500

    def test_perfil_empregado_tipico_fica_entre_450_e_600(self):
        for renda, despesas in [(5000, 2000), (8000, 2500), (3500, 1500), (12000, 6000)]:
            score = calcular_score(
                entrevista(renda_mensal=renda, despesas_fixas=despesas, num_dependentes=1)
            )
            assert 450 <= score <= 600, f"renda={renda} despesas={despesas} -> {score}"

    def test_faixa_de_topo_exige_perfil_impecavel(self):
        """601+ é alcançável, mas só com formal + 0 dependentes + sem dívidas + renda alta.
        É uma decisão de produto declarada no README, não um acidente de calibração."""
        impecavel = calcular_score(
            entrevista(renda_mensal=8000, despesas_fixas=2300, num_dependentes=0)
        )
        assert impecavel > 600

        # O mesmo cliente com um dependente e dívidas não chega lá.
        comum = calcular_score(
            entrevista(
                renda_mensal=8000, despesas_fixas=2300, num_dependentes=1, tem_dividas=True
            )
        )
        assert comum < 601

    def test_scores_semeados_vivem_na_escala_da_formula(self, cliente_repo):
        """Semear scores em escala FICO (720, 850) faria a entrevista derrubar o score de
        todo cliente — e o fluxo `rejeitado -> entrevista -> aprovado` nunca fecharia."""
        for cliente in cliente_repo.listar():
            assert 0 <= cliente.score <= 700, f"{cliente.nome} fora da escala alcançável"

    def test_toda_faixa_da_politica_e_alcancavel(self, faixa_repo: FaixaScoreRepository):
        """Nenhuma faixa pode ser letra morta: cada uma tem um perfil que a atinge."""
        perfis = [
            entrevista(renda_mensal=0, despesas_fixas=3000, tipo_emprego="desempregado",
                       num_dependentes=3, tem_dividas=True),                      # ~0
            entrevista(renda_mensal=2000, despesas_fixas=1500, tipo_emprego="autônomo",
                       num_dependentes=2, tem_dividas=True),                      # ~200
            entrevista(renda_mensal=2500, despesas_fixas=2000, tipo_emprego="autônomo",
                       num_dependentes=1, tem_dividas=False),                     # ~417
            entrevista(renda_mensal=4200, despesas_fixas=1200, tipo_emprego="autônomo",
                       num_dependentes=0, tem_dividas=False),                     # ~505
            entrevista(renda_mensal=12000, despesas_fixas=2000, num_dependentes=0),  # ~680
        ]
        atingidas = {faixa_repo.faixa_para(calcular_score(p)).score_min for p in perfis}
        assert atingidas == {f.score_min for f in faixa_repo.listar()}
