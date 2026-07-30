"""Componentes de conversa."""
from __future__ import annotations

import streamlit as st

AVATARES = {"user": "🧑", "assistant": "🏦"}

BOAS_VINDAS = """
Olá! Sou o atendente virtual do **Banco Ágil**.

Posso consultar seu limite de crédito, registrar um pedido de aumento e cotar moedas.
Para começar, me diga seu **CPF**.
"""


def render_boas_vindas(historico: list[dict]) -> None:
    if not historico:
        with st.chat_message("assistant", avatar=AVATARES["assistant"]):
            st.markdown(BOAS_VINDAS)


def render_historico(historico: list[dict]) -> None:
    for msg in historico:
        with st.chat_message(msg["role"], avatar=AVATARES.get(msg["role"])):
            st.markdown(msg["content"])
