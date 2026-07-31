"""Ponte entre a UI e o grafo."""
from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError

from src.core.constants import MSG_INSTABILIDADE, RECURSION_LIMIT
from src.core.logging import get_logger, set_thread_id
from src.core.utils import texto_da_mensagem
from src.orchestration.graph import compile_graph
from src.orchestration.state import estado_inicial
from src.providers.checkpointer import criar_checkpointer
from src.providers.llm import provider_ativo

logger = get_logger(__name__)


@dataclass
class Resposta:
    texto: str
    debug: dict = field(default_factory=dict)
    finished: bool = False


class Atendimento:
    """Grafo compilado + checkpointer. Instância única por processo."""

    def __init__(self) -> None:
        checkpointer, descricao = criar_checkpointer()
        self.grafo = compile_graph(checkpointer)
        self.persistencia = descricao
        self.provider = provider_ativo()

    def responder(self, session_id: str, mensagem: str) -> Resposta:
        set_thread_id(session_id)
        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": RECURSION_LIMIT,
        }
        entrada = self._entrada(config, mensagem)
        # Fronteira do turno: a resposta precisa vir das mensagens produzidas AGORA.
        # Varrer o histórico acumulado devolveria a fala do turno anterior quando este
        # não produz texto — resultado errado com aparência de resposta normal.
        ja_ditas = self._quantidade_de_mensagens(config)

        try:
            estado = self.grafo.invoke(entrada, config=config)
        except GraphRecursionError:
            logger.error("Limite de recursão atingido na sessão %s.", session_id)
            return Resposta(
                texto=(
                    "Me perdi um pouco aqui. Pode reformular o que precisa, por favor?"
                ),
                debug={"erro": "recursion_limit"},
            )
        except Exception as exc:
            logger.exception("Falha inesperada no atendimento: %s", exc)
            return Resposta(texto=MSG_INSTABILIDADE, debug={"erro": str(exc)})

        return Resposta(
            texto=_ultima_fala(estado, desde=ja_ditas),
            debug=self._debug(estado),
            finished=bool(estado.get("finished")),
        )

    def _quantidade_de_mensagens(self, config: dict) -> int:
        try:
            snapshot = self.grafo.get_state(config)
        except Exception:
            return 0
        return len((snapshot.values or {}).get("messages", [])) if snapshot else 0

    def _entrada(self, config: dict, mensagem: str) -> dict:
        """Estado inicial completo no primeiro turno; depois, só o delta."""
        delta = {"messages": [HumanMessage(content=mensagem)]}
        try:
            snapshot = self.grafo.get_state(config)
            iniciada = bool(snapshot and snapshot.values)
        except Exception:
            iniciada = False
        return delta if iniciada else {**estado_inicial(), **delta}

    def _debug(self, estado: dict) -> dict:
        cliente = estado.get("cliente") or {}
        return {
            "agente atual": estado.get("current_agent", "-"),
            "autenticado": bool(estado.get("authenticated")),
            "cliente": cliente.get("nome", "-"),
            "score": cliente.get("score", "-"),
            "limite": cliente.get("limite_atual", "-"),
            "tentativas de autenticação": estado.get("auth_attempts", 0),
            "último pedido": (estado.get("ultima_solicitacao") or {}).get("status", "-"),
            "modelo do turno": estado.get("llm_provider") or "-",
            "provider configurado": self.provider,
            "sessões": self.persistencia,
            "vazamento detectado": bool(estado.get("vazamento_detectado")),
        }


def _ultima_fala(estado: dict, desde: int = 0) -> str:
    """Última fala do atendente **entre as mensagens deste turno**.

    Sem o corte em `desde`, um turno que não produz texto devolveria a resposta anterior:
    o cliente pergunta "e a taxa?" e recebe de volta "seu limite é R$ 5.000,00".
    """
    novas = estado.get("messages", [])[desde:]
    falas = [
        texto for m in novas
        if isinstance(m, AIMessage) and (texto := texto_da_mensagem(m.content))
    ]
    return falas[-1] if falas else MSG_INSTABILIDADE


def atendimento_encerrado(atendimento: Atendimento, session_id: str) -> bool:
    """Se a sessão retomada já estava encerrada, a tela precisa refletir isso."""
    try:
        snapshot = atendimento.grafo.get_state(
            {"configurable": {"thread_id": session_id}}
        )
    except Exception:
        return False
    return bool((snapshot.values or {}).get("finished")) if snapshot else False


def historico_visivel(atendimento: Atendimento, session_id: str) -> list[dict]:
    """Reconstrói a conversa a partir do checkpointer (sobrevive a um refresh da página)."""
    try:
        snapshot = atendimento.grafo.get_state(
            {"configurable": {"thread_id": session_id}}
        )
    except Exception:
        return []

    mensagens = (snapshot.values or {}).get("messages", []) if snapshot else []
    visivel = []
    for msg in mensagens:
        if isinstance(msg, HumanMessage):
            visivel.append({"role": "user", "content": texto_da_mensagem(msg.content)})
        elif isinstance(msg, AIMessage) and (texto := texto_da_mensagem(msg.content)):
            visivel.append({"role": "assistant", "content": texto})
    return visivel
