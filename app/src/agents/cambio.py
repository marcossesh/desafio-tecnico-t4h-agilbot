"""Agente de Câmbio: cotação de moedas em tempo real."""
from __future__ import annotations

from typing import Literal

from langchain_core.tools import tool
from langgraph.graph import END
from langgraph.types import Command

from src.agents.base import Handler, run_agent_turn
from src.agents.common import (
    consultar_base_conhecimento,
    encerrar_atendimento,
    handler_consultar_conhecimento,
    handler_encerrar,
    make_handoff_handler,
)
from src.agents.prompts import PROMPT_CAMBIO
from src.core.config import get_settings
from src.core.constants import MOEDA_PADRAO
from src.core.utils import interno
from src.orchestration.container import get_services
from src.services.cambio_service import MoedaSuportada

NOME = "cambio"


@tool
def consultar_cotacao(moeda: MoedaSuportada = MOEDA_PADRAO) -> str:
    """Consulta a cotação atual de uma moeda em reais (BRL). Informe o código ISO 4217 de
    3 letras. Sem moeda especificada, cota o dólar."""
    return ""


@tool
def atender_credito() -> str:
    """Assume o atendimento de crédito (consulta de limite, pedido de aumento)."""
    return ""


def _handler_consultar_cotacao(args: dict, _state: dict) -> tuple[str, dict]:
    resultado = get_services().cambio.consultar(args.get("moeda") or MOEDA_PADRAO)

    if not resultado.ok:
        return (
            interno(
                f"{resultado.mensagem} Repasse isso ao cliente com clareza. NÃO informe a "
                "cotação de outra moeda no lugar e não invente valores."
            ),
            {},
        )

    return (
        interno(
            f"{resultado.mensagem} (atualizado em {resultado.atualizado_em}). Informe ao "
            f"cliente usando EXATAMENTE a moeda {resultado.moeda_origem} e o valor acima. "
            "Depois pergunte se pode ajudar em algo mais."
        ),
        {},
    )


TOOLS_BASE = [consultar_cotacao, atender_credito, encerrar_atendimento]

HANDLERS: dict[str, Handler] = {
    "consultar_cotacao": _handler_consultar_cotacao,
    "atender_credito": make_handoff_handler("credito", "crédito"),
    "encerrar_atendimento": handler_encerrar,
    "consultar_base_conhecimento": handler_consultar_conhecimento,
}


def tools() -> list:
    if get_settings().rag_enabled:
        return [*TOOLS_BASE, consultar_base_conhecimento]
    return TOOLS_BASE


def node(state: dict) -> Command[Literal["credito", "__end__"]]:
    updates, destino = run_agent_turn(state, NOME, PROMPT_CAMBIO, tools(), HANDLERS)
    return Command(goto=destino or END, update=updates)
