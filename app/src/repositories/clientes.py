"""Acesso a `clientes.csv` — a base de autenticação e o alvo das atualizações de score."""
from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from src.core.constants import CLIENTES_CSV, HEADER_CLIENTES
from src.core.logging import get_logger
from src.core.utils import apenas_digitos
from src.domain.models import Cliente
from src.repositories.base import COLUNA_EXCEDENTE, CsvRepository, RepositoryError

logger = get_logger(__name__)


class ClienteRepository:
    def __init__(self, path: Path | None = None):
        self.csv = CsvRepository(path or CLIENTES_CSV, HEADER_CLIENTES)

    def listar(self) -> list[Cliente]:
        """Lista os clientes válidos, ignorando e registrando linhas inconsistentes."""
        clientes: list[Cliente] = []
        for i, linha in enumerate(self.csv.read_dicts(), start=2):
            campos = {k: v for k, v in linha.items() if isinstance(k, str)}
            campos.pop(COLUNA_EXCEDENTE, None)
            try:
                clientes.append(Cliente(**campos))
            except (ValidationError, TypeError, ValueError) as exc:
                # Não basta ValidationError: uma linha malformada pode produzir TypeError
                # ou ValueError antes do Pydantic chegar a validar. Nenhuma linha isolada
                # pode tirar os demais clientes do ar.
                logger.warning("Linha %d de clientes.csv ignorada (inválida): %s", i, exc)
        return clientes

    def buscar_por_cpf(self, cpf: str) -> Cliente | None:
        alvo = apenas_digitos(cpf)
        return next((c for c in self.listar() if c.cpf == alvo), None)

    def _atualizar_campos(self, cpf: str, campos: dict[str, str]) -> None:
        """Atualiza sob o lock do repositório, com o ciclo read-modify-write inteiro dentro.

        Ler aqui e escrever depois deixaria a janela em que duas atualizações concorrentes
        (um score da entrevista e um limite aprovado, por exemplo) leem o mesmo estado e a
        segunda apaga a primeira.
        """
        alvo = apenas_digitos(cpf)
        encontrado = False

        def transformar(linhas: list[dict]) -> list[dict]:
            nonlocal encontrado
            for linha in linhas:
                if apenas_digitos(linha.get("cpf", "")) == alvo:
                    linha.update(campos)
                    encontrado = True
            return linhas

        self.csv.mutate(transformar)
        if not encontrado:
            raise RepositoryError(f"Cliente {alvo} não encontrado para atualização.")

    def atualizar_score(self, cpf: str, score: int) -> None:
        self._atualizar_campos(cpf, {"score": str(int(score))})

    def atualizar_limite(self, cpf: str, limite: float) -> None:
        self._atualizar_campos(cpf, {"limite_atual": f"{limite:.2f}"})

    def atualizar_limite_se(self, cpf: str, esperado: float, novo: float) -> bool:
        """Compare-and-set: só grava se o limite em disco ainda for o avaliado.

        Duas aprovações concorrentes avaliam contra o mesmo limite-base e a segunda
        sobrescreveria a primeira. Devolver `False` diz ao serviço que o mundo mudou
        debaixo dele e que a decisão precisa ser refeita, em vez de gravar por cima.
        """
        alvo = apenas_digitos(cpf)
        aplicado = False

        def transformar(linhas: list[dict]) -> list[dict]:
            nonlocal aplicado
            for linha in linhas:
                if apenas_digitos(linha.get("cpf", "")) != alvo:
                    continue
                try:
                    atual = float(linha.get("limite_atual") or 0)
                except ValueError:
                    return linhas
                if abs(atual - esperado) < 0.005:
                    linha["limite_atual"] = f"{novo:.2f}"
                    aplicado = True
            return linhas

        self.csv.mutate(transformar)
        return aplicado
