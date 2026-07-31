"""Barra lateral: controles e painel de diagnóstico."""
from __future__ import annotations

import streamlit as st

from ui.state import novo_atendimento

CLIENTES_DEMO = """
| Cliente | CPF | Nascimento |
| --- | --- | --- |
| Ana Souza | 111.444.777-35 | 14/05/1990 |
| Diego Rocha | 222.555.888-46 | 19/07/1995 |
| Carla Mendes | 333.666.999-57 | 27/03/1978 |
| Bruno Lima | 123.456.789-09 | 02/11/1985 |
| Felipe Nunes | 987.654.321-00 | 08/09/1988 |
"""


def render_sidebar(debug: dict, finished: bool) -> None:
    with st.sidebar:
        st.subheader("Atendimento")
        if st.button("Novo atendimento", use_container_width=True):
            novo_atendimento()
            st.rerun()

        if finished:
            st.markdown(
                '<div class="aviso-encerrado">Atendimento encerrado.</div>',
                unsafe_allow_html=True,
            )

        if debug.get("vazamento detectado"):
            st.warning("Possível menção a transição entre agentes na última resposta.")

        inventados = debug.get("números sem procedência")
        if isinstance(inventados, list) and inventados:
            st.warning(
                "A última resposta cita números que nenhuma ferramenta devolveu: "
                f"{', '.join(str(n) for n in inventados)}."
            )

        with st.expander("Diagnóstico", expanded=False):
            if debug:
                st.json(debug, expanded=True)
            else:
                st.caption("Envie uma mensagem para ver o estado do atendimento.")

        with st.expander("Clientes de teste", expanded=False):
            st.markdown(CLIENTES_DEMO)
            st.caption(
                "Diego demonstra o fluxo rejeição → entrevista → aprovação. "
                "Felipe tem a conta bloqueada."
            )
