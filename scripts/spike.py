"""Spike vertical: exercita o grafo contra o LLM real, em terminal, sem UI."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from src.core.constants import RECURSION_LIMIT
from src.core.utils import texto_da_mensagem
from src.orchestration.graph import compile_graph
from src.providers.llm import LLMIndisponivelError, get_chat_model, provider_ativo

ROTEIRO = [
    "Olá!",
    "Meu CPF é 222.555.888-46",
    "19/07/1995",
    "Queria aumentar meu limite para 10 mil reais",
    "Pode fazer as perguntas",
    "Minha renda é 4200 por mês",
    "Sou autônomo",
    "Minhas despesas fixas são 1200",
    "Não tenho dependentes",
    "Não tenho dívidas",
    "Legal! E quanto está o euro hoje?",
    "Era só isso, obrigado!",
]

VERDE, AMARELO, CINZA, RESET = "\033[92m", "\033[93m", "\033[90m", "\033[0m"


class ContadorDeRequisicoes:
    """Conta as chamadas ao LLM."""

    def __init__(self, modelo):
        self._modelo = modelo
        self.total = 0

    def __getattr__(self, nome):
        return getattr(self._modelo, nome)

    def bind_tools(self, *args, **kwargs):
        return ContadorDeRequisicoes.compartilhado(self, self._modelo.bind_tools(*args, **kwargs))

    @classmethod
    def compartilhado(cls, pai: ContadorDeRequisicoes, modelo):
        filho = cls(modelo)
        filho.__dict__["_pai"] = pai
        return filho

    def invoke(self, *args, **kwargs):
        self.total += 1
        if pai := self.__dict__.get("_pai"):
            pai.total += 1
        return self._modelo.invoke(*args, **kwargs)


def _resposta(estado: dict) -> str:
    falas = [
        texto for m in estado["messages"]
        if isinstance(m, AIMessage) and (texto := texto_da_mensagem(m.content))
    ]
    return falas[-1] if falas else "(sem resposta)"


def _debug(estado: dict) -> str:
    partes = [
        f"agente={estado.get('current_agent')}",
        f"auth={estado.get('authenticated')}",
        f"tentativas={estado.get('auth_attempts')}",
        f"provider={estado.get('llm_provider') or '?'}",
    ]
    if estado.get("ultima_solicitacao"):
        partes.append(f"pedido={estado['ultima_solicitacao'].get('status')}")
    if estado.get("vazamento_detectado"):
        partes.append("VAZAMENTO!")
    return " | ".join(partes)


def main() -> int:
    try:
        modelo = get_chat_model()
    except LLMIndisponivelError as exc:
        print(f"{AMARELO}{exc}{RESET}")
        return 1

    contador = ContadorDeRequisicoes(modelo)
    import src.agents.base as motor

    motor.get_chat_model = lambda: contador

    print(f"{CINZA}Provider: {provider_ativo()}{RESET}\n")

    grafo = compile_graph(MemorySaver())
    config = {"configurable": {"thread_id": "spike"}, "recursion_limit": RECURSION_LIMIT}
    interativo = "-i" in sys.argv
    pausa = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--pausa=")), 0))

    turnos: list[int] = []
    entradas = iter(ROTEIRO) if not interativo else None
    while True:
        if turnos and pausa:
            time.sleep(pausa)
        if interativo:
            try:
                mensagem = input("você > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not mensagem:
                break
        else:
            mensagem = next(entradas, "")
            if not mensagem:
                break
            print(f"você > {mensagem}")

        antes = contador.total
        estado = grafo.invoke({"messages": [HumanMessage(content=mensagem)]}, config=config)
        turnos.append(contador.total - antes)
        print(f"{VERDE}bot  > {_resposta(estado)}{RESET}")
        print(f"{CINZA}       [{_debug(estado)}]{RESET}\n")

        if estado.get("finished"):
            print(f"{CINZA}--- atendimento encerrado ---{RESET}")
            break

    if turnos:
        print(
            f"{CINZA}Custo: {contador.total} requisições ao LLM em {len(turnos)} turnos "
            f"(média {contador.total / len(turnos):.1f}, máx {max(turnos)} num turno).{RESET}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
