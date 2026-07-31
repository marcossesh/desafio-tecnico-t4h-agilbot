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
# Limite por CPF, em dimensão que o cliente não controla: o contador do enunciado vive no
# estado da conversa e zera ao abrir um novo atendimento.
MAX_FALHAS_POR_CPF: Final[int] = 6
JANELA_THROTTLE: Final[int] = 300  # segundos
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

# Janela curta: dois cliques ou dois turnos seguidos com o mesmo valor são o mesmo
# pedido; repetir depois disso é intenção legítima e merece registro próprio.
JANELA_IDEMPOTENCIA: Final[int] = 60  # segundos

MOEDA_PADRAO: Final[str] = "USD"
MOEDA_DESTINO: Final[str] = "BRL"
TIMEOUT_HTTP: Final[int] = 10

MSG_ATENDIMENTO_ENCERRADO: Final[str] = (
    "Este atendimento já foi encerrado. Para uma nova solicitação, inicie um novo "
    "atendimento — será um prazer ajudar."
)

MSG_INSTABILIDADE: Final[str] = (
    "Estou com uma instabilidade no sistema neste momento. Pode tentar novamente "
    "em alguns instantes?"
)

# O vazamento é sobre *pessoas e áreas*, não sobre movimentação de dinheiro. A versão
# anterior casava a palavra "transferência" isolada — e o próprio `tarifas.md` tem uma
# seção "Transferências" com o TED a R$ 8,50. Dois artefatos corretos em separado que
# eram incompatíveis juntos: o prompt empurrava o modelo a evitar o termo certo, e o
# painel de diagnóstico acusava vazamento em resposta legítima.
REGEX_VAZAMENTO: Final[str] = (
    r"\b(?:transferir|transferindo|transfer[êe]ncia)\s+"
    r"(?:voc[êe]|o\s+senhor|a\s+senhora|seu\s+atendimento|"
    r"para\s+(?:o|a)\s+(?:setor|departamento|equipe|atendente|agente))\b"
    r"|\b(?:outro\s+(?:agente|atendente|setor|departamento)|"
    r"setor\s+de\s+\w+|departamento\s+de\s+\w+|"
    r"encaminh\w*\s+(?:voc[êe]|o\s+senhor|a\s+senhora|para)|"
    r"redirecion\w*\s+(?:voc[êe]|o\s+senhor|a\s+senhora|para))\b"
)
