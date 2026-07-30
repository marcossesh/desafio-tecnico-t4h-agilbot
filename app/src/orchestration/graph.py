"""Grafo de estado do atendimento."""
from __future__ import annotations

from functools import lru_cache

from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents import cambio, credito, entrevista, triagem
from src.core.constants import AGENTE_PADRAO, AGENTES
from src.orchestration.state import AgentState

NOS = {
    "triagem": triagem.node,
    "credito": credito.node,
    "entrevista": entrevista.node,
    "cambio": cambio.node,
}


def _selecionar_agente(state: AgentState) -> str:
    """Retoma a conversa com o agente que a conduzia."""
    atual = state.get("current_agent") or AGENTE_PADRAO
    return atual if atual in NOS else AGENTE_PADRAO


def montar_grafo() -> StateGraph:
    builder = StateGraph(AgentState)
    for nome, no in NOS.items():
        builder.add_node(nome, no)
    builder.set_conditional_entry_point(_selecionar_agente, {a: a for a in AGENTES})
    return builder


def compile_graph(checkpointer=None) -> CompiledStateGraph:
    """Compila o grafo, opcionalmente com checkpointer (sessões persistentes)."""
    return montar_grafo().compile(checkpointer=checkpointer)


@lru_cache(maxsize=1)
def build_graph() -> CompiledStateGraph:
    """Grafo sem checkpointer — usado em testes e invocações pontuais."""
    return compile_graph()
