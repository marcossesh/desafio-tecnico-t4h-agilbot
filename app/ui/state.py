"""Estado da sessão do Streamlit."""
from __future__ import annotations

import uuid

import streamlit as st

from ui.service import Atendimento


@st.cache_resource(show_spinner=False)
def get_atendimento() -> Atendimento:
    """Instância única do grafo compilado (com checkpointer)."""
    return Atendimento()


def init_session() -> None:
    if "session_id" not in st.session_state:
        novo_atendimento()


def novo_atendimento() -> None:
    """Começa um atendimento do zero: novo `thread_id`, histórico limpo."""
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.historico = []
    st.session_state.debug = {}
    st.session_state.finished = False
