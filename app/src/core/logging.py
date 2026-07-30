"""Logging estruturado, correlacionado por sessão."""
from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

from src.core.constants import LOGS_DIR

_thread_id: ContextVar[str] = ContextVar("thread_id", default="-")

_FORMATO = "%(asctime)s | %(levelname)-7s | sessao=%(thread_id)s | %(name)s | %(message)s"
_configurado = False


def set_thread_id(thread_id: str) -> None:
    """Associa os logs seguintes a uma sessão de atendimento."""
    _thread_id.set(thread_id or "-")


class _FiltroSessao(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.thread_id = _thread_id.get()
        return True


def _configurar() -> None:
    """Configura raiz uma única vez: stderr sempre, arquivo quando possível."""
    global _configurado
    if _configurado:
        return
    _configurado = True

    formatter = logging.Formatter(_FORMATO)
    filtro = _FiltroSessao()

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    console.addFilter(filtro)

    handlers: list[logging.Handler] = [console]
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        arquivo = logging.FileHandler(LOGS_DIR / "agilbot.log", encoding="utf-8")
        arquivo.setFormatter(formatter)
        arquivo.addFilter(filtro)
        handlers.append(arquivo)
    except OSError:
        pass

    raiz = logging.getLogger("agilbot")
    raiz.setLevel(logging.INFO)
    raiz.handlers = handlers
    raiz.propagate = False


def get_logger(nome: str) -> logging.Logger:
    _configurar()
    return logging.getLogger(f"agilbot.{nome}")
