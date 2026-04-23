# RE_CL — Makefile
# Uso: make <target>
# Requiere: Docker, Python 3.11+, Node 20+

.DEFAULT_GOAL := help
PYTHON := py
COMPOSE := docker-compose

# ── Ayuda ──────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "RE_CL — Comandos disponibles"
	@echo "──────────────────────────────────────────"
	@echo "  make setup          Levantar DB + aplicar schema"
	@echo "  make pipeline       Correr pipeline completo (ingesta→modelo→scores→mapas)"
	@echo "  make score-only     Re-calcular scores sin re-ingestar ni re-entrenar"
	@echo "  make scrape         Scraping de portales (Portal Inmobiliario + Toctoc)"
	@echo "  make scrape-score   Scraping + re-scoring con datos frescos"
	@echo "  make alerts         Verificar nuevas oportunidades altas y notificar
  make deploy         Registrar flows en Prefect (servidor local debe estar corriendo)"
	@echo "  make up             Levantar todos los servicios (DB + API + Dashboard + Frontend)"
	@echo "  make down           Bajar todos los servicios"
	@echo "  make frontend       Instalar deps y build del frontend React"
	@echo "  make test           Correr todos los tests"
	@echo "  make logs           Ver logs de todos los servicios"
	@echo "  make status         Ver estado de los servicios"
	@echo ""

# ── Docker ─────────────────────────────────────────────────────────────────────
setup:
	$(COMPOSE) up -d db
	@echo "Esperando que la DB esté lista..."
	@sleep 5
	@echo "DB lista en localhost:5432"

up:
	$(COMPOSE) up -d --build
	@echo ""
	@echo "✓ Plataforma disponible en: http://localhost"
	@echo "  → Frontend:   http://localhost"
	@echo "  → API docs:   http://localhost/docs"
	@echo "  → Dashboard:  http://localhost/dashboard"
	@echo "  → API directa: http://localhost:8000"

up-dev:
	$(COMPOSE) up -d db
	@echo "DB lista. Para desarrollo local:"
	@echo "  API:       uvicorn src.api.main:app --reload --port 8000"
	@echo "  Dashboard: streamlit run src/dashboard/app.py"
	@echo "  Frontend:  cd frontend && npm run dev"

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=50

status:
	$(COMPOSE) ps

restart-api:
	$(COMPOSE) restart api

# ── Pipeline ───────────────────────────────────────────────────────────────────
pipeline:
	@echo "=== Iniciando pipeline completo ==="
	$(PYTHON) src/ingestion/load_transactions.py
	$(PYTHON) src/ingestion/clean_transactions.py
	$(PYTHON) src/features/build_features.py
	$(PYTHON) src/models/hedonic_model.py
	$(PYTHON) src/scoring/opportunity_score.py
	$(PYTHON) src/maps/commune_ranking.py
	$(PYTHON) src/maps/heatmap.py
	@echo "=== Pipeline completo ==="

pipeline-dry:
	$(PYTHON) src/ingestion/clean_transactions.py --dry-run
	$(PYTHON) src/features/build_features.py --dry-run
	$(PYTHON) src/scoring/opportunity_score.py --dry-run

score-only:
	$(PYTHON) src/scoring/opportunity_score.py
	$(PYTHON) src/maps/commune_ranking.py
	$(PYTHON) src/maps/heatmap.py

score-location:
	$(PYTHON) src/scoring/opportunity_score.py --profile location
	$(PYTHON) src/maps/commune_ranking.py
	$(PYTHON) src/maps/heatmap.py

score-growth:
	$(PYTHON) src/scoring/opportunity_score.py --profile growth

score-liquidity:
	$(PYTHON) src/scoring/opportunity_score.py --profile liquidity

# ── Scraping ───────────────────────────────────────────────────────────────────
scrape:
	$(PYTHON) src/scraping/portal_inmobiliario.py --max-pages 30
	$(PYTHON) src/scraping/toctoc.py --max-pages 30

scrape-score:
	$(PYTHON) src/scraping/portal_inmobiliario.py --max-pages 30
	$(PYTHON) src/scraping/toctoc.py --max-pages 30
	$(PYTHON) src/scoring/scraped_to_scored.py
	$(PYTHON) src/maps/commune_ranking.py
	$(PYTHON) src/maps/heatmap.py

scrape-dry:
	$(PYTHON) src/scraping/portal_inmobiliario.py --dry-run
	$(PYTHON) src/scraping/toctoc.py --dry-run

# ── Alertas ────────────────────────────────────────────────────────────────────
alerts:
	$(PYTHON) src/alerts/notifier.py

alerts-test:
	$(PYTHON) src/alerts/notifier.py --dry-run

# ── Frontend ───────────────────────────────────────────────────────────────────
frontend:
	cd frontend && npm install && npm run build
	@echo "Frontend build listo en frontend/dist/"

frontend-dev:
	cd frontend && npm install && npm run dev

# ── Tests ──────────────────────────────────────────────────────────────────────
test:
	$(PYTHON) -m pytest tests/ -v

test-fast:
	$(PYTHON) -m pytest tests/ -x -q

test-scoring:
	$(PYTHON) -m pytest tests/test_scoring.py -v

test-api:
	$(PYTHON) -m pytest tests/test_api.py -v

test-clean:
	$(PYTHON) -m pytest tests/test_clean.py -v

# ── Prefect ────────────────────────────────────────────────────────────────────
deploy:
	@echo "Registrando deployments en Prefect..."
	$(PYTHON) src/pipelines/deploy.py
	@echo ""
	@echo "Para ejecutar el worker:"
	@echo "  prefect worker start --pool default-agent-pool"

prefect-server:
	prefect server start

daily:
	$(PYTHON) src/pipelines/flows.py --flow daily

# ── Utilidades ─────────────────────────────────────────────────────────────────
heatmap:
	$(PYTHON) src/maps/heatmap.py
	@echo "Mapa guardado en data/exports/"

open-map:
	start data/exports/heatmap_v1.0.html

db-shell:
	$(COMPOSE) exec db psql -U re_cl_user -d re_cl

.PHONY: help setup up up-dev down logs status restart-api \
        pipeline pipeline-dry score-only score-location score-growth score-liquidity \
        scrape scrape-score scrape-dry alerts alerts-test \
        deploy prefect-server daily \
        frontend frontend-dev test test-fast test-scoring test-api test-clean \
        heatmap open-map db-shell
