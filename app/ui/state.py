"""Sessão do Streamlit: identidade da thread e o que a tela precisa reexibir.

O estado autoritativo do atendimento **não** está aqui — vive no checkpointer do
LangGraph, indexado pelo `sid`. Este módulo guarda só o suficiente para redesenhar a
página, que o Streamlit reexecuta a cada interação.
"""
from __future__ import annotations

import uuid

import streamlit as st

from ui.service import Atendimento, atendimento_encerrado, historico_visivel


@st.cache_resource(show_spinner=False)
def sessao_atual() -> Atendimento:
    """Grafo compilado e checkpointer — uma instância por processo.

    O `cache_resource` é o que garante um pool de conexões, um grafo e **um lock por
    CSV**; sem ele, cada reexecução do script criaria repositórios novos e a
    serialização de escrita deixaria de valer.
    """
    return Atendimento()


def iniciar() -> None:
    """Retoma o atendimento em curso ou começa um novo.

    O `session_state` morre a cada refresh, mas a conversa continua íntegra no
    checkpointer. O `sid` viaja na query string justamente para sobreviver ao F5 e
    permitir reidratar a tela do que já está persistido — sem isso, cada refresh
    abandonaria a thread e criaria uma sessão órfã.
    """
    if "sid" in st.session_state:
        return

    sid = st.query_params.get("sid")
    if not sid:
        recomecar()
        return

    atendimento = sessao_atual()
    st.session_state.sid = sid
    st.session_state.conversa = historico_visivel(atendimento, sid)
    st.session_state.diagnostico = {}
    st.session_state.encerrado = atendimento_encerrado(atendimento, sid)


def recomecar() -> None:
    """Zera a tela e abre uma thread nova — o atendimento anterior fica no checkpointer."""
    sid = str(uuid.uuid4())
    st.query_params["sid"] = sid
    st.session_state.sid = sid
    st.session_state.conversa = []
    st.session_state.diagnostico = {}
    st.session_state.encerrado = False
