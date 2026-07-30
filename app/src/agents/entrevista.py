"""Agente de Entrevista de Crédito: coleta os 5 dados e recalcula o score."""
from __future__ import annotations

from typing import Literal

from langchain_core.tools import tool
from langgraph.graph import END
from langgraph.types import Command

from src.agents.base import CHAVE_HANDOFF, Handler, run_agent_turn
from src.agents.common import encerrar_atendimento, handler_encerrar
from src.agents.contexto import cliente_do_estado
from src.agents.prompts import INSTRUCAO_SEM_CLIENTE, PROMPT_ENTREVISTA
from src.core.utils import interno
from src.orchestration.container import get_services

NOME = "entrevista"


@tool
def registrar_entrevista(
    renda_mensal: str,
    tipo_emprego: str,
    despesas_fixas: str,
    num_dependentes: int,
    tem_dividas: str,
) -> str:
    """Registra as 5 respostas da entrevista e recalcula o score do cliente. Chame apenas
    quando tiver TODAS as respostas, repassando-as como o cliente as informou
    (`tipo_emprego`: formal, autônomo ou desempregado; `tem_dividas`: sim ou não)."""
    return ""


def _handler_registrar(args: dict, state: dict) -> tuple[str, dict]:
    """Valida, recalcula e devolve o atendimento ao crédito."""
    cliente = cliente_do_estado(state)
    if cliente is None:
        return interno(INSTRUCAO_SEM_CLIENTE), {}

    resultado = get_services().entrevista.registrar(
        cliente,
        renda_mensal=args.get("renda_mensal"),
        tipo_emprego=args.get("tipo_emprego"),
        despesas_fixas=args.get("despesas_fixas"),
        num_dependentes=args.get("num_dependentes"),
        tem_dividas=args.get("tem_dividas"),
    )

    if not resultado.ok:
        return (
            interno(
                f"{resultado.mensagem}. Repergunte ao cliente APENAS o campo com problema, "
                "de forma simples e cordial. Não recomece a entrevista."
            ),
            {},
        )

    efeitos: dict = {"cliente": resultado.cliente_atualizado.model_dump(mode="json")}
    efeitos[CHAVE_HANDOFF] = "credito"
    efeitos["current_agent"] = "credito"

    return (
        interno(
            f"Entrevista concluída. {resultado.mensagem} Assumindo novamente o contexto de "
            "crédito; continue naturalmente, sem avisar o cliente."
        ),
        efeitos,
    )


TOOLS = [registrar_entrevista, encerrar_atendimento]

HANDLERS: dict[str, Handler] = {
    "registrar_entrevista": _handler_registrar,
    "encerrar_atendimento": handler_encerrar,
}


def node(state: dict) -> Command[Literal["credito", "__end__"]]:
    updates, destino = run_agent_turn(state, NOME, PROMPT_ENTREVISTA, TOOLS, HANDLERS)
    return Command(goto=destino or END, update=updates)
