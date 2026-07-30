"""Validação de CPF, parsing de data em formato livre e autenticação."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.repositories.clientes import ClienteRepository
from src.services.auth_service import AuthService, parse_data, validar_cpf
from tests.conftest import CPF_ANA, CPF_FELIPE


class TestValidarCpf:
    @pytest.mark.parametrize(
        "cpf",
        ["11144477735", "111.444.777-35", "22255588846", "33366699957", "12345678909"],
    )
    def test_cpfs_validos(self, cpf: str):
        assert validar_cpf(cpf) is True

    @pytest.mark.parametrize(
        "cpf",
        [
            "11144477700",   # dígitos verificadores errados
            "1114447773",    # curto demais
            "111444777351",  # longo demais
            "11111111111",   # todos iguais
            "",
            "abcdefghijk",
        ],
    )
    def test_cpfs_invalidos(self, cpf: str):
        assert validar_cpf(cpf) is False


class TestParseData:
    @pytest.mark.parametrize(
        "texto",
        [
            "14/05/1990", "14-05-1990", "14 05 1990", "14051990",
            "1990-05-14", "14 de maio de 1990", "14.05.1990",
        ],
    )
    def test_formatos_aceitos(self, texto: str):
        assert parse_data(texto) == date(1990, 5, 14)

    @pytest.mark.parametrize("texto", ["", "abc", "00000000", "32/13/1990", "1990"])
    def test_formatos_rejeitados(self, texto: str):
        assert parse_data(texto) is None

    def test_ano_com_dois_digitos(self):
        assert parse_data("14/05/90") == date(1990, 5, 14)


class TestAuthService:
    def test_autentica_cliente_valido(self, cliente_repo: ClienteRepository):
        resultado = AuthService(cliente_repo).autenticar(CPF_ANA, "14/05/1990")
        assert resultado.ok
        assert resultado.cliente is not None
        assert resultado.cliente.primeiro_nome == "Ana"

    def test_aceita_cpf_pontuado_e_data_por_extenso(self, cliente_repo: ClienteRepository):
        resultado = AuthService(cliente_repo).autenticar(
            "111.444.777-35", "14 de maio de 1990"
        )
        assert resultado.ok

    def test_recusa_cpf_invalido(self, cliente_repo: ClienteRepository):
        resultado = AuthService(cliente_repo).autenticar("11144477700", "14/05/1990")
        assert not resultado.ok
        assert "não é válido" in resultado.mensagem

    def test_recusa_data_ilegivel(self, cliente_repo: ClienteRepository):
        resultado = AuthService(cliente_repo).autenticar(CPF_ANA, "abc")
        assert not resultado.ok
        assert "data de nascimento" in resultado.mensagem

    def test_recusa_cpf_sem_cadastro(self, cliente_repo: ClienteRepository):
        resultado = AuthService(cliente_repo).autenticar("52998224725", "14/05/1990")
        assert not resultado.ok
        assert "não encontrei" in resultado.mensagem

    def test_recusa_data_que_nao_confere(self, cliente_repo: ClienteRepository):
        resultado = AuthService(cliente_repo).autenticar(CPF_ANA, "15/05/1990")
        assert not resultado.ok
        assert "não confere" in resultado.mensagem

    def test_recusa_conta_bloqueada(self, cliente_repo: ClienteRepository):
        resultado = AuthService(cliente_repo).autenticar(CPF_FELIPE, "08/09/1988")
        assert not resultado.ok
        assert "bloqueada" in resultado.mensagem

    def test_csv_ausente_nao_levanta_excecao(self, tmp_path: Path):
        """Falha de leitura vira mensagem controlada — o atendimento não quebra."""
        servico = AuthService(ClienteRepository(tmp_path / "inexistente.csv"))
        resultado = servico.autenticar(CPF_ANA, "14/05/1990")
        assert not resultado.ok
        assert "base de clientes" in resultado.mensagem
