"""Injeção de contexto: o canal de memória entre turnos."""
from __future__ import annotations

from src.core.constants import MAX_TENTATIVAS_AUTH
from src.core.utils import formatar_brl, formatar_cpf
from src.domain.models import Cliente

CABECALHO = "CONTEXTO ATUAL DO ATENDIMENTO (dados do sistema, não repita como lista):"
SEM_DADOS = "- Nenhum dado coletado ainda nesta conversa."


def cliente_do_estado(state: dict) -> Cliente | None:
    """Reconstrói o modelo a partir do dict serializado no estado."""
    dados = state.get("cliente")
    if not dados:
        return None
    try:
        return Cliente(**dados)
    except (TypeError, ValueError):
        return None


def render_contexto(state: dict) -> str:
    """Renderiza o bloco de contexto que vai no system prompt deste turno."""
    linhas: list[str] = []

    cliente = cliente_do_estado(state)
    autenticado = bool(state.get("authenticated"))

    if autenticado and cliente is not None:
        linhas.append(
            f"- Cliente autenticado: {cliente.nome} (trate por {cliente.primeiro_nome})."
        )
        linhas.append(f"- CPF: {cliente.cpf_formatado}.")
        linhas.append(f"- Limite atual: {formatar_brl(cliente.limite_atual)}.")
        linhas.append(f"- Score de crédito: {cliente.score}.")
    else:
        linhas.append("- Cliente ainda NÃO autenticado.")
        cpf_informado = state.get("cpf_informado") or ""
        if cpf_informado:
            linhas.append(
                f"- O cliente JÁ informou o CPF {formatar_cpf(cpf_informado)} nesta conversa. "
                "Não peça o CPF de novo: peça a data de nascimento (se ainda não tiver) e "
                "chame a ferramenta de autenticação."
            )
        tentativas = int(state.get("auth_attempts", 0) or 0)
        if tentativas:
            restantes = max(MAX_TENTATIVAS_AUTH - tentativas, 0)
            linhas.append(
                f"- Tentativas de autenticação usadas: {tentativas} de {MAX_TENTATIVAS_AUTH} "
                f"(restam {restantes})."
            )

    ultima = state.get("ultima_solicitacao") or {}
    if ultima:
        valor = formatar_brl(float(ultima.get("valor_solicitado", 0)))
        linhas.append(
            f"- Último pedido de aumento: {valor}, status {ultima.get('status', '?')} "
            f"(avaliado com score {ultima.get('score_avaliado', '?')})."
        )

    if state.get("entrevista_concluida"):
        linhas.append(
            "- A entrevista financeira JÁ FOI CONCLUÍDA nesta conversa e o score acima "
            "já é o recalculado. NÃO inicie nem ofereça outra entrevista: os dados "
            "financeiros que aparecem na conversa são as respostas dela, não dados novos "
            "para registrar. Apenas comunique o resultado do pedido ao cliente."
        )
    elif state.get("entrevista_oferecida"):
        linhas.append(
            "- A entrevista financeira JÁ foi oferecida ao cliente nesta conversa. "
            "Não ofereça de novo se ele já recusou."
        )

    corpo = "\n".join(linhas) if linhas else SEM_DADOS
    return f"{CABECALHO}\n{corpo}"
