"""Retornos tipados dos serviços."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.domain.enums import StatusPedido
from src.domain.models import Cliente, SolicitacaoAumento


class ResultadoAuth(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    mensagem: str = ""
    cliente: Cliente | None = None


class ResumoLimite(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool = True
    limite_atual: float = 0.0
    score: int = 0
    limite_maximo: float | None = None
    taxa_juros_mensal: float | None = None
    mensagem: str = ""


class ResultadoAumento(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: StatusPedido
    mensagem: str
    limite_maximo: float | None = None
    taxa_juros_mensal: float | None = None
    solicitacao: SolicitacaoAumento | None = None
    linha_idx: int | None = None
    score_avaliado: int | None = None
    cliente_atualizado: Cliente | None = None

    @property
    def aprovado(self) -> bool:
        return self.status == StatusPedido.APROVADO


class ResultadoEntrevista(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    mensagem: str = ""
    score_anterior: int | None = None
    score_novo: int | None = None
    cliente_atualizado: Cliente | None = None


class ResultadoCotacao(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    mensagem: str = ""
    moeda_origem: str = ""
    moeda_destino: str = ""
    valor: float | None = None
    variacao_pct: float | None = None
    atualizado_em: str = ""


class ResultadoConhecimento(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    contexto: str = ""
    fontes: list[str] = []
