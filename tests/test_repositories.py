"""Camada de dados: escrita atômica, índices de linha e erros controlados."""
from __future__ import annotations

import csv
import itertools
from pathlib import Path

import pytest

from src.core.constants import HEADER_SOLICITACOES
from src.domain.enums import StatusPedido
from src.domain.models import SolicitacaoAumento
from src.repositories.base import CsvRepository, RepositoryError
from src.repositories.clientes import ClienteRepository
from src.repositories.score_limite import FaixaScoreRepository
from src.repositories.solicitacoes import SolicitacaoRepository
from tests.conftest import CPF_ANA, CPF_DIEGO


class TestEscritaAtomica:
    def test_temporario_nasce_no_mesmo_diretorio_do_alvo(self, tmp_path: Path, monkeypatch):
        """Sob bind mount do Docker, um temporário em /tmp faria `os.replace` levantar
        `Invalid cross-device link`. O teste fixa o invariante que evita isso."""
        alvo = tmp_path / "sub" / "arquivo.csv"
        alvo.parent.mkdir()
        vistos: list[str] = []

        import tempfile as _tempfile

        original = _tempfile.mkstemp

        def espiao(*args, **kwargs):
            vistos.append(str(kwargs.get("dir")))
            return original(*args, **kwargs)

        monkeypatch.setattr(_tempfile, "mkstemp", espiao)

        CsvRepository(alvo, ["a", "b"]).write_dicts([{"a": "1", "b": "2"}])

        assert vistos == [str(alvo.parent)]

    def test_nao_deixa_temporario_orfao(self, tmp_path: Path):
        repo = CsvRepository(tmp_path / "x.csv", ["a"])
        repo.write_dicts([{"a": "1"}])
        assert [p.name for p in tmp_path.iterdir()] == ["x.csv"]

    def test_preserva_a_permissao_do_arquivo(self, tmp_path: Path):
        """`mkstemp` cria com 0600; sem preservar o modo, a primeira escrita mudaria a
        permissão do CSV — perceptível no host, via bind mount."""
        alvo = tmp_path / "x.csv"
        repo = CsvRepository(alvo, ["a"])
        repo.write_dicts([{"a": "1"}])
        alvo.chmod(0o644)

        repo.write_dicts([{"a": "2"}])

        assert alvo.stat().st_mode & 0o777 == 0o644

    def test_conteudo_anterior_sobrevive_a_falha_de_escrita(self, tmp_path: Path, monkeypatch):
        alvo = tmp_path / "x.csv"
        repo = CsvRepository(alvo, ["a"])
        repo.write_dicts([{"a": "original"}])

        def explode(*_args, **_kwargs):
            raise OSError("disco cheio")

        monkeypatch.setattr("src.repositories.base.os.replace", explode)
        with pytest.raises(RepositoryError):
            repo.write_dicts([{"a": "novo"}])

        assert "original" in alvo.read_text()
        assert list(tmp_path.iterdir()) == [alvo]  # temporário limpo


class TestCsvRepository:
    def test_append_devolve_indice_sequencial(self, tmp_path: Path):
        repo = CsvRepository(tmp_path / "s.csv", ["a"])
        assert repo.append_dict({"a": "primeiro"}) == 0
        assert repo.append_dict({"a": "segundo"}) == 1

    def test_update_row_substitui_a_linha_certa(self, tmp_path: Path):
        repo = CsvRepository(tmp_path / "s.csv", ["a"])
        repo.append_dict({"a": "um"})
        repo.append_dict({"a": "dois"})
        repo.update_row(0, {"a": "UM"})
        assert [linha["a"] for linha in repo.read_dicts()] == ["UM", "dois"]

    def test_update_row_fora_do_intervalo(self, tmp_path: Path):
        repo = CsvRepository(tmp_path / "s.csv", ["a"])
        with pytest.raises(RepositoryError, match="inexistente"):
            repo.update_row(5, {"a": "x"})

    def test_arquivo_ausente_vira_erro_controlado(self, tmp_path: Path):
        with pytest.raises(RepositoryError, match="não encontrado"):
            CsvRepository(tmp_path / "nada.csv", ["a"]).read_dicts()


