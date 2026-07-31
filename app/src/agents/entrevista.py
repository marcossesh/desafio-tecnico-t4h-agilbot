"""Agente de Entrevista de Crédito: coleta os 5 dados e recalcula o score."""
from __future__ import annotations

from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import END
from langgraph.types import Command

from src.agents.base import CHAVE_HANDOFF, Handler, run_agent_turn
from src.agents.common import encerrar_atendimento, handler_encerrar
from src.agents.contexto import cliente_do_estado
from src.agents.prompts import INSTRUCAO_SEM_CLIENTE, PROMPT_ENTREVISTA
from src.core.logging import get_logger
from src.core.utils import interno, normalizar, texto_da_mensagem
from src.orchestration.container import get_services

logger = get_logger(__name__)

NOME = "entrevista"

# Marcas de que a pergunta chegou a ser feita ao cliente. Vêm do próprio roteiro em
# `PROMPT_ENTREVISTA`, então são o vocabulário que o agente de fato usa.
MARCAS_DAS_PERGUNTAS: dict[str, tuple[str, ...]] = {
    "renda_mensal": ("renda", "ganha", "recebe"),
    "tipo_emprego": ("emprego", "trabalh", "formal", "autonom", "ocupacao"),
    "despesas_fixas": ("despesa", "gasto", "custo fixo"),
    "num_dependentes": ("dependente",),
    "tem_dividas": ("divida", "dividas", "endivid"),
}


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


def _perguntas_nao_feitas(state: dict) -> list[str]:
    """Campos cujo assunto nunca apareceu na entrevista.

    O handler valida o formato das 5 respostas, nunca a procedência delas — e o modelo
    pulou a pergunta sobre dívidas ativas e preencheu `não` por conta própria. São 200
    pontos de score e uma mudança de faixa decididos por um dado que o cliente não deu.

    A verificação é lexical e vale para os dois lados da conversa: o assunto conta tanto
    se o atendente perguntou quanto se o cliente se antecipou ("4200, autônomo, sem
    dívidas"). Restringi-la às perguntas do atendente bloquearia esse cliente, que é
    legítimo — o que se quer barrar é o campo que ninguém, em momento algum, mencionou.
    """
    inicio = int(state.get("entrevista_inicio") or 0)
    janela = " ".join(
        normalizar(texto)
        for msg in (state.get("messages") or [])[inicio:]
        if isinstance(msg, AIMessage | HumanMessage)
        and (texto := texto_da_mensagem(msg.content))
    )
    return [
        campo
        for campo, marcas in MARCAS_DAS_PERGUNTAS.items()
        if not any(marca in janela for marca in marcas)
    ]


def _handler_registrar(args: dict, state: dict) -> tuple[str, dict]:
    """Valida, recalcula e devolve o atendimento ao crédito."""
    cliente = cliente_do_estado(state)
    if cliente is None:
        return interno(INSTRUCAO_SEM_CLIENTE), {}

    if faltando := _perguntas_nao_feitas(state):
        logger.warning("Entrevista concluída sem perguntar: %s", ", ".join(faltando))
        return (
            interno(
                f"Você ainda não perguntou ao cliente: {', '.join(faltando)}. Não é "
                "possível registrar a entrevista com uma resposta que ele não deu. "
                "Faça AGORA a primeira pergunta que falta, uma só, e aguarde a resposta."
            ),
            {},
        )

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

    # O texto é imperativo quanto ao número porque a versão anterior ("score recalculado:
    # 540 -> 467") deixava os dois valores soltos: o modelo anunciou um terceiro número,
    # inventado, e depois chamou o score novo de "anterior".
    return (
        interno(
            f"Entrevista concluída. O novo score do cliente é {resultado.score_novo}. "
            f"Ao comunicar o resultado, use EXATAMENTE o número {resultado.score_novo} — "
            "nunca estime nem arredonde. O score anterior era "
            f"{resultado.score_anterior}; não cite esse número ao cliente. Assumindo "
            "novamente o contexto de crédito; continue naturalmente, sem avisar o cliente."
        ),
        efeitos,
    )


TOOLS = [registrar_entrevista, encerrar_atendimento]

HANDLERS: dict[str, Handler] = {
    "registrar_entrevista": _handler_registrar,
    "encerrar_atendimento": handler_encerrar,
}


def node(state: dict) -> Command[Literal["credito", "__end__"]]:
    estado = dict(state)
    # Marca onde a entrevista começou. O "sim" que aceitou a oferta fica do lado de fora
    # da janela — senão ele autorizaria sozinho a resposta sobre dívidas.
    if estado.get("entrevista_inicio") is None:
        estado["entrevista_inicio"] = len(estado.get("messages") or [])

    updates, destino = run_agent_turn(estado, NOME, PROMPT_ENTREVISTA, TOOLS, HANDLERS)
    return Command(
        goto=destino or END,
        update={"entrevista_inicio": estado["entrevista_inicio"], **updates},
    )
