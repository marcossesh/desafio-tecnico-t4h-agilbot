"""LLM falso para exercitar o grafo inteiro sem chamar nenhuma API.

O modelo devolve respostas roteirizadas (texto e/ou tool calls) e **registra tudo que
recebeu** — é o que permite asseverar o comportamento do sanitizador e da injeção de
contexto, que de outro modo só apareceriam contra um provedor real.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def fala(texto: str) -> AIMessage:
    """Resposta em linguagem natural."""
    return AIMessage(content=texto, response_metadata={"model_name": "fake-1"})


def chama(nome: str, **args: Any) -> AIMessage:
    """Resposta que aciona uma ferramenta."""
    return AIMessage(
        content="",
        tool_calls=[{"name": nome, "args": args, "id": f"call_{nome}"}],
        response_metadata={"model_name": "fake-1"},
    )


class FakeChatModel(BaseChatModel):
    """Devolve o roteiro na ordem; ao esgotar, responde uma fala genérica."""

    respostas: list[AIMessage] = []
    chamadas: list[list[BaseMessage]] = []
    ferramentas: list[Any] = []

    model_config = {"arbitrary_types_allowed": True}

    def __init__(self, respostas: list[AIMessage] | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        object.__setattr__(self, "_roteiro", iter(respostas or []))
        self.respostas = list(respostas or [])
        self.chamadas = []
        self.ferramentas = []

    @property
    def _llm_type(self) -> str:
        return "fake"

    @property
    def roteiro(self) -> Iterator[AIMessage]:
        return object.__getattribute__(self, "_roteiro")

    def bind_tools(self, tools: list, **_kwargs: Any) -> FakeChatModel:
        self.ferramentas = list(tools)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.chamadas.append(list(messages))
        try:
            resposta = next(self.roteiro)
        except StopIteration:
            resposta = fala("Posso ajudar em mais alguma coisa?")
        return ChatResult(generations=[ChatGeneration(message=resposta)])

    # --- Auxiliares de asserção --------------------------------------------

    @property
    def nomes_das_ferramentas(self) -> set[str]:
        return {getattr(t, "name", str(t)) for t in self.ferramentas}

    def prompt_da_chamada(self, indice: int = -1) -> str:
        """System prompt recebido em uma das chamadas (inclui o bloco de contexto)."""
        return str(self.chamadas[indice][0].content)

    def historico_da_chamada(self, indice: int = -1) -> list[BaseMessage]:
        """Mensagens após o system prompt — o histórico já sanitizado."""
        return self.chamadas[indice][1:]
