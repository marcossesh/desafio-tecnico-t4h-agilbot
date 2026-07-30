"""Container de serviços — injeção de dependência leve."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from src.services.auth_service import AuthService
from src.services.cambio_service import CambioService
from src.services.credito_service import CreditoService
from src.services.entrevista_service import EntrevistaService
from src.services.knowledge_service import KnowledgeService


@dataclass(frozen=True)
class Services:
    """Serviços de negócio disponíveis para os agentes."""

    auth: AuthService
    credito: CreditoService
    entrevista: EntrevistaService
    cambio: CambioService
    knowledge: KnowledgeService


_override: Services | None = None


@lru_cache(maxsize=1)
def _services_padrao() -> Services:
    return Services(
        auth=AuthService(),
        credito=CreditoService(),
        entrevista=EntrevistaService(),
        cambio=CambioService(),
        knowledge=KnowledgeService(),
    )


def get_services() -> Services:
    return _override or _services_padrao()


def set_services(services: Services | None) -> None:
    """Substitui o container. Passe `None` para restaurar o padrão."""
    global _override
    _override = services
