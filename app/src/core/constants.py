"""Constantes do domínio, centralizadas para não haver números mágicos espalhados."""
from __future__ import annotations

from pathlib import Path
from typing import Final

APP_DIR: Final[Path] = Path(__file__).resolve().parents[2]
DATA_DIR: Final[Path] = APP_DIR / "data"
LOGS_DIR: Final[Path] = APP_DIR / "logs"
ENV_FILE: Final[Path] = APP_DIR.parent / ".env"

CLIENTES_CSV: Final[Path] = DATA_DIR / "clientes.csv"
SCORE_LIMITE_CSV: Final[Path] = DATA_DIR / "score_limite.csv"
SOLICITACOES_CSV: Final[Path] = DATA_DIR / "solicitacoes_aumento_limite.csv"
HISTORICO_SCORE_CSV: Final[Path] = DATA_DIR / "historico_score.csv"

HEADER_CLIENTES: Final[list[str]] = [
    "cpf", "nome", "data_nascimento", "email", "telefone", "profissao",
    "tipo_emprego", "renda_declarada", "limite_atual", "score", "status_conta",
    "data_abertura",
]

HEADER_SOLICITACOES: Final[list[str]] = [
    "cpf_cliente", "data_hora_solicitacao", "limite_atual",
    "novo_limite_solicitado", "status_pedido",
]

HEADER_HISTORICO_SCORE: Final[list[str]] = [
    "cpf_cliente", "data_hora", "score_anterior", "score_novo", "origem",
]

MAX_TENTATIVAS_AUTH: Final[int] = 3
TAMANHO_CPF: Final[int] = 11

SCORE_MINIMO: Final[int] = 0
SCORE_MAXIMO: Final[int] = 1000

PESO_RENDA: Final[int] = 30
PESO_EMPREGO: Final[dict[str, int]] = {
    "formal": 300,
    "autonomo": 200,
    "desempregado": 0,
}
PESO_DEPENDENTES: Final[dict[int, int]] = {0: 100, 1: 80, 2: 60, 3: 30}
MAX_DEPENDENTES_TABELADO: Final[int] = 3
PESO_DIVIDAS: Final[dict[bool, int]] = {True: -100, False: 100}

AGENTE_PADRAO: Final[str] = "triagem"
AGENTES: Final[tuple[str, ...]] = ("triagem", "credito", "entrevista", "cambio")
MAX_ITERACOES_TURNO: Final[int] = 6
RECURSION_LIMIT: Final[int] = 12

MOEDA_PADRAO: Final[str] = "USD"
MOEDA_DESTINO: Final[str] = "BRL"
TIMEOUT_HTTP: Final[int] = 10

MSG_INSTABILIDADE: Final[str] = (
    "Estou com uma instabilidade no sistema neste momento. Pode tentar novamente "
    "em alguns instantes?"
)

REGEX_VAZAMENTO: Final[str] = (
    r"\b(transferir|transferind|transfer[êe]ncia|setor|departamento|"
    r"encaminh\w*|redirecion\w*|outro agente|agente de)\b"
)
