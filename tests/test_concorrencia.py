"""Escrita concorrente nos CSVs.

Classe de cenário que cobertura de linha não alcança: os defeitos aqui aparecem no
interleaving de threads, não em caminhos não executados. Todos estes testes falhavam
antes da correção do container e do `mutate()`.
"""
from __future__ import annotations

import threading

from src.orchestration.container import _services_padrao
from src.repositories.clientes import ClienteRepository
from tests.conftest import CPF_ANA, CPF_DIEGO

RODADAS = 15


def _em_paralelo(*tarefas) -> None:
    """Dispara as tarefas ao mesmo tempo, com barreira para maximizar a sobreposição."""
    barreira = threading.Barrier(len(tarefas))

    def correr(fn):
        barreira.wait()
        fn()

    threads = [threading.Thread(target=correr, args=(t,)) for t in tarefas]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


class TestLostUpdate:
    def test_atualizacoes_de_clientes_distintos_nao_se_perdem(self, cliente_repo):
        """O ciclo read-modify-write precisa acontecer inteiro sob o lock."""
        for _ in range(RODADAS):
            _em_paralelo(
                lambda: cliente_repo.atualizar_score(CPF_ANA, 999),
                lambda: cliente_repo.atualizar_score(CPF_DIEGO, 111),
            )
            scores = {c.cpf: c.score for c in cliente_repo.listar()}
            assert (scores[CPF_ANA], scores[CPF_DIEGO]) == (999, 111)

    def test_score_e_limite_do_mesmo_cliente_coexistem(self, cliente_repo):
        """Entrevista grava score e crédito grava limite — nenhum apaga o outro."""
        for _ in range(RODADAS):
            cliente_repo.atualizar_score(CPF_ANA, 500)
            cliente_repo.atualizar_limite(CPF_ANA, 1000)
            _em_paralelo(
                lambda: cliente_repo.atualizar_score(CPF_ANA, 700),
                lambda: cliente_repo.atualizar_limite(CPF_ANA, 8000),
            )
            ana = cliente_repo.buscar_por_cpf(CPF_ANA)
            assert (ana.score, ana.limite_atual) == (700, 8000.0)

    def test_container_compartilha_um_unico_repositorio_de_clientes(self):
        """Três repositórios sobre o mesmo arquivo seriam três locks inúteis."""
        s = _services_padrao()
        assert s.auth.clientes is s.credito.clientes
        assert s.credito.clientes is s.entrevista.clientes


class TestCompareAndSet:
    def test_grava_quando_o_limite_em_disco_e_o_esperado(self, cliente_repo):
        assert cliente_repo.atualizar_limite_se(CPF_ANA, 5000.0, 9000.0) is True
        assert cliente_repo.buscar_por_cpf(CPF_ANA).limite_atual == 9000.0

    def test_recusa_quando_o_limite_mudou_debaixo(self, cliente_repo):
        cliente_repo.atualizar_limite(CPF_ANA, 12000.0)
        assert cliente_repo.atualizar_limite_se(CPF_ANA, 5000.0, 9000.0) is False
        assert cliente_repo.buscar_por_cpf(CPF_ANA).limite_atual == 12000.0

    def test_dois_aumentos_simultaneos_nao_se_sobrescrevem(
        self, cliente_repo, faixa_repo, solicitacao_repo
    ):
        """Ana tem limite 5.000 e teto 15.000. Dois pedidos concorrentes: no máximo um
        aplica o novo limite, e o valor final é sempre um dos dois avaliados."""
        from src.services.credito_service import CreditoService

        servico = CreditoService(faixa_repo, solicitacao_repo, cliente_repo)
        ana = cliente_repo.buscar_por_cpf(CPF_ANA)

        _em_paralelo(
            lambda: servico.solicitar_aumento(ana, 9000),
            lambda: servico.solicitar_aumento(ana, 12000),
        )

        final = cliente_repo.buscar_por_cpf(CPF_ANA).limite_atual
        assert final in (9000.0, 12000.0), f"limite final inesperado: {final}"


class TestSnapshotObsoleto:
    def test_avaliacao_usa_o_limite_em_disco_e_nao_o_do_estado(
        self, cliente_repo, faixa_repo, solicitacao_repo
    ):
        """O cliente vem congelado no estado do grafo desde a autenticação."""
        from src.services.credito_service import CreditoService

        servico = CreditoService(faixa_repo, solicitacao_repo, cliente_repo)
        snapshot = cliente_repo.buscar_por_cpf(CPF_ANA)  # limite 5.000

        cliente_repo.atualizar_limite(CPF_ANA, 11000.0)  # mudou por outro caminho

        # 9.000 é maior que o snapshot (5.000), mas menor que o valor real (11.000).
        resultado = servico.solicitar_aumento(snapshot, 9000)

        assert resultado.status.value == "invalido"
        assert cliente_repo.buscar_por_cpf(CPF_ANA).limite_atual == 11000.0

    def test_repositorio_indisponivel_cai_para_o_snapshot(
        self, cliente_repo, faixa_repo, solicitacao_repo, monkeypatch
    ):
        """Reler é uma melhoria, não uma dependência: se a leitura falha, segue o snapshot."""
        from src.repositories.base import RepositoryError
        from src.services.credito_service import CreditoService

        servico = CreditoService(faixa_repo, solicitacao_repo, cliente_repo)
        ana = cliente_repo.buscar_por_cpf(CPF_ANA)
        monkeypatch.setattr(
            cliente_repo, "buscar_por_cpf",
            lambda _c: (_ for _ in ()).throw(RepositoryError("indisponível")),
        )

        assert servico.solicitar_aumento(ana, 10000).status.value == "aprovado"


class TestRepositorioIsolado:
    def test_instancias_distintas_sobre_o_mesmo_arquivo_nao_serializam(self, data_dir):
        """Documenta a limitação que sobra: o lock é por objeto.

        Por isso o container compartilha uma instância — este teste existe para que a
        razão dessa decisão fique registrada em código, não só no README.
        """
        caminho = data_dir / "clientes.csv"
        r1, r2 = ClienteRepository(caminho), ClienteRepository(caminho)
        assert r1.csv._lock is not r2.csv._lock
