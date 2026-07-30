"""Persistência das sessões de atendimento."""
from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)

TIMEOUT_CONEXAO = 5


def criar_checkpointer() -> tuple[BaseCheckpointSaver, str]:
    """Devolve `(checkpointer, descrição)`. A descrição vai para o sidebar de debug."""
    url = get_settings().postgres_url
    if not url:
        logger.info("POSTGRES_URL não configurada: sessões em memória.")
        return MemorySaver(), "memória (sem POSTGRES_URL)"

    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            conninfo=url,
            max_size=8,
            open=True,
            timeout=TIMEOUT_CONEXAO,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "connect_timeout": TIMEOUT_CONEXAO,
            },
        )
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()
    except Exception as exc:
        logger.error("Postgres indisponível (%s): sessões em memória.", exc)
        return MemorySaver(), "memória (Postgres indisponível)"

    logger.info("Sessões persistidas no Postgres.")
    return checkpointer, "PostgreSQL"
