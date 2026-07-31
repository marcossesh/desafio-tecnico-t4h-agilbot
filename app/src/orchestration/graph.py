"""Grafo de estado do atendimento."""
from __future__ import annotations

from functools import lru_cache

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents import cambio, credito, entrevista, triagem
from src.core.constants import AGENTE_PADRAO, AGENTES, MSG_ATENDIMENTO_ENCERRADO
from src.orchestration.state import AgentState

NOS = {
    "triagem": triagem.node,
    "credito": credito.node,
    "entrevista": entrevista.node,
    "cambio": cambio.node,
}

NO_ENCERRADO = "encerrado"


def _no_encerrado(_state: AgentState) -> dict:
    """Responde a mensagens que chegam depois do atendimento encerrado.

    Não chama o LLM: é uma barreira de domínio, determinística e sem custo.
    """
    return {"messages": [AIMessage(content=MSG_ATENDIMENTO_ENCERRADO)], "finished": True}


def _selecionar_agente(state: AgentState) -> str:
    """Retoma a conversa com o agente que a conduzia, ou barra o que já foi encerrado.

    Sem esta checagem, `finished` seria apenas o `disabled` do widget de chat: qualquer
    caminho fora da UI (refresh, outra aba, sessão retomada do Postgres, uso programático)
    executaria operações de crédito normalmente sobre um atendimento encerrado.
    """
    if state.get("finished"):
        return NO_ENCERRADO
    atual = state.get("current_agent") or AGENTE_PADRAO
    return atual if atual in NOS else AGENTE_PADRAO


def montar_grafo() -> StateGraph:
    builder = StateGraph(AgentState)
    for nome, no in NOS.items():
        builder.add_node(nome, no)
    builder.add_node(NO_ENCERRADO, _no_encerrado)

    rotas = {a: a for a in AGENTES}
    rotas[NO_ENCERRADO] = NO_ENCERRADO
    builder.set_conditional_entry_point(_selecionar_agente, rotas)
    builder.add_edge(NO_ENCERRADO, END)
    return builder


def compile_graph(checkpointer=None) -> CompiledStateGraph:
    """Compila o grafo, opcionalmente com checkpointer (sessões persistentes)."""
    return montar_grafo().compile(checkpointer=checkpointer)


@lru_cache(maxsize=1)
def build_graph() -> CompiledStateGraph:
    """Grafo sem checkpointer — usado em testes e invocações pontuais."""
    return compile_graph()
