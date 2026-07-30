# Imagem da UI Streamlit (que invoca o grafo no mesmo processo).
FROM python:3.12-slim

# O container escreve em app/data, que é um bind mount do host. Rodar como root deixaria
# os CSVs pertencendo ao root na máquina do avaliador; rodar com um UID fixo quebraria em
# qualquer máquina com UID diferente. Por isso o usuário é criado com o UID/GID de quem
# sobe o compose (ver Makefile e README).
ARG UID=1000
ARG GID=1000

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/app \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv

WORKDIR /app

# Dependências primeiro: a camada só é refeita quando o lockfile muda.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app

RUN groupadd -g "${GID}" agilbot 2>/dev/null || true \
 && useradd -m -u "${UID}" -g "${GID}" agilbot 2>/dev/null || true \
 && mkdir -p /app/app/logs \
 && chown -R "${UID}:${GID}" /app /opt/venv

USER ${UID}:${GID}

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "app/ui/streamlit_app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
