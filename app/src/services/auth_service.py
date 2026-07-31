"""Autenticação do cliente: CPF com dígitos verificadores e data em formato livre."""
from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from datetime import date

from src.core.constants import JANELA_THROTTLE, MAX_FALHAS_POR_CPF, TAMANHO_CPF
from src.core.logging import get_logger
from src.core.utils import apenas_digitos, cpf_mascarado, normalizar
from src.domain.results import ResultadoAuth
from src.repositories.base import RepositoryError
from src.repositories.clientes import ClienteRepository

logger = get_logger(__name__)

DATA_MINIMA = date(1900, 1, 1)

_MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def validar_cpf(cpf: str) -> bool:
    """Valida o CPF pelos dígitos verificadores (módulo 11)."""
    d = apenas_digitos(cpf)
    if len(d) != TAMANHO_CPF or len(set(d)) == 1:
        return False

    digitos = [int(c) for c in d]
    for posicao in (9, 10):
        soma = sum(digitos[i] * (posicao + 1 - i) for i in range(posicao))
        resto = (soma * 10) % 11
        esperado = 0 if resto == 10 else resto
        if digitos[posicao] != esperado:
            return False
    return True


def parse_data(texto: str) -> date | None:
    """Interpreta a data de nascimento em formato livre."""
    if not texto:
        return None
    t = normalizar(texto)

    for nome, mes in _MESES.items():
        if nome in t:
            numeros = re.findall(r"\d+", t)
            # O ano precisa ter 4 dígitos. Tomar "o último número da frase" faz
            # "14 de maio de 1990 às 10h" virar o ano 10 — e o pivô de dois dígitos
            # expande para 2010: uma data errada e plausível, pior que devolver None.
            anos = [n for n in numeros if len(n) == 4]
            if not anos or not numeros:
                return None
            return _montar(int(anos[-1]), mes, int(numeros[0]))

    numeros = re.findall(r"\d+", t)

    if len(numeros) == 1 and len(numeros[0]) == 8:
        bloco = numeros[0]
        return _montar(int(bloco[4:]), int(bloco[2:4]), int(bloco[:2])) or _montar(
            int(bloco[:4]), int(bloco[4:6]), int(bloco[6:])
        )

    if len(numeros) != 3:
        return None

    a, b, c = (int(n) for n in numeros)
    if len(numeros[0]) == 4:
        return _montar(a, b, c)
    return _montar(c, b, a)


def _montar(ano: int, mes: int, dia: int) -> date | None:
    """Monta a data e recusa o que não pode ser um nascimento.

    O filtro de intervalo resolve de uma vez as datas futuras e o pivô arbitrário de anos
    com dois dígitos: qualquer expansão que caia fora de `[1900, hoje]` vira `None`, e o
    cliente recebe "não consegui entender a data" em vez de uma falha de conferência.
    """
    if ano < 100:
        ano += 1900 if ano > 30 else 2000
    try:
        montada = date(ano, mes, dia)
    except ValueError:
        return None
    return montada if DATA_MINIMA <= montada <= date.today() else None


FALHA_DE_CREDENCIAL = "os dados informados não conferem com nosso cadastro"
EXCESSO_DE_TENTATIVAS = (
    "houve tentativas demais para este CPF nos últimos minutos; aguarde um pouco antes "
    "de tentar novamente"
)


class ThrottleDeAutenticacao:
    """Janela deslizante de tentativas falhas por CPF.

    Em memória, por processo — suficiente para a UI Streamlit e coerente com o resto da
    persistência do projeto. Num sistema real isso viveria no Postgres que já existe.
    """

    def __init__(self, maximo: int = MAX_FALHAS_POR_CPF, janela: int = JANELA_THROTTLE):
        self.maximo = maximo
        self.janela = janela
        self._falhas: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _recentes(self, cpf: str, agora: float) -> list[float]:
        return [t for t in self._falhas[cpf] if agora - t < self.janela]

    def registrar_falha(self, cpf: str) -> None:
        chave = apenas_digitos(cpf)
        agora = time.monotonic()
        with self._lock:
            self._falhas[chave] = [*self._recentes(chave, agora), agora]

    def bloqueado(self, cpf: str) -> bool:
        chave = apenas_digitos(cpf)
        agora = time.monotonic()
        with self._lock:
            recentes = self._recentes(chave, agora)
            self._falhas[chave] = recentes
            return len(recentes) >= self.maximo

    def limpar(self, cpf: str) -> None:
        with self._lock:
            self._falhas.pop(apenas_digitos(cpf), None)


_throttle = ThrottleDeAutenticacao()


def reset_throttle() -> None:
    """Zera o contador — usado em testes."""
    global _throttle
    _throttle = ThrottleDeAutenticacao()


class AuthService:
    """Autentica o cliente contra `clientes.csv`."""

    def __init__(self, cliente_repo: ClienteRepository | None = None):
        self.clientes = cliente_repo or ClienteRepository()

    def autenticar(self, cpf: str, data_nascimento: str) -> ResultadoAuth:
        if not validar_cpf(cpf):
            return ResultadoAuth(ok=False, mensagem="o CPF informado não é válido")

        # O limite de 3 tentativas do enunciado vive no estado da conversa, que o cliente
        # zera abrindo um novo atendimento. Este contador é por CPF e por janela de tempo:
        # é a dimensão que ele não controla.
        if _throttle.bloqueado(cpf):
            logger.warning("CPF %s bloqueado por excesso de tentativas.", cpf_mascarado(cpf))
            return ResultadoAuth(ok=False, mensagem=EXCESSO_DE_TENTATIVAS)

        data = parse_data(data_nascimento)
        if data is None:
            return ResultadoAuth(
                ok=False,
                mensagem="não consegui entender a data de nascimento informada",
            )

        try:
            cliente = self.clientes.buscar_por_cpf(cpf)
        except RepositoryError as exc:
            logger.error("Falha ao ler a base de clientes durante autenticação: %s", exc)
            return ResultadoAuth(
                ok=False,
                mensagem="não consegui consultar a base de clientes neste momento",
            )

        # Mensagem única para "sem cadastro" e "data não confere". Distinguir as duas
        # transforma o atendimento num oráculo de existência de cadastro: basta variar o
        # CPF e ler a resposta para enumerar quem é cliente do banco. O motivo exato fica
        # no log, onde serve para diagnóstico sem virar canal lateral.
        if cliente is None or cliente.data_nascimento != data:
            motivo = "sem cadastro" if cliente is None else "data divergente"
            logger.info(
                "Falha de autenticação para %s: %s", cpf_mascarado(cpf), motivo
            )
            _throttle.registrar_falha(cpf)
            return ResultadoAuth(ok=False, mensagem=FALHA_DE_CREDENCIAL)

        # O status da conta só é revelado depois de a credencial conferir — quem chega
        # aqui já provou conhecer a data de nascimento.
        if not cliente.conta_ativa:
            return ResultadoAuth(
                ok=False,
                mensagem=(
                    f"a conta está com status '{cliente.status_conta.value}' e não permite "
                    "atendimento automático"
                ),
            )

        _throttle.limpar(cpf)
        return ResultadoAuth(ok=True, cliente=cliente)
