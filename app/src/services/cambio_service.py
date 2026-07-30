"""Câmbio: cotação em tempo real via AwesomeAPI (não exige chave)."""
from __future__ import annotations

from typing import Final, Literal, get_args

import requests

from src.core.config import get_settings
from src.core.constants import MOEDA_DESTINO, MOEDA_PADRAO, TIMEOUT_HTTP
from src.core.logging import get_logger
from src.domain.results import ResultadoCotacao

logger = get_logger(__name__)

MoedaSuportada = Literal[
    "USD", "EUR", "GBP", "ARS", "JPY", "CHF", "CAD", "AUD", "CNY", "BTC"
]
MOEDAS_SUPORTADAS: Final[tuple[str, ...]] = get_args(MoedaSuportada)

NOMES_AMIGAVEIS: Final[dict[str, str]] = {
    "USD": "dólar americano", "EUR": "euro", "GBP": "libra esterlina",
    "ARS": "peso argentino", "JPY": "iene japonês", "CHF": "franco suíço",
    "CAD": "dólar canadense", "AUD": "dólar australiano", "CNY": "yuan chinês",
    "BTC": "bitcoin",
}


class CambioService:
    def __init__(self, base_url: str | None = None, timeout: int = TIMEOUT_HTTP):
        self.base_url = (base_url or get_settings().awesomeapi_base_url).rstrip("/")
        self.timeout = timeout

    def consultar(
        self, moeda: str = MOEDA_PADRAO, destino: str = MOEDA_DESTINO
    ) -> ResultadoCotacao:
        origem = (moeda or MOEDA_PADRAO).strip().upper()
        alvo = (destino or MOEDA_DESTINO).strip().upper()

        if origem not in MOEDAS_SUPORTADAS:
            return ResultadoCotacao(
                ok=False,
                moeda_origem=origem,
                moeda_destino=alvo,
                mensagem=(
                    f"A moeda {origem} não está disponível para cotação. "
                    f"Disponíveis: {', '.join(MOEDAS_SUPORTADAS)}."
                ),
            )

        par = f"{origem}-{alvo}"
        try:
            resposta = requests.get(f"{self.base_url}/{par}", timeout=self.timeout)
            resposta.raise_for_status()
            dados = resposta.json()
        except requests.Timeout:
            logger.error("Timeout ao consultar cotação de %s", par)
            return self._indisponivel(origem, alvo)
        except requests.RequestException as exc:
            logger.error("Falha ao consultar cotação de %s: %s", par, exc)
            return self._indisponivel(origem, alvo)
        except ValueError as exc:
            logger.error("Resposta inválida da API de câmbio para %s: %s", par, exc)
            return self._indisponivel(origem, alvo)

        return self._interpretar(dados, origem, alvo)

    def _interpretar(self, dados: object, origem: str, alvo: str) -> ResultadoCotacao:
        """A AwesomeAPI devolve `{"USDBRL": {...}}`; o conteúdo é o que interessa."""
        if not isinstance(dados, dict) or not dados:
            return self._indisponivel(origem, alvo)

        cotacao = next(iter(dados.values()))
        if not isinstance(cotacao, dict) or "bid" not in cotacao:
            return self._indisponivel(origem, alvo)

        try:
            valor = float(cotacao["bid"])
            variacao = float(cotacao.get("pctChange") or 0.0)
        except (TypeError, ValueError):
            return self._indisponivel(origem, alvo)

        return ResultadoCotacao(
            ok=True,
            moeda_origem=origem,
            moeda_destino=alvo,
            valor=valor,
            variacao_pct=variacao,
            atualizado_em=str(cotacao.get("create_date", "")),
            mensagem=(
                f"1 {NOMES_AMIGAVEIS.get(origem, origem)} ({origem}) = "
                f"{valor:.4f} {alvo} (variação de {variacao:+.2f}% no dia)."
            ),
        )

    @staticmethod
    def _indisponivel(origem: str, alvo: str) -> ResultadoCotacao:
        return ResultadoCotacao(
            ok=False,
            moeda_origem=origem,
            moeda_destino=alvo,
            mensagem=(
                "O serviço de cotação está indisponível neste momento. "
                "Não é possível informar um valor confiável agora."
            ),
        )
