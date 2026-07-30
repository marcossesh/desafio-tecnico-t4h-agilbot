"""Ferramentas e handlers compartilhados entre agentes."""
from __future__ import annotations

from langchain_core.tools import tool

from src.agents.base import CHAVE_HANDOFF, Handler
from src.agents.prompts import INSTRUCAO_DESPEDIDA, INSTRUCAO_SEM_CONHECIMENTO
from src.core.utils import interno
from src.orchestration.container import get_services


@tool
def encerrar_atendimento() -> str:
    """Encerra o atendimento. Use quando o cliente se despedir, disser que não precisa de
    mais nada ou pedir para finalizar."""
    return ""


@tool
def consultar_base_conhecimento(pergunta: str) -> str:
    """Consulta as políticas oficiais do banco (regras de crédito, tarifas, câmbio,
    segurança) para responder dúvidas do cliente com informação oficial."""
    return ""


def handler_encerrar(_args: dict, _state: dict) -> tuple[str, dict]:
    return interno(INSTRUCAO_DESPEDIDA), {"finished": True}


def handler_consultar_conhecimento(args: dict, _state: dict) -> tuple[str, dict]:
    resultado = get_services().knowledge.consultar(args.get("pergunta", ""))
    if not resultado.ok or not resultado.contexto:
        return interno(INSTRUCAO_SEM_CONHECIMENTO), {}

    fontes = ", ".join(resultado.fontes)
    return (
        interno(
            f"Trechos da base de conhecimento (fontes: {fontes}):\n{resultado.contexto}\n\n"
            "Responda com suas próprias palavras, de forma clara e resumida, usando apenas "
            "o conteúdo acima. Não cite este texto literalmente."
        ),
        {},
    )


def make_handoff_handler(destino: str, contexto: str) -> Handler:
    """Cria um handler que passa o atendimento a outro agente, no mesmo turno."""

    def handler(_args: dict, _state: dict) -> tuple[str, dict]:
        return (
            interno(
                f"Assumindo o atendimento no contexto de {contexto}. Continue a conversa "
                "naturalmente, sem avisar o cliente sobre qualquer mudança."
            ),
            {CHAVE_HANDOFF: destino, "current_agent": destino},
        )

    return handler
