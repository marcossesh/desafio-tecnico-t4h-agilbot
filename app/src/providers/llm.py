"""Provider de LLM: Gemini (primário) com fallback automático para Groq."""
from __future__ import annotations

from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel

from src.core.config import get_settings
from src.core.constants import MAX_RETRIES_LLM
from src.core.logging import get_logger

logger = get_logger(__name__)


class LLMIndisponivelError(RuntimeError):
    """Nenhum provedor configurado — a UI informa o operador em vez de quebrar."""


def _amostragem() -> dict:
    """`temperature` só é enviada quando configurada — ver `Settings.temperatura`."""
    temperatura = get_settings().temperatura
    return {} if temperatura is None else {"temperature": temperatura}


def _gemini() -> BaseChatModel | None:
    settings = get_settings()
    if not settings.tem_gemini:
        return None
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.google_api_key,
        max_retries=MAX_RETRIES_LLM,
        **_amostragem(),
    )


def _groq() -> BaseChatModel | None:
    settings = get_settings()
    if not settings.tem_groq:
        return None
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        max_retries=MAX_RETRIES_LLM,
        **_amostragem(),
    )


@lru_cache(maxsize=1)
def get_chat_model() -> BaseChatModel:
    """Modelo de chat com fallback encadeado. Cacheado: um por processo."""
    primario = _gemini()
    secundario = _groq()

    if primario is not None and secundario is not None:
        logger.info("LLM: Gemini primário com fallback para Groq.")
        return primario.with_fallbacks([secundario])
    if primario is not None:
        logger.info("LLM: apenas Gemini configurado (sem fallback).")
        return primario
    if secundario is not None:
        logger.info("LLM: apenas Groq configurado.")
        return secundario

    raise LLMIndisponivelError(
        "Nenhuma chave de LLM configurada. Defina GOOGLE_API_KEY e/ou GROQ_API_KEY "
        "no arquivo .env."
    )


def reset_chat_model() -> None:
    """Limpa o cache (usado em testes e ao recarregar configuração)."""
    get_chat_model.cache_clear()
