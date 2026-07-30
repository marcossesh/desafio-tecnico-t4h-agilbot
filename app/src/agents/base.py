"""Motor de um turno de agente."""
from __future__ import annotations

import re
from collections.abc import Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agents.contexto import render_contexto
from src.core.constants import MAX_ITERACOES_TURNO, MSG_INSTABILIDADE, REGEX_VAZAMENTO
from src.core.logging import get_logger
from src.core.utils import texto_da_mensagem
from src.providers.llm import LLMIndisponivelError, get_chat_model

logger = get_logger(__name__)

Handler = Callable[[dict, dict], tuple[str, dict]]

CHAVE_HANDOFF = "__handoff__"

_VAZAMENTO = re.compile(REGEX_VAZAMENTO, re.IGNORECASE)

INSTRUCAO_RESPOSTA_FINAL = SystemMessage(
    content=(
        "Escreva AGORA a resposta final ao cliente, em português do Brasil, com suas "
        "próprias palavras: curta (1 a 3 frases), cordial e direta. Baseie-se no "
        "resultado das ferramentas acima. Não chame ferramentas e não copie textos "
        "internos."
    )
)


def sanitizar_historico(messages: list) -> list:
    """Reduz o histórico à conversa: humano e falas do atendente."""
    limpo: list = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            limpo.append(msg)
        elif isinstance(msg, AIMessage) and (texto := texto_da_mensagem(msg.content)):
            limpo.append(AIMessage(content=texto))
    return limpo


def _tem_texto(mensagens: list) -> bool:
    return any(
        isinstance(m, AIMessage) and texto_da_mensagem(m.content) for m in mensagens
    )


def _silenciar(mensagens: list) -> list:
    """Zera o texto das falas do agente, preservando as tool calls para auditoria."""
    return [
        m.model_copy(update={"content": ""})
        if isinstance(m, AIMessage) and texto_da_mensagem(m.content)
        else m
        for m in mensagens
    ]


def _redigir_resposta(modelo: BaseChatModel, convo: list, agente: str) -> AIMessage | None:
    """Força uma resposta final ao cliente quando o turno terminaria sem texto."""
    try:
        resposta = modelo.invoke([*convo, INSTRUCAO_RESPOSTA_FINAL])
    except Exception as exc:
        logger.error("Falha ao redigir resposta final no agente %s: %s", agente, exc)
        return None
    if isinstance(resposta, AIMessage) and texto_da_mensagem(resposta.content):
        return resposta
    return None


def _detectar_vazamento(mensagens: list, agente: str) -> bool:
    """Acusa quando o atendente denuncia a existência de múltiplos agentes."""
    for msg in mensagens:
        if isinstance(msg, AIMessage) and (texto := texto_da_mensagem(msg.content)):
            achado = _VAZAMENTO.search(texto)
            if achado:
                logger.warning(
                    "Possível vazamento de transição no agente %s: %r", agente, achado.group(0)
                )
                return True
    return False


def _nome_do_provider(resposta: AIMessage) -> str:
    """Nome do modelo que atendeu a chamada, para o painel de diagnóstico."""
    meta = getattr(resposta, "response_metadata", None) or {}
    return str(meta.get("model_name") or meta.get("model") or "")


def run_agent_turn(
    state: dict,
    agent_name: str,
    system_prompt: str,
    tools: list,
    handlers: dict[str, Handler],
) -> tuple[dict, str | None]:
    """Executa um turno e devolve `(atualizações_do_estado, destino_do_handoff)`."""
    try:
        modelo = get_chat_model()
    except LLMIndisponivelError as exc:
        logger.error("LLM indisponível: %s", exc)
        return {"messages": [AIMessage(content=MSG_INSTABILIDADE)]}, None

    modelo_com_tools = modelo.bind_tools(tools) if tools else modelo

    prompt = f"{system_prompt}\n\n{render_contexto(state)}"
    convo: list = [SystemMessage(content=prompt), *sanitizar_historico(state["messages"])]

    novas_mensagens: list = []
    updates: dict = {"current_agent": agent_name}
    destino: str | None = None

    for _ in range(MAX_ITERACOES_TURNO):
        try:
            resposta = modelo_com_tools.invoke(convo)
        except Exception as exc:
            logger.error("Falha ao invocar LLM no agente %s: %s", agent_name, exc)
            novas_mensagens.append(AIMessage(content=MSG_INSTABILIDADE))
            break

        if provider := _nome_do_provider(resposta):
            updates["llm_provider"] = provider

        convo.append(resposta)
        novas_mensagens.append(resposta)

        if not resposta.tool_calls:
            break

        for chamada in resposta.tool_calls:
            handler = handlers.get(chamada["name"])
            if handler is None:
                conteudo, efeitos = (
                    f"[interno] Ferramenta indisponível neste contexto: {chamada['name']}.",
                    {},
                )
            else:
                conteudo, efeitos = handler(chamada.get("args") or {}, {**state, **updates})

            convo.append(
                ToolMessage(
                    content=conteudo, tool_call_id=chamada["id"], name=chamada["name"]
                )
            )
            novas_mensagens.append(convo[-1])

            destino = efeitos.pop(CHAVE_HANDOFF, None) or destino
            updates.update(efeitos)

        if destino:
            break

    if destino:
        novas_mensagens = _silenciar(novas_mensagens)
    elif not _tem_texto(novas_mensagens):
        redigida = _redigir_resposta(modelo, convo, agent_name)
        if redigida is not None:
            novas_mensagens.append(redigida)

    updates["vazamento_detectado"] = _detectar_vazamento(novas_mensagens, agent_name)
    updates["messages"] = novas_mensagens
    return updates, destino
