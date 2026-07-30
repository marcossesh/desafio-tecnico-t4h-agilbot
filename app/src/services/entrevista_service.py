"""Entrevista de crédito: valida os 5 dados, recalcula o score e persiste."""
from __future__ import annotations

from pydantic import ValidationError

from src.core.logging import get_logger
from src.domain.models import Cliente, DadosEntrevista, RegistroScore
from src.domain.results import ResultadoEntrevista
from src.repositories.base import RepositoryError
from src.repositories.clientes import ClienteRepository
from src.repositories.historico_score import HistoricoScoreRepository
from src.services.scoring import calcular_score

logger = get_logger(__name__)


def _mensagem_de_erro(exc: ValidationError) -> str:
    """Traduz o erro do Pydantic em algo que o agente possa repassar ao cliente."""
    partes = []
    for erro in exc.errors():
        campo = ".".join(str(p) for p in erro["loc"]) or "dado"
        partes.append(f"{campo}: {erro['msg']}")
    return "; ".join(partes)


class EntrevistaService:
    def __init__(
        self,
        cliente_repo: ClienteRepository | None = None,
        historico_repo: HistoricoScoreRepository | None = None,
    ):
        self.clientes = cliente_repo or ClienteRepository()
        self.historico = historico_repo or HistoricoScoreRepository()

    def _registrar_historico(self, cliente: Cliente, novo_score: int) -> None:
        """Registra a mudança de score na trilha de auditoria."""
        try:
            self.historico.registrar(
                RegistroScore(
                    cpf_cliente=cliente.cpf,
                    score_anterior=cliente.score,
                    score_novo=novo_score,
                )
            )
        except RepositoryError as exc:
            logger.warning(
                "Score de %s atualizado, mas não registrado no histórico: %s",
                cliente.cpf, exc,
            )

    def registrar(self, cliente: Cliente, **respostas: object) -> ResultadoEntrevista:
        """Valida as respostas, recalcula o score e grava em `clientes.csv`."""
        try:
            dados = DadosEntrevista(**respostas)
        except (ValidationError, ValueError) as exc:
            mensagem = (
                _mensagem_de_erro(exc) if isinstance(exc, ValidationError) else str(exc)
            )
            return ResultadoEntrevista(
                ok=False, mensagem=f"Dados inválidos na entrevista — {mensagem}"
            )

        novo_score = calcular_score(dados)

        try:
            self.clientes.atualizar_score(cliente.cpf, novo_score)
        except RepositoryError as exc:
            logger.error("Falha ao persistir novo score de %s: %s", cliente.cpf, exc)
            return ResultadoEntrevista(
                ok=False,
                mensagem="Não consegui salvar o resultado da entrevista agora.",
                score_anterior=cliente.score,
                score_novo=novo_score,
            )

        self._registrar_historico(cliente, novo_score)

        return ResultadoEntrevista(
            ok=True,
            mensagem=f"Score recalculado: {cliente.score} -> {novo_score}.",
            score_anterior=cliente.score,
            score_novo=novo_score,
            cliente_atualizado=cliente.model_copy(update={"score": novo_score}),
        )
