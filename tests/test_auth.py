"""Validação de CPF, parsing de data em formato livre e autenticação."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.core.constants import MAX_FALHAS_POR_CPF
from src.repositories.clientes import ClienteRepository
from src.services.auth_service import (
    EXCESSO_DE_TENTATIVAS,
    FALHA_DE_CREDENCIAL,
    AuthService,
    parse_data,
    validar_cpf,
)
from tests.conftest import CPF_ANA, CPF_DIEGO, CPF_FELIPE


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

    @pytest.mark.parametrize(
        "texto", ["14/05/90", "14 05 90", "14 de maio de 90"]
    )
    def test_ano_com_dois_digitos_vale_em_qualquer_forma(self, texto: str):
        """Aceitar dois dígitos na forma numérica e recusar na textual era arbitrário.

        `14/05/90` sempre funcionou; `14 de maio de 90` não — mesma ambiguidade, dois
        comportamentos. Era resíduo da regra que exigia 4 dígitos no ramo textual.
        """
        assert parse_data(texto) == date(1990, 5, 14)

    def test_numero_extra_na_frase_nao_vira_ano(self):
        """O bug que motivou a regra dos 4 dígitos: o último número virava o ano.

        "às 10h" fazia a data virar 2010 — errada, plausível, e consumindo uma tentativa
        de autenticação sem o cliente entender por quê.
        """
        assert parse_data("14 de maio de 1990 as 10h") == date(1990, 5, 14)

    def test_dois_digitos_com_numero_extra_e_ambiguo_demais(self):
        """Sem um ano de 4 dígitos para ancorar, três números não têm leitura segura."""
        assert parse_data("14 de maio de 90 as 10h") is None


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
        assert resultado.mensagem == FALHA_DE_CREDENCIAL

    def test_recusa_data_que_nao_confere(self, cliente_repo: ClienteRepository):
        resultado = AuthService(cliente_repo).autenticar(CPF_ANA, "15/05/1990")
        assert not resultado.ok
        assert resultado.mensagem == FALHA_DE_CREDENCIAL

    def test_falha_nao_distingue_cpf_inexistente_de_data_errada(
        self, cliente_repo: ClienteRepository
    ):
        """Mensagens distintas fariam do atendimento um oráculo de existência de cadastro:
        bastaria variar o CPF e ler a resposta para enumerar os clientes do banco."""
        servico = AuthService(cliente_repo)

        sem_cadastro = servico.autenticar("52998224725", "01/01/1900")
        data_errada = servico.autenticar(CPF_ANA, "01/01/1900")

        assert sem_cadastro.mensagem == data_errada.mensagem

    def test_status_da_conta_so_e_revelado_apos_a_data_conferir(
        self, cliente_repo: ClienteRepository
    ):
        servico = AuthService(cliente_repo)

        com_data_errada = servico.autenticar(CPF_FELIPE, "01/01/1900")
        com_data_certa = servico.autenticar(CPF_FELIPE, "08/09/1988")

        assert com_data_errada.mensagem == FALHA_DE_CREDENCIAL
        assert "bloqueada" in com_data_certa.mensagem

    def test_recusa_conta_bloqueada(self, cliente_repo: ClienteRepository):
        resultado = AuthService(cliente_repo).autenticar(CPF_FELIPE, "08/09/1988")
        assert not resultado.ok
        assert "bloqueada" in resultado.mensagem

    def test_conta_bloqueada_e_sinalizada_a_parte(self, cliente_repo: ClienteRepository):
        """Distinguir de falha de credencial é o que impede consumir tentativa à toa."""
        servico = AuthService(cliente_repo)

        bloqueada = servico.autenticar(CPF_FELIPE, "08/09/1988")
        credencial_errada = servico.autenticar(CPF_FELIPE, "01/01/1900")

        assert bloqueada.conta_bloqueada is True
        assert credencial_errada.conta_bloqueada is False

    def test_csv_ausente_nao_levanta_excecao(self, tmp_path: Path):
        """Falha de leitura vira mensagem controlada — o atendimento não quebra."""
        servico = AuthService(ClienteRepository(tmp_path / "inexistente.csv"))
        resultado = servico.autenticar(CPF_ANA, "14/05/1990")
        assert not resultado.ok
        assert "base de clientes" in resultado.mensagem


class TestThrottlePorCpf:
    """O limite de 3 tentativas do enunciado vive no estado da conversa, que o cliente
    zera abrindo um novo atendimento. Este contador é por CPF e por janela de tempo."""

    def test_bloqueia_apos_falhas_repetidas_no_mesmo_cpf(self, cliente_repo):
        servico = AuthService(cliente_repo)
        for _ in range(MAX_FALHAS_POR_CPF):
            servico.autenticar(CPF_ANA, "01/01/1900")

        resultado = servico.autenticar(CPF_ANA, "14/05/1990")

        assert not resultado.ok
        assert resultado.mensagem == EXCESSO_DE_TENTATIVAS

    def test_bloqueio_atravessa_sessoes_diferentes(self, cliente_repo):
        """Abrir um novo atendimento não deve zerar o contador — é a dimensão que o
        cliente controla, e por isso o limite não pode viver só ali."""
        for _ in range(MAX_FALHAS_POR_CPF):
            AuthService(cliente_repo).autenticar(CPF_ANA, "01/01/1900")

        outro_servico = AuthService(cliente_repo)
        assert outro_servico.autenticar(CPF_ANA, "14/05/1990").mensagem == EXCESSO_DE_TENTATIVAS

    def test_bloqueio_e_por_cpf_e_nao_global(self, cliente_repo):
        servico = AuthService(cliente_repo)
        for _ in range(MAX_FALHAS_POR_CPF):
            servico.autenticar(CPF_ANA, "01/01/1900")

        assert servico.autenticar(CPF_DIEGO, "19/07/1995").ok

    def test_autenticacao_bem_sucedida_zera_o_contador(self, cliente_repo):
        servico = AuthService(cliente_repo)
        for _ in range(MAX_FALHAS_POR_CPF - 1):
            servico.autenticar(CPF_ANA, "01/01/1900")

        assert servico.autenticar(CPF_ANA, "14/05/1990").ok
        for _ in range(MAX_FALHAS_POR_CPF - 1):
            servico.autenticar(CPF_ANA, "01/01/1900")
        assert servico.autenticar(CPF_ANA, "14/05/1990").ok
