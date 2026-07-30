"""Fixtures compartilhadas.

Os testes operam sobre **cópias dos CSVs reais do projeto**, em `tmp_path`. Isso importa:
o teste de regressão do fluxo-vitrine valida os dados que serão de fato entregues, não
uma fixture paralela que poderia divergir deles.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.core.constants import CLIENTES_CSV, DATA_DIR, SCORE_LIMITE_CSV
from src.repositories.clientes import ClienteRepository
from src.repositories.historico_score import HistoricoScoreRepository
from src.repositories.score_limite import FaixaScoreRepository
from src.repositories.solicitacoes import SolicitacaoRepository

CPF_ANA = "11144477735"
CPF_DIEGO = "22255588846"
CPF_CARLA = "33366699957"
CPF_BRUNO = "12345678909"
CPF_FELIPE = "98765432100"


@pytest.fixture(autouse=True)
def _sem_escrita_em_producao():
    """Falha o teste que escrever nos CSVs reais do projeto.

    Todo repositório aceita um caminho no construtor e, nos testes, recebe um temporário.
    Esquecer de injetar um deles faz o repositório cair no caminho padrão — e o teste
    passa, escrevendo em `app/data` silenciosamente. Foi exatamente o que aconteceu ao
    introduzir o histórico de score.
    """
    antes = {p: p.read_bytes() for p in DATA_DIR.iterdir() if p.is_file()}
    yield
    depois = {p: p.read_bytes() for p in DATA_DIR.iterdir() if p.is_file()}

    criados = sorted(p.name for p in set(depois) - set(antes))
    alterados = sorted(p.name for p in set(antes) & set(depois) if antes[p] != depois[p])
    assert not criados, f"o teste criou arquivos em app/data: {criados}"
    assert not alterados, f"o teste alterou arquivos em app/data: {alterados}"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Cópia isolada dos CSVs reais — os testes podem escrever à vontade."""
    destino = tmp_path / "data"
    destino.mkdir()
    shutil.copy(CLIENTES_CSV, destino / "clientes.csv")
    shutil.copy(SCORE_LIMITE_CSV, destino / "score_limite.csv")
    return destino


@pytest.fixture
def cliente_repo(data_dir: Path) -> ClienteRepository:
    return ClienteRepository(data_dir / "clientes.csv")


@pytest.fixture
def faixa_repo(data_dir: Path) -> FaixaScoreRepository:
    return FaixaScoreRepository(data_dir / "score_limite.csv")


@pytest.fixture
def solicitacao_repo(data_dir: Path) -> SolicitacaoRepository:
    return SolicitacaoRepository(data_dir / "solicitacoes_aumento_limite.csv")


@pytest.fixture
def historico_repo(data_dir: Path) -> HistoricoScoreRepository:
    return HistoricoScoreRepository(data_dir / "historico_score.csv")


@pytest.fixture
def servicos(cliente_repo, faixa_repo, solicitacao_repo, historico_repo):
    """Injeta serviços apoiados nos repositórios temporários.

    O `try/finally` é obrigatório: o container guarda o override num global, e sem a
    restauração o estado vazaria para os testes seguintes.
    """
    from src.orchestration.container import Services, set_services
    from src.services.auth_service import AuthService
    from src.services.cambio_service import CambioService
    from src.services.credito_service import CreditoService
    from src.services.entrevista_service import EntrevistaService
    from src.services.knowledge_service import KnowledgeService

    servicos = Services(
        auth=AuthService(cliente_repo),
        credito=CreditoService(faixa_repo, solicitacao_repo, cliente_repo),
        entrevista=EntrevistaService(cliente_repo, historico_repo),
        cambio=CambioService(),
        knowledge=KnowledgeService(),
    )
    set_services(servicos)
    try:
        yield servicos
    finally:
        set_services(None)
