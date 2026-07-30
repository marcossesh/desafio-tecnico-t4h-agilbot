"""Acesso a `solicitacoes_aumento_limite.csv` — o pedido formal exigido pelo enunciado."""
from __future__ import annotations

from pathlib import Path

from src.core.constants import HEADER_SOLICITACOES, SOLICITACOES_CSV
from src.domain.enums import StatusPedido
from src.domain.models import SolicitacaoAumento
from src.repositories.base import CsvRepository, RepositoryError


class SolicitacaoRepository:
    def __init__(self, path: Path | None = None):
        self.csv = CsvRepository(path or SOLICITACOES_CSV, HEADER_SOLICITACOES)

    def registrar(self, solicitacao: SolicitacaoAumento) -> int:
        """Grava o pedido e devolve o índice da linha."""
        return self.csv.append_dict(solicitacao.para_csv())

    def transicionar(self, idx: int, solicitacao: SolicitacaoAumento) -> None:
        """Move o pedido de `pendente` para um estado terminal, na mesma linha."""
        if not solicitacao.status_pedido.e_terminal:
            raise RepositoryError(
                f"Transição inválida: {solicitacao.status_pedido.value} não é terminal."
            )
        self.csv.update_row(idx, solicitacao.para_csv())

    def listar(self) -> list[dict[str, str]]:
        try:
            return self.csv.read_dicts()
        except RepositoryError:
            return []

    def do_cliente(self, cpf: str) -> list[dict[str, str]]:
        return [linha for linha in self.listar() if linha.get("cpf_cliente") == cpf]

    def status_da_linha(self, idx: int) -> StatusPedido | None:
        linhas = self.listar()
        if not 0 <= idx < len(linhas):
            return None
        try:
            return StatusPedido(linhas[idx].get("status_pedido", ""))
        except ValueError:
            return None