class TestClienteRepository:
    def test_carrega_a_base_entregue(self, cliente_repo: ClienteRepository):
        assert len(cliente_repo.listar()) == 5

    def test_busca_aceita_cpf_formatado(self, cliente_repo: ClienteRepository):
        assert cliente_repo.buscar_por_cpf("111.444.777-35").primeiro_nome == "Ana"

    def test_atualiza_score_preservando_as_demais_linhas(self, cliente_repo: ClienteRepository):
        antes = {c.cpf: c.score for c in cliente_repo.listar()}
        cliente_repo.atualizar_score(CPF_DIEGO, 505)

        depois = {c.cpf: c.score for c in cliente_repo.listar()}
        assert depois[CPF_DIEGO] == 505
        assert {k: v for k, v in depois.items() if k != CPF_DIEGO} == {
            k: v for k, v in antes.items() if k != CPF_DIEGO
        }

    def test_atualiza_limite(self, cliente_repo: ClienteRepository):
        cliente_repo.atualizar_limite(CPF_ANA, 12000)
        assert cliente_repo.buscar_por_cpf(CPF_ANA).limite_atual == 12000.0

    def test_cliente_inexistente_levanta(self, cliente_repo: ClienteRepository):
        with pytest.raises(RepositoryError, match="não encontrado"):
            cliente_repo.atualizar_score("52998224725", 500)

    def test_linha_corrompida_e_ignorada_sem_derrubar_o_resto(self, data_dir: Path):
        caminho = data_dir / "clientes.csv"
        with caminho.open("a", encoding="utf-8") as f:
            f.write("nao-e-cpf,Sem Data,data-invalida,,,,,,,,,\n")

        clientes = ClienteRepository(caminho).listar()
        assert len(clientes) == 5  # as 5 válidas continuam disponíveis


class TestFaixaScoreRepository:
    @pytest.mark.parametrize(
        ("score", "limite"), [(0, 1000.0), (300, 1000.0), (380, 5000.0),
                              (505, 15000.0), (655, 50000.0), (1000, 50000.0)]
    )
    def test_faixa_por_score(self, faixa_repo: FaixaScoreRepository, score: int, limite: float):
        assert faixa_repo.faixa_para(score).limite_maximo == limite

    def test_faixas_cobrem_a_escala_sem_buraco(self, faixa_repo: FaixaScoreRepository):
        faixas = sorted(faixa_repo.listar(), key=lambda f: f.score_min)
        assert faixas[0].score_min == 0
        assert faixas[-1].score_max == 1000
        for anterior, seguinte in itertools.pairwise(faixas):
            assert seguinte.score_min == anterior.score_max + 1


class TestSolicitacaoRepository:
    def test_arquivo_ausente_lista_vazio(self, solicitacao_repo: SolicitacaoRepository):
        assert solicitacao_repo.listar() == []

    def test_registra_com_o_cabecalho_do_enunciado(self, solicitacao_repo: SolicitacaoRepository):
        solicitacao_repo.registrar(
            SolicitacaoAumento(
                cpf_cliente=CPF_DIEGO, limite_atual=800, novo_limite_solicitado=10000
            )
        )
        with solicitacao_repo.csv.path.open(encoding="utf-8") as f:
            assert next(csv.reader(f)) == HEADER_SOLICITACOES

    def test_transicao_reescreve_a_mesma_linha(self, solicitacao_repo: SolicitacaoRepository):
        pedido = SolicitacaoAumento(
            cpf_cliente=CPF_DIEGO, limite_atual=800, novo_limite_solicitado=10000
        )
        idx = solicitacao_repo.registrar(pedido)
        assert solicitacao_repo.status_da_linha(idx) == StatusPedido.PENDENTE

        solicitacao_repo.transicionar(
            idx, pedido.model_copy(update={"status_pedido": StatusPedido.REJEITADO})
        )
        assert solicitacao_repo.status_da_linha(idx) == StatusPedido.REJEITADO
        assert len(solicitacao_repo.listar()) == 1  # transicionou, não duplicou

    def test_transicao_para_estado_nao_terminal_e_recusada(
        self, solicitacao_repo: SolicitacaoRepository
    ):
        pedido = SolicitacaoAumento(
            cpf_cliente=CPF_DIEGO, limite_atual=800, novo_limite_solicitado=10000
        )
        idx = solicitacao_repo.registrar(pedido)
        with pytest.raises(RepositoryError, match="não é terminal"):
            solicitacao_repo.transicionar(idx, pedido)
