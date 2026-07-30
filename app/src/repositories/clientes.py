"""Acesso a `clientes.csv` — a base de autenticação e o alvo das atualizações de score."""
from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from src.core.constants import CLIENTES_CSV, HEADER_CLIENTES
from src.core.logging import get_logger
from src.core.utils import apenas_digitos
from src.domain.models import Cliente
from src.repositories.base import CsvRepository, RepositoryError

logger = get_logger(__name__)


class ClienteRepository:
    def __init__(self, path: Path | None = None):
        self.csv = CsvRepository(path or CLIENTES_CSV, HEADER_CLIENTES)

    def listar(self) -> list[Cliente]:
        """Lista os clientes válidos, ignorando e registrando linhas inconsistentes."""
        clientes: list[Cliente] = []
        for i, linha in enumerate(self.csv.read_dicts(), start=2):
            try:
                clientes.append(Cliente(**linha))
            except ValidationError as exc:
                logger.warning("Linha %d de clientes.csv ignorada (inválida): %s", i, exc)
        return clientes

    def buscar_por_cpf(self, cpf: str) -> Cliente | None:
        alvo = apenas_digitos(cpf)
        return next((c for c in self.listar() if c.cpf == alvo), None)

    def _atualizar_campos(self, cpf: str, campos: dict[str, str]) -> None:
        alvo = apenas_digitos(cpf)
        linhas = self.csv.read_dicts()
        for linha in linhas:
            if apenas_digitos(linha.get("cpf", "")) == alvo:
                linha.update(campos)
                self.csv.write_dicts(linhas, HEADER_CLIENTES)
                return
        raise RepositoryError(f"Cliente {alvo} não encontrado para atualização.")

    def atualizar_score(self, cpf: str, score: int) -> None:
        self._atualizar_campos(cpf, {"score": str(int(score))})

    def atualizar_limite(self, cpf: str, limite: float) -> None:
        self._atualizar_campos(cpf, {"limite_atual": f"{limite:.2f}"})
