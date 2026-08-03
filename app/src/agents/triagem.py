"""Agente de Triagem: recepção, autenticação e direcionamento."""
from __future__ import annotations

from typing import Literal

from langchain_core.tools import tool
from langgraph.graph import END
from langgraph.types import Command

from src.agents.base import Handler, run_agent_turn
from src.agents.common import encerrar_atendimento, handler_encerrar, make_handoff_handler
from src.agents.prompts import INSTRUCAO_NAO_AUTENTICADO, PROMPT_TRIAGEM
from src.core.constants import MAX_TENTATIVAS_AUTH
from src.core.utils import apenas_digitos, interno
from src.orchestration.container import get_services
from src.services.auth_service import validar_cpf

NOME = "triagem"


@tool
def verificar_cpf(cpf: str) -> str:
    """Verifica se o CPF tem formato e dígitos verificadores válidos. Chame IMEDIATAMENTE
    após o cliente informar o CPF, antes de pedir a data de nascimento."""
    return ""


@tool
def autenticar_cliente(cpf: str, data_nascimento: str) -> str:
    """Autentica o cliente conferindo CPF e data de nascimento na base. Passe os valores
    exatamente como o cliente informou."""
    return ""


@tool
def atender_credito() -> str:
    """Assume o atendimento de crédito (consulta de limite, pedido de aumento). Só depois
    da autenticação bem-sucedida."""
    return ""


@tool
def atender_cambio() -> str:
    """Assume o atendimento de cotação de moedas. Só depois da autenticação bem-sucedida."""
    return ""


def _handler_verificar_cpf(args: dict, _state: dict) -> tuple[str, dict]:
    """Valida o CPF assim que informado."""
    cpf = args.get("cpf", "")
    if validar_cpf(cpf):
        return (
            interno("CPF válido. Agora peça a data de nascimento do cliente."),
            {"cpf_informado": apenas_digitos(cpf)},
        )
    return (
        interno(
            "CPF inválido (quantidade de dígitos ou dígitos verificadores incorretos). "
            "Com suas palavras, avise que o CPF não é válido e peça que digite novamente. "
            "Não peça a data de nascimento ainda."
        ),
        {},
    )


def _handler_autenticar(args: dict, state: dict) -> tuple[str, dict]:
    """Autentica e administra o limite de tentativas."""
    tentativas_atuais = int(state.get("auth_attempts", 0) or 0)
    if tentativas_atuais >= MAX_TENTATIVAS_AUTH:
        return (
            interno(
                "O limite de tentativas de autenticação já foi atingido. Encerre o "
                "atendimento com cordialidade, sem tentar autenticar de novo."
            ),
            {"finished": True},
        )

    cpf = args.get("cpf") or state.get("cpf_informado", "")
    resultado = get_services().auth.autenticar(cpf, args.get("data_nascimento", ""))

    if resultado.ok and resultado.cliente is not None:
        cliente = resultado.cliente
        return (
            interno(
                f"Autenticação bem-sucedida. Cliente: {cliente.nome} (trate por "
                f"'{cliente.primeiro_nome}'). Escreva uma saudação curta usando o primeiro "
                "nome e pergunte em que pode ajudar, citando as opções concretas."
            ),
            {
                "authenticated": True,
                "cpf": cliente.cpf,
                "cpf_informado": cliente.cpf,
                "cliente": cliente.model_dump(mode="json"),
                "auth_attempts": 0,
            },
        )

    # Conta bloqueada não é falha de credencial: o CPF e a data conferiram. Contar como
    # tentativa punia o cliente por um estado que ele não controla — e a mensagem "restam
    # 2 tentativas" ainda o convidava a repetir a mesma data correta, sem chance de dar
    # certo. Encerra aqui, porque o atendimento automático não tem como prosseguir.
    if resultado.conta_bloqueada:
        return (
            interno(
                f"Os dados conferem, mas {resultado.mensagem}. Informe isso ao cliente com "
                "cordialidade e encerre. NÃO trate como erro de digitação, não peça os "
                "dados de novo e NÃO invente telefone, e-mail, site ou qualquer canal de "
                "contato: você não tem esse dado. Se ele perguntar como resolver, diga que "
                "precisa procurar o banco pelos canais oficiais dele."
            ),
            {"finished": True},
        )

    tentativas = tentativas_atuais + 1
    if tentativas >= MAX_TENTATIVAS_AUTH:
        return (
            interno(
                f"Autenticação falhou (motivo: {resultado.mensagem}). Esta era a última "
                "tentativa permitida. Com suas palavras, informe de maneira agradável que "
                "não foi possível autenticar e encerre o atendimento."
            ),
            {"auth_attempts": tentativas, "finished": True},
        )

    return (
        interno(
            f"Autenticação falhou. Motivo: {resultado.mensagem}. Restam "
            f"{MAX_TENTATIVAS_AUTH - tentativas} tentativas. Explique o motivo ao cliente "
            "com suas palavras e peça os dados novamente."
        ),
        {"auth_attempts": tentativas},
    )


def _somente_autenticado(destino: str, contexto: str) -> Handler:
    """Bloqueia o direcionamento até a autenticação — regra do enunciado."""
    seguir = make_handoff_handler(destino, contexto)

    def handler(args: dict, state: dict) -> tuple[str, dict]:
        if not state.get("authenticated"):
            return interno(INSTRUCAO_NAO_AUTENTICADO), {}
        return seguir(args, state)

    return handler


TOOLS = [verificar_cpf, autenticar_cliente, atender_credito, atender_cambio,
         encerrar_atendimento]

HANDLERS: dict[str, Handler] = {
    "verificar_cpf": _handler_verificar_cpf,
    "autenticar_cliente": _handler_autenticar,
    "atender_credito": _somente_autenticado("credito", "crédito"),
    "atender_cambio": _somente_autenticado("cambio", "câmbio"),
    "encerrar_atendimento": handler_encerrar,
}


def node(state: dict) -> Command[Literal["credito", "cambio", "__end__"]]:
    """Executa um turno da triagem e roteia para o destino do handoff."""
    updates, destino = run_agent_turn(state, NOME, PROMPT_TRIAGEM, TOOLS, HANDLERS)
    return Command(goto=destino or END, update=updates)
