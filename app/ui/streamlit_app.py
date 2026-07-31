"""Interface do atendimento do Banco Ágil.

Entrypoint fino: configura a página, delega o desenho a `ui.tela` e a conversa a
`ui.service`. Nenhuma regra de negócio vive aqui.
"""
from __future__ import annotations

import streamlit as st

from ui import tela
from ui.state import iniciar, sessao_atual

st.set_page_config(
    page_title="Banco Ágil — Atendimento",
    page_icon="🏦",
    layout="centered",
    initial_sidebar_state="expanded",
)


def _turno(texto: str) -> None:
    """Um turno completo: eco da fala, invocação do grafo, atualização da sessão."""
    st.session_state.conversa.append({"role": "user", "content": texto})
    tela.eco_do_cliente(texto)

    with st.spinner(tela.AGUARDE):
        resposta = sessao_atual().responder(st.session_state.sid, texto)

    st.session_state.conversa.append({"role": "assistant", "content": resposta.texto})
    st.session_state.diagnostico = resposta.debug
    st.session_state.encerrado = resposta.finished
    st.rerun()


def main() -> None:
    tela.preparar()
    iniciar()

    tela.faixa_de_topo()
    tela.painel(st.session_state.diagnostico, st.session_state.encerrado)
    tela.conversa(st.session_state.conversa)

    fechado = st.session_state.encerrado
    if texto := st.chat_input(
        tela.CAMPO_ENCERRADO if fechado else tela.CAMPO_ATIVO, disabled=fechado
    ):
        _turno(texto)


if __name__ == "__main__":
    # O `streamlit run` executa este arquivo como `__main__`; o guard mantém o módulo
    # importável, e é isso que permite o teste de import cobrir a UI sem subir servidor.
    main()
