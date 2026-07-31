"""Tudo que a tela desenha: estilo, cabeçalho, conversa e painel de diagnóstico.

Um módulo só porque as quatro peças são pequenas e mudam juntas — separá-las em
`styles.py` + `components/` custava quatro arquivos de menos de 50 linhas cada, sem
nenhum ganho de isolamento: todas dependem do mesmo `st` e do mesmo dicionário de
diagnóstico.
"""
from __future__ import annotations

import streamlit as st

from ui.state import recomecar

ICONES = {"user": "🧑", "assistant": "🏦"}

CAMPO_ATIVO = "Em que posso ajudar?"
CAMPO_ENCERRADO = "Atendimento finalizado — inicie um novo para continuar."
AGUARDE = "Um momento..."

ABERTURA = """
Olá! Sou o atendente virtual do **Banco Ágil**.

Posso consultar seu limite de crédito, registrar um pedido de aumento e cotar moedas.
Para começar, me diga seu **CPF**.
"""

CADASTROS_DE_TESTE = """
| Cliente | CPF | Nascimento |
| --- | --- | --- |
| Ana Souza | 111.444.777-35 | 14/05/1990 |
| Diego Rocha | 222.555.888-46 | 19/07/1995 |
| Carla Mendes | 333.666.999-57 | 27/03/1978 |
| Bruno Lima | 123.456.789-09 | 02/11/1985 |
| Felipe Nunes | 987.654.321-00 | 08/09/1988 |
"""

FOLHA_DE_ESTILO = """
<style>
  .faixa-topo {
    display: flex; align-items: center; gap: .9rem;
    padding: 1rem 1.25rem; margin-bottom: 1.25rem;
    border-radius: 14px;
    background: linear-gradient(100deg, #0f5132 0%, #1a7f4f 55%, #24a06a 100%);
    color: #fff;
  }
  .faixa-topo .selo { font-size: 1.9rem; line-height: 1; }
  .faixa-topo h1 { font-size: 1.25rem; margin: 0; font-weight: 650; color: #fff; }
  .faixa-topo p  { font-size: .85rem; margin: .15rem 0 0; opacity: .85; }

  .stChatMessage { border-radius: 12px; }
  div[data-testid="stChatInput"] textarea { font-size: .95rem; }

  .selo-encerrado {
    padding: .6rem .9rem; border-radius: 10px; font-size: .85rem;
    background: rgba(120,120,120,.12); border: 1px solid rgba(120,120,120,.25);
  }
</style>
"""


def preparar() -> None:
    """Injeta a folha de estilo. Primeira coisa que a página faz."""
    st.markdown(FOLHA_DE_ESTILO, unsafe_allow_html=True)


def faixa_de_topo() -> None:
    st.markdown(
        """
        <div class="faixa-topo">
          <div class="selo">🏦</div>
          <div>
            <h1>Banco Ágil — Atendimento</h1>
            <p>Consulta de limite, aumento de crédito e cotação de moedas.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def conversa(mensagens: list[dict]) -> None:
    """Desenha a conversa inteira — a abertura entra quando ainda não há nada dito."""
    if not mensagens:
        with st.chat_message("assistant", avatar=ICONES["assistant"]):
            st.markdown(ABERTURA)

    for msg in mensagens:
        with st.chat_message(msg["role"], avatar=ICONES.get(msg["role"])):
            st.markdown(msg["content"])


def eco_do_cliente(texto: str) -> None:
    """Mostra a fala do cliente antes de o grafo responder, para o turno não parecer travado."""
    with st.chat_message("user", avatar=ICONES["user"]):
        st.markdown(texto)


def painel(diagnostico: dict, encerrado: bool) -> None:
    """Barra lateral: controle de sessão, alarmes das guardas e estado do atendimento."""
    with st.sidebar:
        st.subheader("Atendimento")
        if st.button("Novo atendimento", use_container_width=True):
            recomecar()
            st.rerun()

        if encerrado:
            st.markdown(
                '<div class="selo-encerrado">Atendimento encerrado.</div>',
                unsafe_allow_html=True,
            )

        _alarmes(diagnostico)

        with st.expander("Diagnóstico", expanded=False):
            if diagnostico:
                st.json(diagnostico, expanded=True)
            else:
                st.caption("Envie uma mensagem para ver o estado do atendimento.")

        with st.expander("Clientes de teste", expanded=False):
            st.markdown(CADASTROS_DE_TESTE)
            st.caption(
                "Diego demonstra o fluxo rejeição → entrevista → aprovação. "
                "Felipe tem a conta bloqueada."
            )


def _alarmes(diagnostico: dict) -> None:
    """As duas guardas de runtime aparecem aqui, fora do expander, para não passarem batido."""
    if diagnostico.get("vazamento detectado"):
        st.warning("Possível menção a transição entre agentes na última resposta.")

    inventados = diagnostico.get("números sem procedência")
    if isinstance(inventados, list) and inventados:
        st.warning(
            "A última resposta cita números que nenhuma ferramenta devolveu: "
            f"{', '.join(str(n) for n in inventados)}."
        )
