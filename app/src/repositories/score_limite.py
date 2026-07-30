"""Acesso a `score_limite.csv` — a política de crédito por faixa de score."""
from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from src.core.constants import SCORE_LIMITE_CSV
from src.core.logging import get_logger
from src.domain.models import FaixaScore
from src.repositories.base import CsvRepository, RepositoryError

logger = get_logger(__name__)

HEADER = ["score_min", "score_max", "limite_maximo", "taxa_juros_mensal"]


class FaixaScoreRepository:
    def __init__(self, path: Path | None = None):
        self.csv = CsvRepository(path or SCORE_LIMITE_CSV, HEADER)

    def listar(self) -> list[FaixaScore]:
        faixas: list[FaixaScore] = []
        for i, linha in enumerate(self.csv.read_dicts(), start=2):
            try:
                faixas.append(FaixaScore(**linha))
            except ValidationError as exc:
                logger.warning("Linha %d de score_limite.csv ignorada: %s", i, exc)
        if not faixas:
            raise RepositoryError("Política de crédito vazia ou ilegível.")
        return faixas

    def faixa_para(self, score: int) -> FaixaScore | None:
        return next((f for f in self.listar() if f.contem(score)), None)
