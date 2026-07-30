"""Trilha de auditoria das mudanças de score."""
from __future__ import annotations

from pathlib import Path

from src.core.constants import HEADER_HISTORICO_SCORE, HISTORICO_SCORE_CSV
from src.domain.models import RegistroScore
from src.repositories.base import CsvRepository, RepositoryError


class HistoricoScoreRepository:
    def __init__(self, path: Path | None = None):
        self.csv = CsvRepository(path or HISTORICO_SCORE_CSV, HEADER_HISTORICO_SCORE)

    def registrar(self, registro: RegistroScore) -> int:
        return self.csv.append_dict(registro.para_csv())

    def listar(self) -> list[dict[str, str]]:
        try:
            return self.csv.read_dicts()
        except RepositoryError:
            return []

    def do_cliente(self, cpf: str) -> list[dict[str, str]]:
        return [linha for linha in self.listar() if linha.get("cpf_cliente") == cpf]
