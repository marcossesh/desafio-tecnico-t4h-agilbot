"""Enums do domínio, com normalização da entrada em linguagem natural."""
from __future__ import annotations

from enum import StrEnum

from src.core.utils import normalizar


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


_SINONIMOS_EMPREGO: dict[TipoEmprego, tuple[str, ...]] = {
    TipoEmprego.DESEMPREGADO: ("desempregad", "sem emprego", "sem trabalho", "nao trabalho"),
    TipoEmprego.AUTONOMO: (
        "autonom", "pj", "freelan", "empresari", "empreendedor", "mei",
        "por conta", "informal", "liberal",
    ),
    TipoEmprego.FORMAL: ("formal", "clt", "carteira", "assalariad", "efetiv", "funcionari"),
}


class StatusConta(StrEnum):
    ATIVA = "ativa"
    BLOQUEADA = "bloqueada"
    ENCERRADA = "encerrada"

    @classmethod
    def from_texto(cls, texto: str) -> StatusConta:
        t = normalizar(texto)
        for status in cls:
            if status.value == t:
                return status
        return cls.BLOQUEADA


_AFIRMATIVAS = ("sim", "s", "tenho", "possuo", "yes", "y", "verdadeiro", "true", "1")
_NEGATIVAS = ("nao", "n", "nenhuma", "nenhum", "no", "falso", "false", "0")


def texto_para_booleano(texto: str | bool) -> bool:
    """Interpreta 'sim'/'não' e variantes. Levanta ValueError quando ambíguo."""
    if isinstance(texto, bool):
        return texto

    t = normalizar(texto)
    if not t:
        raise ValueError("resposta não informada")
    palavras = set(t.replace("-", " ").split())
    if palavras & set(_NEGATIVAS):
        return False
    if palavras & set(_AFIRMATIVAS):
        return True
    raise ValueError(f"não entendi a resposta {texto!r} (responda sim ou não)")
