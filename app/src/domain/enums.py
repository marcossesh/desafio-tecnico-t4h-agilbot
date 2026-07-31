"""Enums do domínio, com normalização da entrada em linguagem natural."""
from __future__ import annotations

from enum import StrEnum

from src.core.logging import get_logger
from src.core.utils import normalizar

logger = get_logger(__name__)


class StatusPedido(StrEnum):
    """Ciclo de vida de uma solicitação de aumento de limite."""

    PENDENTE = "pendente"
    APROVADO = "aprovado"
    REJEITADO = "rejeitado"
    INVALIDO = "invalido"
    ERRO = "erro"

    @property
    def e_terminal(self) -> bool:
        return self in (StatusPedido.APROVADO, StatusPedido.REJEITADO)


class TipoEmprego(StrEnum):
    FORMAL = "formal"
    AUTONOMO = "autonomo"
    DESEMPREGADO = "desempregado"

    @classmethod
    def from_texto(cls, texto: str) -> TipoEmprego:
        """Mapeia texto livre para o tipo canônico. Levanta ValueError se não reconhecer."""
        t = normalizar(texto)
        if not t:
            raise ValueError("tipo de emprego não informado")

        for tipo, sinonimos in _SINONIMOS_EMPREGO.items():
            if any(s in t for s in sinonimos):
                return tipo
        raise ValueError(
            f"tipo de emprego não reconhecido: {texto!r} "
            "(use formal, autônomo ou desempregado)"
        )


# O enunciado define três categorias, mas o cliente responde com a palavra dele. Rejeitar
# "aposentado" ou "sou empregado" deixa a entrevista em beco sem saída, porque o prompt
# manda repreguntar só aquele campo e o cliente repete a mesma formulação.
#
# A ordem do dicionário importa: "desempregad" precisa ser avaliado antes de "empregad",
# que está em FORMAL. O teste `test_desempregado_nao_e_confundido_com_formal` protege isso.
#
# Aposentadoria e pensão entram em FORMAL por serem renda estável e comprovável — a
# decisão está registrada aqui porque é de produto, não de implementação.
_SINONIMOS_EMPREGO: dict[TipoEmprego, tuple[str, ...]] = {
    TipoEmprego.DESEMPREGADO: (
        "desempregad", "sem emprego", "sem trabalho", "nao trabalho", "sem renda",
        "do lar", "dona de casa", "estudante", "bolsista", "estagi", "procurando",
    ),
    TipoEmprego.AUTONOMO: (
        "autonom", "pj", "freelan", "empresari", "empreendedor", "mei",
        "por conta", "informal", "liberal", "diarist", "bico", "temporari",
        "comission", "vendedor", "motorista de aplicativo",
    ),
    TipoEmprego.FORMAL: (
        "formal", "clt", "carteira", "assalariad", "efetiv", "funcionari",
        "empregad", "registrad", "servidor", "concursad", "militar",
        "aposentad", "pensionist", "inss",
    ),
}


class StatusConta(StrEnum):
    ATIVA = "ativa"
    BLOQUEADA = "bloqueada"
    ENCERRADA = "encerrada"

    @classmethod
    def from_texto(cls, texto: str) -> StatusConta:
        """Valor desconhecido vira BLOQUEADA (*fail-closed*), mas com rastro no log.

        Manter o *fail-closed* é a escolha certa de segurança. O que faltava era
        distinguir um bloqueio real de uma célula vazia no CSV: sem o aviso, um dado
        faltando tira o cliente do ar e não deixa pista nenhuma.
        """
        t = normalizar(texto)
        for status in cls:
            if status.value == t:
                return status
        logger.warning(
            "status_conta %r não reconhecido; assumindo BLOQUEADA (fail-closed)", texto
        )
        return cls.BLOQUEADA


# Comparação por palavra inteira: um vocabulário curto demais transforma "estou sem
# dívidas" num erro, e o cliente tende a repetir a mesma formulação quando reperguntado.
_AFIRMATIVAS = (
    "sim", "s", "tenho", "possuo", "yes", "y", "verdadeiro", "true", "1",
    "positivo", "afirmativo", "claro", "isso", "algumas", "varias", "muitas",
)
_NEGATIVAS = (
    "nao", "n", "nenhuma", "nenhum", "no", "falso", "false", "0",
    "zero", "nada", "nunca", "negativo", "livre", "quitado", "quitei", "limpo",
)
# "sem" só é conclusivo em resposta curta ("sem dívidas"); numa frase longa pode aparecer
# em outro papel, e aí a precedência normal por palavra decide.
_MAX_PALAVRAS_PARA_SEM = 4


def texto_para_booleano(texto: str | bool) -> bool:
    """Interpreta 'sim'/'não' e variantes. Levanta ValueError quando ambíguo."""
    if isinstance(texto, bool):
        return texto

    t = normalizar(texto)
    if not t:
        raise ValueError("resposta não informada")
    lista = t.replace("-", " ").split()
    palavras = set(lista)

    # Negativa vence: "não tenho dívidas" tem "tenho", mas a resposta é não.
    if palavras & set(_NEGATIVAS):
        return False
    if palavras & set(_AFIRMATIVAS):
        return True
    if "sem" in palavras and len(lista) <= _MAX_PALAVRAS_PARA_SEM:
        return False
    raise ValueError(f"não entendi a resposta {texto!r} (responda sim ou não)")
