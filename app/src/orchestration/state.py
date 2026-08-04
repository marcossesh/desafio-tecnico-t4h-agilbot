"""Estado compartilhado do atendimento."""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

from src.core.constants import AGENTE_PADRAO


class UltimaSolicitacao(TypedDict, total=False):
    """O último pedido de aumento avaliado."""

    linha_idx: int
    valor_solicitado: float
    score_avaliado: int
    status: str


class AgentState(TypedDict, total=False):
    """Estado único que trafega entre todos os agentes."""

    messages: Annotated[list, add_messages]

    cpf_informado: str
    cpf: str
    authenticated: bool
    auth_attempts: int
    cliente: dict[str, Any] | None

    current_agent: str
    finished: bool

    ultima_solicitacao: UltimaSolicitacao | None
    entrevista_oferecida: bool
    entrevista_concluida: bool
    # Índice em `messages` onde a entrevista começou — delimita a janela em que as
    # perguntas precisam ter sido feitas.
    entrevista_inicio: int | None

    llm_provider: str
    vazamento_detectado: bool
    numeros_inventados: list[float]


def estado_inicial() -> AgentState:
    """Estado zerado no início de um atendimento."""
    return AgentState(
        messages=[],
        cpf_informado="",
        cpf="",
        authenticated=False,
        auth_attempts=0,
        cliente=None,
        current_agent=AGENTE_PADRAO,
        finished=False,
        ultima_solicitacao=None,
        entrevista_oferecida=False,
        entrevista_concluida=False,
        entrevista_inicio=None,
        llm_provider="",
        vazamento_detectado=False,
        numeros_inventados=[],
    )
