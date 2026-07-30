"""Fórmula ponderada de score do enunciado."""
from __future__ import annotations

from src.core.constants import (
    MAX_DEPENDENTES_TABELADO,
    PESO_DEPENDENTES,
    PESO_DIVIDAS,
    PESO_EMPREGO,
    PESO_RENDA,
    SCORE_MAXIMO,
    SCORE_MINIMO,
)
from src.domain.models import DadosEntrevista


def peso_dependentes(quantidade: int) -> int:
    """A tabela do enunciado vai de 0 a "3+": 3 ou mais compartilham o mesmo peso."""
    return PESO_DEPENDENTES[min(max(quantidade, 0), MAX_DEPENDENTES_TABELADO)]


def calcular_score(dados: DadosEntrevista) -> int:
    """Score inteiro no intervalo [0, 1000]."""
    contribuicao_renda = (dados.renda_mensal / (dados.despesas_fixas + 1)) * PESO_RENDA

    bruto = (
        contribuicao_renda
        + PESO_EMPREGO[dados.tipo_emprego.value]
        + peso_dependentes(dados.num_dependentes)
        + PESO_DIVIDAS[dados.tem_dividas]
    )
    return int(max(SCORE_MINIMO, min(SCORE_MAXIMO, round(bruto))))
