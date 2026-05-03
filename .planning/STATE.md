---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: MVP
status: completed
last_updated: "2026-04-23T02:44:26.751Z"
progress:
  total_phases: 3
  completed_phases: 1
  total_plans: 5
  completed_plans: 4
  percent: 80
---

# Project State: RE_CL

**Last updated:** 2026-04-23
**Current milestone:** v1.0 MVP
**Active phase:** Phase 9 — Scraping Paralelo Multi-fuente
**Status:** Milestone complete

## Completed Phases

- **Phase 1** — Entorno y Base de Datos (schema.sql, docker-compose.yml, requirements.txt, .env.example)
- **Phase 2** — Ingesta y Limpieza del CSV (load_transactions.py, clean_transactions.py)
- **Phase 3** — Feature Engineering (price_features.py, spatial_features.py, temporal_features.py, build_features.py) — 14/14 tests passing

## Key Decisions

- **Stack:** Python 3.11 + PostgreSQL/PostGIS + XGBoost + Folium + Streamlit + FastAPI
- **Dataset:** Transactions w.Const.date_v2.csv — ~1M registros CBR, RM Santiago, 2013-2014
- **Real_Value scale:** Requiere validación manual (puede estar en pesos CLP o UF). clean_transactions.py detecta automáticamente.
- **MVP scope:** Solo RM de Santiago. Otras regiones → V2.
- **Model version:** v1.0 para el MVP
- **Scoring:** undervaluation_score + data_confidence → opportunity_score (0-1)
- **Phase 9 — Prefect 3 YAML:** Used `prefect.yaml` (Prefect 3 style) instead of V2 `deployment build/apply` — installed version is 3.6.27
- **Phase 9 — DI cron:** `daily-di` cron `0 11 * * *` (07:00 CLT, UTC-4); acceptable DST drift to 08:00 CLST
- **Phase 9 — Parallel scrape gate:** 5,003 listings (4,922 PI + 81 Toctoc) — status PASS; DI produced 0 (cookies absent, --skip-di used)

## Accumulated Context

### Roadmap Evolution

- Phase 9 added: Scraping Paralelo Multi-fuente (sin credenciales) — Toctoc paralelo (asyncio 4 tipos), PI por-comuna (40×4), Data Inmobiliaria guest 1 comuna/día via Prefect

## Warnings

- Dataset antiguo (2013-2014). Útil para validar metodología, no para precios actuales.
- Real_Value en algunos registros parece estar en CLP, no UF. Verificar antes de usar.
- Solo Región Metropolitana. No generalizar modelos a otras regiones.

## Sesión 2026-05-02 — Asset Subclass Engine + WARP scraping

### WARP scraping completado
- **16 → 27/40 comunas DI completas + 1 partial (Cerro Navia 406)**
- 11 comunas nuevas en sesión: Huechuraba, San Joaquín, La Cisterna, Colina, San Ramón, Lo Espejo, Pedro Aguirre Cerda, Lo Prado, Cerro Navia, Recoleta, Quinta Normal
- Total rows DI checkpoint: 117,383 (134,811 en transactions_raw)
- WARP loop autónomo con auto-reconnect: 6 corridas, detectó pool exhausted correctamente

### Pipeline post-scrape ejecutado
- transactions_clean: 916,895 rows (+133k)
- transaction_features: 865,583 rows (+131k)
- Modelo retrained: R²=0.6694, n_train=598,561 (+78k vs anterior)
- model_scores: 4 perfiles × 610,824 = 2,443,296 rows (default/location/growth/safety)
- High-opp (>0.7): 243,467 candidatos

### Asset Subclass Weights Engine — NUEVO (Opus diseñó, Sonnet ejecutó)
- **prompts/asset_subclass_weights_engine.md** — master plan completo
- **db/migrations/015_asset_subclass_weights.sql** — tabla con 14 subclases seeded
- **db/migrations/016_subclass_scores_jsonb.sql** — JSONB column en model_scores
- **src/scoring/asset_subclass.py** — scorer multi-dimensional (12 dim × 14 subclases)
- **src/api/routes/subclass.py** — 4 endpoints (list/weights/heatmap/update)
- **frontend/src/components/SubclassSelector.tsx** — selector UI agrupado por parent_class
- **frontend/src/components/SubclassHeatmapLayer.tsx** — Deck.gl HeatmapLayer hook
- 14 subclases cubiertas: apartment_income/flip, house_income/flip, land_residential/commercial_dev,
  gas_station, pharmacy, supermarket, bank_branch, clinic, restaurant, office_class_a, warehouse

### Multi-agente y security
- Trigger DB valida sum(weights)=1.0 antes de INSERT/UPDATE
- POST /subclasses/{name}/weights protegido (TODO: JWT admin role)
- Aditivo — no rompe opportunity_score existente, JSONB es opt-in
- Frontend pre-existente sigue funcionando sin cambios

### Bloqueado en usuario (5 min cuando vuelva)
- Cuenta Oracle Cloud confirmada Always Free (badge "Always Free-eligible" verificado en VM.Standard.A1.Flex)
- URL repo público GitHub para que oracle_one_paste.sh pueda clonar
- Pegar oracle_one_paste.sh en Cloud Shell (provisiona 3 VMs ARM)
- SCP cookies a las 3 VMs

### Próximos pasos automatizables
- Task Scheduler 06:00 03/05 → cron diario con WARP/quota fresca
- Cuando user provea URL repo → ejecutar Oracle setup (auto)
