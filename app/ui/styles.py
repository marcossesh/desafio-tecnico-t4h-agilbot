"""Estilos e cabeçalho da interface."""
from __future__ import annotations

import streamlit as st

CSS = """
<style>
  .bloco-cabecalho {
    display: flex; align-items: center; gap: .9rem;
    padding: 1rem 1.25rem; margin-bottom: 1.25rem;
    border-radius: 14px;
    background: linear-gradient(100deg, #0f5132 0%, #1a7f4f 55%, #24a06a 100%);
    color: #fff;
  }
  .bloco-cabecalho .marca { font-size: 1.9rem; line-height: 1; }
  .bloco-cabecalho h1 { font-size: 1.25rem; margin: 0; font-weight: 650; color: #fff; }
  .bloco-cabecalho p  { font-size: .85rem; margin: .15rem 0 0; opacity: .85; }

  .stChatMessage { border-radius: 12px; }
  div[data-testid="stChatInput"] textarea { font-size: .95rem; }

  .aviso-encerrado {
    padding: .6rem .9rem; border-radius: 10px; font-size: .85rem;
    background: rgba(120,120,120,.12); border: 1px solid rgba(120,120,120,.25);
  }
</style>
"""


def apply_styles() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def render_header() -> None:
    st.markdown(
        """
        <div class="bloco-cabecalho">
          <div class="marca">🏦</div>
          <div>
            <h1>Banco Ágil — Atendimento</h1>
            <p>Consulta de limite, aumento de crédito e cotação de moedas.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
