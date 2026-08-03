"""Agente de Crédito: consulta de limite, pedido de aumento e reavaliação pós-entrevista."""
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
from src.agents.contexto import cliente_do_estado
from src.agents.prompts import INSTRUCAO_SEM_CLIENTE, PROMPT_CREDITO
from src.core.config import get_settings
from src.core.utils import formatar_brl, formatar_percentual, interno, parse_valor_monetario
from src.domain.enums import StatusPedido
from src.orchestration.container import get_services

NOME = "credito"


@tool
def consultar_limite() -> str:
    """Consulta o limite de crédito atual do cliente, o score e o teto da faixa."""
    return ""


@tool
def solicitar_aumento(novo_limite: float) -> str:
    """Registra um pedido formal de aumento de limite e avalia contra o score do cliente.
    Chame SEMPRE que o cliente pedir um aumento, qualquer que seja o valor."""
    return ""


@tool
def iniciar_entrevista() -> str:
    """Inicia a entrevista financeira que recalcula o score. Use quando o cliente aceitar
    a oferta após um pedido rejeitado."""
    return ""


@tool
def atender_cambio() -> str:
    """Assume o atendimento de cotação de moedas."""
    return ""


def _sem_cliente() -> tuple[str, dict]:
    return interno(INSTRUCAO_SEM_CLIENTE), {}


def _handler_consultar_limite(_args: dict, state: dict) -> tuple[str, dict]:
    cliente = cliente_do_estado(state)
    if cliente is None:
        return _sem_cliente()

    resumo = get_services().credito.consultar_limite(cliente)
    if not resumo.ok:
        return interno(f"Não foi possível consultar a política agora: {resumo.mensagem}."), {}

    return (
        interno(
            f"Limite atual: {formatar_brl(resumo.limite_atual)}. Score: {resumo.score}. "
            f"Teto para esse score: {formatar_brl(resumo.limite_maximo or 0)}, taxa "
            f"{formatar_percentual(resumo.taxa_juros_mensal or 0)} ao mês. Informe ao "
            "cliente de forma curta e natural."
        ),
        {},
    )


def _efeitos_da_solicitacao(resultado) -> dict:
    """Guarda no estado o suficiente para a reavaliação — e só isso."""
    if resultado.linha_idx is None:
        return {}
    return {
        "ultima_solicitacao": {
            "linha_idx": resultado.linha_idx,
            "valor_solicitado": resultado.solicitacao.novo_limite_solicitado,
            "score_avaliado": resultado.score_avaliado,
            "status": resultado.status.value,
        }
    }


def _atualizar_cliente(resultado) -> dict:
    if resultado.cliente_atualizado is None:
        return {}
    return {"cliente": resultado.cliente_atualizado.model_dump(mode="json")}


def _handler_solicitar_aumento(args: dict, state: dict) -> tuple[str, dict]:
    cliente = cliente_do_estado(state)
    if cliente is None:
        return _sem_cliente()

    try:
        novo_limite = parse_valor_monetario(args.get("novo_limite") or 0)
    except (TypeError, ValueError):
        return interno("Valor de limite inválido. Peça ao cliente que informe um número."), {}

    resultado = get_services().credito.solicitar_aumento(cliente, novo_limite)
    efeitos = {**_efeitos_da_solicitacao(resultado), **_atualizar_cliente(resultado)}

    if resultado.status is StatusPedido.REJEITADO:
        # Acima do teto de todas as faixas, a entrevista não é um caminho: é uma promessa
        # que nenhum recálculo de score pode cumprir.
        if resultado.acima_do_teto_global:
            return (
                interno(
                    f"{resultado.mensagem} Esse valor está acima do teto que o banco "
                    "concede em qualquer faixa de score, então NÃO ofereça a entrevista "
                    "financeira: ela não mudaria o resultado. Informe com cordialidade e "
                    "convide o cliente a pedir um valor dentro do teto informado."
                ),
                efeitos,
            )

        efeitos["entrevista_oferecida"] = True
        return (
            interno(
                f"{resultado.mensagem} Informe o cliente com suas palavras e ofereça, com "
                "gentileza, uma breve entrevista financeira que pode recalcular o score e "
                "reabrir a possibilidade de aumento. Pergunte se ele deseja fazê-la."
            ),
            efeitos,
        )

    return interno(f"{resultado.mensagem} Informe o cliente com suas palavras."), efeitos


