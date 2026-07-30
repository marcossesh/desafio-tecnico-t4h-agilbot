"""Interface do atendimento do Banco Ágil."""
from __future__ import annotations

import streamlit as st

from ui.components.chat import AVATARES, render_boas_vindas, render_historico
from ui.components.sidebar import render_sidebar
from ui.state import get_atendimento, init_session
from ui.styles import apply_styles, render_header

PLACEHOLDER_ATIVO = "Digite sua mensagem..."
PLACEHOLDER_ENCERRADO = "Atendimento encerrado. Clique em 'Novo atendimento'."

st.set_page_config(
    page_title="Banco Ágil — Atendimento",
    page_icon="🏦",
    layout="centered",
    initial_sidebar_state="expanded",
)


def _enviar(mensagem: str) -> None:
    st.session_state.historico.append({"role": "user", "content": mensagem})
    with st.chat_message("user", avatar=AVATARES["user"]):
        st.markdown(mensagem)

    with st.spinner("Atendente digitando..."):
        resposta = get_atendimento().responder(st.session_state.session_id, mensagem)

    st.session_state.debug = resposta.debug
    st.session_state.finished = resposta.finished
    st.session_state.historico.append({"role": "assistant", "content": resposta.texto})
    st.rerun()


def main() -> None:
    apply_styles()
    init_session()

    render_sidebar(st.session_state.debug, st.session_state.finished)
    render_header()
    render_boas_vindas(st.session_state.historico)
    render_historico(st.session_state.historico)

    encerrado = st.session_state.finished
    mensagem = st.chat_input(
        PLACEHOLDER_ENCERRADO if encerrado else PLACEHOLDER_ATIVO, disabled=encerrado
    )
    if mensagem:
        _enviar(mensagem)


if __name__ == "__main__":
    main()
