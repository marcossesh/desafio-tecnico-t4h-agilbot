"""Modelos do domínio em Pydantic. Puros: validam e serializam, não fazem I/O."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.constants import SCORE_MAXIMO, SCORE_MINIMO
from src.core.logging import get_logger
from src.core.utils import apenas_digitos, formatar_cpf, parse_valor_monetario
from src.domain.enums import StatusConta, StatusPedido, TipoEmprego, texto_para_booleano

logger = get_logger(__name__)


class Cliente(BaseModel):
    """Uma linha de `clientes.csv`, já tipada."""

    model_config = ConfigDict(frozen=True)

    cpf: str
    nome: str
    data_nascimento: date
    email: str = ""
    telefone: str = ""
    profissao: str = ""
    tipo_emprego: TipoEmprego = TipoEmprego.FORMAL
    renda_declarada: float = 0.0
    limite_atual: float = 0.0
    score: int = 0
    status_conta: StatusConta = StatusConta.ATIVA
    data_abertura: date | None = None

    @field_validator("cpf", mode="before")
    @classmethod
    def _somente_digitos(cls, v: str) -> str:
        return apenas_digitos(v)

    @field_validator("tipo_emprego", mode="before")
    @classmethod
    def _emprego(cls, v: str) -> str | TipoEmprego:
        """Cadastro com emprego irreconhecível não pode apagar a identidade do cliente.

        Se este validador levantasse, o Pydantic embrulharia em `ValidationError`, o
        repositório descartaria a linha inteira, e autenticar devolveria "não encontrei
        um cadastro com esse CPF" — reportando dado inválido como cliente inexistente.
        O campo só pesa no score da entrevista, então o default com aviso é o correto.
        """
        if not isinstance(v, str):
            return v
        try:
            return TipoEmprego.from_texto(v)
        except ValueError:
            logger.warning("tipo_emprego %r não reconhecido; assumindo FORMAL", v)
            return TipoEmprego.FORMAL

    @field_validator("status_conta", mode="before")
    @classmethod
    def _status(cls, v: str) -> str | StatusConta:
        return StatusConta.from_texto(v) if isinstance(v, str) else v

    @field_validator("score", mode="before")
    @classmethod
    def _score_na_escala(cls, v: object) -> int:
        """Ajusta o score ao intervalo em vez de invalidar a linha.

        `Field(ge=…, le=…)` seria o reflexo — e o errado: um score 1500 (digitação ou
        escala FICO) viraria `ValidationError` e o cliente sumiria da base. Trocaria um
        cliente sem crédito por um cliente sem cadastro.
        """
        try:
            score = int(float(v or 0))
        except (TypeError, ValueError):
            logger.warning("score %r ilegível; assumindo %d", v, SCORE_MINIMO)
            return SCORE_MINIMO
        if not SCORE_MINIMO <= score <= SCORE_MAXIMO:
            logger.warning(
                "score %s fora de [%d, %d]; ajustado ao limite da escala",
                score, SCORE_MINIMO, SCORE_MAXIMO,
            )
            return min(max(score, SCORE_MINIMO), SCORE_MAXIMO)
        return score

    @field_validator("limite_atual", "renda_declarada", mode="before")
    @classmethod
    def _valor_nao_negativo(cls, v: object) -> float:
        try:
            valor = float(v or 0)
        except (TypeError, ValueError):
            return 0.0
        if valor < 0:
            logger.warning("valor monetário negativo no cadastro (%s); assumindo 0", v)
            return 0.0
        return valor

    @property
    def primeiro_nome(self) -> str:
        return self.nome.split()[0] if self.nome else ""

    @property
    def cpf_formatado(self) -> str:
        return formatar_cpf(self.cpf)

    @property
    def conta_ativa(self) -> bool:
        return self.status_conta == StatusConta.ATIVA


class FaixaScore(BaseModel):
    """Uma linha de `score_limite.csv`: a política de crédito por faixa."""

    model_config = ConfigDict(frozen=True)

    score_min: int
    score_max: int
    limite_maximo: float
    taxa_juros_mensal: float

    def contem(self, score: int) -> bool:
        return self.score_min <= score <= self.score_max


class SolicitacaoAumento(BaseModel):
    """Pedido formal de aumento — exatamente as 5 colunas exigidas pelo enunciado."""

    cpf_cliente: str
    data_hora_solicitacao: datetime = Field(default_factory=datetime.now)
    limite_atual: float
    novo_limite_solicitado: float
    status_pedido: StatusPedido = StatusPedido.PENDENTE

    @field_validator("cpf_cliente", mode="before")
    @classmethod
    def _somente_digitos(cls, v: str) -> str:
        return apenas_digitos(v)

    def para_csv(self) -> dict[str, str]:
        """Serializa na ordem e no formato do CSV (timestamp em ISO 8601)."""
        return {
            "cpf_cliente": self.cpf_cliente,
            "data_hora_solicitacao": self.data_hora_solicitacao.isoformat(),
            "limite_atual": f"{self.limite_atual:.2f}",
            "novo_limite_solicitado": f"{self.novo_limite_solicitado:.2f}",
            "status_pedido": self.status_pedido.value,
        }


class RegistroScore(BaseModel):
    """Uma mudança de score, para a trilha de auditoria."""

    model_config = ConfigDict(frozen=True)

    cpf_cliente: str
    score_anterior: int
    score_novo: int
    data_hora: datetime = Field(default_factory=datetime.now)
    origem: str = "entrevista"

    @field_validator("cpf_cliente", mode="before")
    @classmethod
    def _somente_digitos(cls, v: str) -> str:
        return apenas_digitos(v)

    def para_csv(self) -> dict[str, str]:
        return {
            "cpf_cliente": self.cpf_cliente,
            "data_hora": self.data_hora.isoformat(),
            "score_anterior": str(self.score_anterior),
            "score_novo": str(self.score_novo),
            "origem": self.origem,
        }


class DadosEntrevista(BaseModel):
    """Os 5 dados coletados na entrevista, já normalizados e validados."""

    model_config = ConfigDict(frozen=True)

    renda_mensal: float = Field(ge=0)
    tipo_emprego: TipoEmprego
    despesas_fixas: float = Field(ge=0)
    num_dependentes: int = Field(ge=0)
    tem_dividas: bool

    @field_validator("tipo_emprego", mode="before")
    @classmethod
    def _emprego(cls, v: str) -> str | TipoEmprego:
        return TipoEmprego.from_texto(v) if isinstance(v, str) else v

    @field_validator("tem_dividas", mode="before")
    @classmethod
    def _dividas(cls, v: str | bool) -> bool:
        return texto_para_booleano(v)

    @field_validator("renda_mensal", "despesas_fixas", mode="before")
    @classmethod
    def _valor(cls, v: str | float) -> float:
        """O cliente informa como quiser: '4200', 'R$ 4.200', '4.200,50', '10 mil', '10k'."""
        return parse_valor_monetario(v)
