"""Estado da sessão do Streamlit."""
from __future__ import annotations

import uuid

import streamlit as st

from ui.service import Atendimento, atendimento_encerrado, historico_visivel


@st.cache_resource(show_spinner=False)
def get_atendimento() -> Atendimento:
    """Instância única do grafo compilado (com checkpointer)."""
    return Atendimento()


def init_session() -> None:
    """Retoma o atendimento em curso, ou começa um novo.

    O `session_state` do Streamlit morre a cada refresh, mas a conversa continua íntegra
    no checkpointer. O `session_id` viaja na query string justamente para sobreviver ao
    F5 e permitir reidratar a tela a partir do que já está persistido — sem isso, cada
    refresh abandonaria a thread e criaria uma sessão órfã.
    """
    if "session_id" in st.session_state:
        return

    sid = st.query_params.get("sid")
    if not sid:
        novo_atendimento()
        return

    st.session_state.session_id = sid
    st.session_state.historico = historico_visivel(get_atendimento(), sid)
    st.session_state.debug = {}
    st.session_state.finished = atendimento_encerrado(get_atendimento(), sid)


def novo_atendimento() -> None:
    """Começa um atendimento do zero: novo `thread_id`, histórico limpo."""
    st.session_state.session_id = str(uuid.uuid4())
    st.query_params["sid"] = st.session_state.session_id
    st.session_state.historico = []
    st.session_state.debug = {}
    st.session_state.finished = False
