#!/bin/sh
# Indexa a base de conhecimento antes de subir a UI.
#
# A ingestão é idempotente (sonda a versão do corpus e sai sem gravar se já estiver em
# dia), então rodar a cada start do container é barato. Sem GOOGLE_API_KEY ou sem
# POSTGRES_URL ela apenas registra um aviso e devolve 0 — mesmo caminho de degradação do
# RAG desligado.
set -e

if ! python -m src.rag.ingest; then
    # Indexação é acessória: o atendimento funciona sem ela (o agente responde que não
    # tem a informação). Derrubar o container aqui trocaria uma degradação por uma
    # indisponibilidade total.
    echo "[entrypoint] Falha ao indexar a base de conhecimento; o RAG responderá vazio." >&2
fi

exec "$@"
