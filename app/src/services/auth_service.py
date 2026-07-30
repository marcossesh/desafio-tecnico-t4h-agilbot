"""Autenticação do cliente: CPF com dígitos verificadores e data em formato livre."""
from __future__ import annotations

import re
from datetime import date

from src.core.constants import TAMANHO_CPF
from src.core.logging import get_logger
from src.core.utils import apenas_digitos, normalizar
from src.domain.results import ResultadoAuth
from src.repositories.base import RepositoryError
from src.repositories.clientes import ClienteRepository

logger = get_logger(__name__)

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
            if len(numeros) >= 2:
                dia, ano = int(numeros[0]), int(numeros[-1])
                return _montar(ano, mes, dia)
            return None

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
    if ano < 100:
        ano += 1900 if ano > 30 else 2000
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


class AuthService:
    """Autentica o cliente contra `clientes.csv`."""

    def __init__(self, cliente_repo: ClienteRepository | None = None):
        self.clientes = cliente_repo or ClienteRepository()

    def autenticar(self, cpf: str, data_nascimento: str) -> ResultadoAuth:
        if not validar_cpf(cpf):
            return ResultadoAuth(ok=False, mensagem="o CPF informado não é válido")

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

        if cliente is None:
            return ResultadoAuth(ok=False, mensagem="não encontrei um cadastro com esse CPF")

        if cliente.data_nascimento != data:
            return ResultadoAuth(
                ok=False, mensagem="a data de nascimento não confere com o cadastro"
            )

        if not cliente.conta_ativa:
            return ResultadoAuth(
                ok=False,
                mensagem=(
                    f"a conta está com status '{cliente.status_conta.value}' e não permite "
                    "atendimento automático"
                ),
            )

        return ResultadoAuth(ok=True, cliente=cliente)