def _reavaliacao_automatica(state: dict) -> dict | None:
    """Reavalia um pedido rejeitado quando o score mudou desde a avaliação."""
    ultima = state.get("ultima_solicitacao") or {}
    cliente = cliente_do_estado(state)

    # A condição é "melhorou", não "mudou". Com `!=`, uma entrevista que derruba o score
    # (o cliente revela dívidas e desemprego) fazia o sistema registrar, por conta
    # própria, um pedido de aumento que o cliente nunca fez — e ainda rejeitá-lo. Pedido
    # sem origem numa intenção do cliente é problema de conformidade na trilha formal.
    if (
        cliente is None
        or ultima.get("status") != StatusPedido.REJEITADO.value
        or ultima.get("score_avaliado") is None
        or cliente.score <= ultima["score_avaliado"]
    ):
        return None

    resultado = get_services().credito.solicitar_aumento(
        cliente, float(ultima.get("valor_solicitado", 0)), reavaliacao=True
    )
    return {**_efeitos_da_solicitacao(resultado), **_atualizar_cliente(resultado),
            "_mensagem_reavaliacao": resultado.mensagem}


def _handler_iniciar_entrevista(args: dict, state: dict) -> tuple[str, dict]:
    """Entra na entrevista com a janela zerada.

    `entrevista_inicio` delimita onde os 5 assuntos precisam ter aparecido. Se o cliente
    abandona a entrevista e volta depois, manter o índice antigo faria a janela abranger a
    tentativa anterior — e assuntos já mencionados lá autorizariam respostas nesta.
    """
    conteudo, efeitos = make_handoff_handler("entrevista", "entrevista financeira")(
        args, state
    )
    return conteudo, {**efeitos, "entrevista_inicio": None}


TOOLS_BASE = [consultar_limite, solicitar_aumento, iniciar_entrevista, atender_cambio,
              encerrar_atendimento]

HANDLERS: dict[str, Handler] = {
    "consultar_limite": _handler_consultar_limite,
    "solicitar_aumento": _handler_solicitar_aumento,
    "iniciar_entrevista": _handler_iniciar_entrevista,
    "atender_cambio": make_handoff_handler("cambio", "câmbio"),
    "encerrar_atendimento": handler_encerrar,
    "consultar_base_conhecimento": handler_consultar_conhecimento,
}


def tools() -> list:
    """A ferramenta de RAG só é registrada quando o RAG está de fato disponível."""
    if get_settings().rag_enabled:
        return [*TOOLS_BASE, consultar_base_conhecimento]
    return TOOLS_BASE


def node(state: dict) -> Command[Literal["entrevista", "cambio", "__end__"]]:
    prompt = PROMPT_CREDITO
    estado = dict(state)

    if (reavaliacao := _reavaliacao_automatica(state)) is not None:
        mensagem = reavaliacao.pop("_mensagem_reavaliacao", "")
        estado.update(reavaliacao)
        prompt = (
            f"{prompt}\n\nRESULTADO DA REAVALIAÇÃO AUTOMÁTICA (o score do cliente mudou "
            f"e o pedido anterior foi reavaliado): {mensagem}\nComunique esse resultado "
            "ao cliente com suas palavras, de forma natural, sem mencionar reavaliação "
            "automática nem qualquer processo interno."
        )
    else:
        reavaliacao = {}

    updates, destino = run_agent_turn(estado, NOME, prompt, tools(), HANDLERS)
    return Command(goto=destino or END, update={**reavaliacao, **updates})
