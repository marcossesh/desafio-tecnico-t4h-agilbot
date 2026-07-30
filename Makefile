.PHONY: help install run test lint spike ingest docker docker-down

export PYTHONPATH := app

help:
	@echo "install      instala as dependências (uv, Python 3.12 gerenciado)"
	@echo "run          sobe a UI Streamlit em http://localhost:8501"
	@echo "test         roda a suíte com cobertura"
	@echo "lint         roda o ruff"
	@echo "spike        conversa com o grafo no terminal (precisa de chave de LLM)"
	@echo "ingest       indexa a base de conhecimento no pgvector"
	@echo "docker       sobe postgres + app via docker compose"
	@echo "docker-down  derruba os containers"

install:
	uv python install 3.12
	uv sync

run:
	uv run streamlit run app/ui/streamlit_app.py

test:
	uv run pytest

lint:
	uv run ruff check app tests scripts

spike:
	uv run python scripts/spike.py

ingest:
	uv run python -m src.rag.ingest

# APP_UID/APP_GID são repassados para que os CSVs escritos no bind mount pertençam a
# quem subiu o compose — sem isso, "Permission denied" só dentro do container.
# (`UID` seria o nome natural, mas é readonly no bash.)
docker:
	APP_UID=$$(id -u) APP_GID=$$(id -g) docker compose -f infra/docker-compose.yml up --build

docker-down:
	docker compose -f infra/docker-compose.yml down
