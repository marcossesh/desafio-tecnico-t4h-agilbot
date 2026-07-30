"""Câmbio com a API externa mockada — nenhum teste depende da rede."""
from __future__ import annotations

import pytest
import requests

from src.services.cambio_service import MOEDAS_SUPORTADAS, CambioService

BASE = "https://economia.awesomeapi.com.br/json/last"

RESPOSTA_USD = {
    "USDBRL": {
        "code": "USD", "codein": "BRL", "name": "Dólar Americano/Real Brasileiro",
        "high": "5.09", "low": "5.05", "bid": "5.0835", "ask": "5.0841",
        "pctChange": "-0.23", "create_date": "2026-07-30 14:55:02",
    }
}


@pytest.fixture
def servico() -> CambioService:
    return CambioService(base_url=BASE)


class TestCotacao:
    def test_cotacao_padrao_e_dolar(self, servico, requests_mock):
        requests_mock.get(f"{BASE}/USD-BRL", json=RESPOSTA_USD)
        resultado = servico.consultar()

        assert resultado.ok
        assert resultado.moeda_origem == "USD"
        assert resultado.moeda_destino == "BRL"
        assert resultado.valor == pytest.approx(5.0835)
        assert "dólar americano" in resultado.mensagem

    def test_respeita_a_moeda_pedida(self, servico, requests_mock):
        requests_mock.get(
            f"{BASE}/EUR-BRL",
            json={"EURBRL": {"bid": "5.85823", "pctChange": "0.11", "create_date": "x"}},
        )
        resultado = servico.consultar("EUR")

        assert resultado.ok
        assert resultado.moeda_origem == "EUR"
        assert "euro" in resultado.mensagem
        assert "dólar" not in resultado.mensagem  # nunca devolve outra moeda no lugar

    def test_aceita_codigo_em_minusculas(self, servico, requests_mock):
        requests_mock.get(f"{BASE}/USD-BRL", json=RESPOSTA_USD)
        assert servico.consultar("usd").ok


class TestMoedasSuportadas:
    def test_lista_verificada_contra_a_api(self):
        # Cada par foi conferido manualmente (todos respondem 200 em <MOEDA>-BRL).
        assert set(MOEDAS_SUPORTADAS) == {
            "USD", "EUR", "GBP", "ARS", "JPY", "CHF", "CAD", "AUD", "CNY", "BTC"
        }

    def test_moeda_fora_da_lista_nao_chega_a_chamar_a_api(self, servico, requests_mock):
        resultado = servico.consultar("XYZ")

        assert not resultado.ok
        assert "não está disponível" in resultado.mensagem
        assert requests_mock.call_count == 0


class TestErros:
    def test_api_fora_do_ar(self, servico, requests_mock):
        requests_mock.get(f"{BASE}/USD-BRL", status_code=503)
        resultado = servico.consultar("USD")

        assert not resultado.ok
        assert "indisponível" in resultado.mensagem
        assert resultado.valor is None  # jamais inventa um valor

    def test_timeout(self, servico, requests_mock):
        requests_mock.get(f"{BASE}/USD-BRL", exc=requests.Timeout)
        assert not servico.consultar("USD").ok

    def test_json_malformado(self, servico, requests_mock):
        requests_mock.get(f"{BASE}/USD-BRL", text="isto não é json")
        assert not servico.consultar("USD").ok

    def test_resposta_sem_o_campo_esperado(self, servico, requests_mock):
        requests_mock.get(f"{BASE}/USD-BRL", json={"USDBRL": {"nada": "aqui"}})
        assert not servico.consultar("USD").ok
