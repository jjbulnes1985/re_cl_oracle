# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**RE_CL** — Real estate undervaluation detection platform for Chile's Región Metropolitana de Santiago. Trains a hedonic XGBoost model on CBR transaction data (2008-2018), computes opportunity scores, and surfaces results via Folium maps, Streamlit dashboard, FastAPI, and React + Deck.gl frontend. Live market data from Portal Inmobiliario + Toctoc + Yapo + MercadoLibre scrapers. 16 spatial features from local ieut-inciti shapefiles (Phase 8).

## Commands

### Environment
```bash
cp .env.example .env          # fill in POSTGRES_PASSWORD, RAW_CSV_PATH
docker-compose up -d          # PostgreSQL + PostGIS on :5432

psql -U re_cl_user -d re_cl -f db/schema.sql
psql -U re_cl_user -d re_cl -f db/migrations/001_transaction_features.sql
psql -U re_cl_user -d re_cl -f db/migrations/002_scraped_listings.sql
```

### Pipeline (in order)
```bash
py src/ingestion/load_transactions.py          # CSV → transactions_raw
py src/ingestion/clean_transactions.py         # → transactions_clean
py src/features/build_features.py              # → transaction_features
py src/models/hedonic_model.py                 # → models/hedonic_model.pkl
py src/scoring/opportunity_score.py            # → model_scores  (default profile)
py src/scoring/opportunity_score.py --profile location   # named profile
py src/maps/commune_ranking.py                 # → commune_stats
py src/maps/heatmap.py                         # → data/exports/heatmap_v1.0.html
```

### Prefect orchestration (V2)
```bash
py src/pipelines/flows.py                      # full pipeline (local)
py src/pipelines/flows.py --flow scoring_only
py src/pipelines/flows.py --flow maps_only
py src/pipelines/flows.py --flow scraping --max-pages 50

# Deploy to Prefect server:
prefect deployment build src/pipelines/flows.py:full_pipeline -n weekly --cron "0 3 * * 0"
prefect deployment apply full_pipeline-deployment.yaml
```

### Scraping (V2 — requires playwright)
```bash
pip install playwright && playwright install chromium

# Portal Inmobiliario — NOTE: MeLi gates pagination behind login.
# Page 1 per type = 48 listings each. Use --by-commune for maximum coverage.
py src/scraping/portal_inmobiliario.py --max-pages 1 --type apartments
py src/scraping/portal_inmobiliario.py --by-commune --type apartments   # 40 communes × 48 = 1,920 listings
py src/scraping/portal_inmobiliario.py --by-commune                     # all 4 types, 40 communes each
py src/scraping/portal_inmobiliario.py --dry-run
py src/scraping/portal_inmobiliario.py --dump-html --type apartments    # debug selectors

# Toctoc — no login required, pagination works freely
py src/scraping/toctoc.py --max-pages 100 --type apartments             # ~2,000 writes (~77 unique/type)
py src/scraping/toctoc.py --max-pages 100                               # all 4 types
py src/scraping/toctoc.py --dump-html                                   # debug __NEXT_DATA__ structure

# Yapo — Phase 8 (Playwright)
py src/scraping/yapo.py --max-pages 50                                  # all 4 types
py src/scraping/yapo.py --type apartments --max-pages 100
py src/scraping/yapo.py --dump-html                                     # debug page structure

# MercadoLibre Inmuebles — Phase 8 (REST API, no Playwright required)
py src/scraping/mercadolibre.py                                         # all types, max 1000 offset each
py src/scraping/mercadolibre.py --type apartments --max-offset 1000
py src/scraping/mercadolibre.py --dry-run

# County normalization (run after scraping, before scoring)
py src/ingestion/normalize_county.py                                    # fuzzy match → 40 RM communes
py src/ingestion/normalize_county.py --report                           # show county distribution
```

### CBR 2017-2018 ingestion (Phase 8 — ieut-inciti dataset)
```bash
# Apply migrations first
psql -U re_cl_user -d re_cl -f db/migrations/012_cbr_2018.sql
psql -U re_cl_user -d re_cl -f db/migrations/013_ieut_spatial.sql

# Load additional CBR data (677k + 80k rows, years 2015-2018)
py src/ingestion/load_cbr_2018.py                                       # both sources
py src/ingestion/load_cbr_2018.py --source completo --min-year 2015    # transacciones27062018
py src/ingestion/load_cbr_2018.py --source actualizacion               # 191118 update (2017-2018)
py src/ingestion/load_cbr_2018.py --dry-run

# ieut-inciti spatial features (16 distances from local shapefiles)
# Requires: IEUT_DATA_DIR env var or default path (Dropbox)
py src/features/ieut_spatial_features.py                               # ~30min on CPU
py src/features/ieut_spatial_features.py --dry-run

# Full feature rebuild including ieut (step 6)
py src/features/build_features.py                                      # includes ieut step
py src/features/build_features.py --skip-ieut                         # skip if shapefiles unavailable
```

### Applications
```bash
streamlit run src/dashboard/app.py             # Dashboard on :8501
uvicorn src.api.main:app --reload --port 8000  # API on :8000 (docs: /docs)

# React frontend (V2)
cd frontend && npm install && npm run dev       # Dev server on :3000
cd frontend && npm run build                   # Production build → frontend/dist/
```

### Reports (V5)
```bash
py src/reports/generate_report.py              # → data/exports/report_YYYY-MM-DD.html
py src/reports/generate_report.py --top-n 50  # top 50 opportunities
```

### Alerts API (V5)
```bash
curl http://localhost:8000/alerts/opportunities
curl "http://localhost:8000/analytics/price-trend?county_name=Las+Condes"
```

### Setup — cold start (V5)
```bash
bash scripts/setup_pipeline.sh                         # single-command full setup
py scripts/setup_pipeline.py --from-step 5            # resume from step 5
py scripts/setup_pipeline.py --skip-osm --skip-backtest
```

### GTFS bus stops (V6.3)
```bash
py src/features/gtfs_features.py --dry-run          # preview (downloads DTPM GTFS)
py src/features/gtfs_features.py --force-refresh     # re-download stops
py src/features/build_features.py --skip-gtfs        # build without GTFS
```

### Auth API (V6.6)
```bash
curl -X POST http://localhost:8000/auth/register -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"mypassword"}'
curl -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"mypassword"}'
curl http://localhost:8000/auth/me -H "Authorization: Bearer <token>"
curl -X POST http://localhost:8000/searches -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" -d '{"name":"Las Condes","filters":{"county":"Las Condes"}}'
```

### Tests
```bash
py -m pytest tests/ -v                         # All 296 tests (4 skipped: statsmodels)
py -m pytest tests/test_auth.py -v             # Auth + saved searches
py -m pytest tests/test_gtfs_features.py -v   # GTFS integration
py -m pytest tests/test_scoring.py -v
py -m pytest tests/test_api_v4.py -v
```

## Architecture

```
src/
├── ingestion/       # CSV → PostgreSQL (load, clean)
├── features/
│   ├── price_features.py       # gap_pct (winsorizado), percentiles p25/p50/p75, thesis features
│   ├── spatial_features.py     # dist_km_centroid, DBSCAN clusters
│   ├── temporal_features.py    # quarter dummies, season_index
│   ├── build_features.py       # Orquestador idempotente → transaction_features (5 steps incl. GTFS)
│   ├── osm_features.py         # OSM/Metro proximity features (V4.2)
│   ├── gtfs_features.py        # DTPM GTFS bus stop proximity (V6.3)
│   └── commune_context.py      # INE census + CEAD crime enrichment (V5.2/V5.3)
├── models/          # hedonic_model.py: XGBoost + LabelEncoders → models/
├── scoring/
│   ├── undervaluation.py       # gap percentile score
│   ├── opportunity_score.py    # composite score + profile dispatch
│   ├── shap_explainer.py       # SHAP top-3 features
│   ├── scoring_profile.py      # configurable weighting profiles (6 profiles)
│   └── scraped_to_scored.py    # listings scrapeados → model_scores
├── backtesting/
│   ├── __init__.py
│   └── walk_forward.py         # Walk-forward backtest + OLS benchmark (V4.5)
├── maps/            # heatmap.py (Folium HTML), commune_ranking.py
├── reports/
│   ├── __init__.py
│   └── generate_report.py      # Self-contained HTML report generator (V5)
├── api/
│   ├── main.py                 # FastAPI app (CORS, rate limit, stale-data middleware)
│   ├── db.py                   # engine singleton + dep
│   ├── middleware/
│   │   └── stale_data.py       # X-Data-Age-Days / X-Data-Stale headers
│   └── routes/
│       ├── properties.py       # /properties (incl. /search, /comparables, /communes/enriched)
│       ├── scores.py           # GET /scores/{id}, /top, /summary
│       ├── profiles.py         # GET /profiles, POST /profiles/score
│       ├── analytics.py        # GET /analytics/price-trend, /score-distribution (V5)
│       ├── alerts.py           # GET /alerts/opportunities, /config, POST /test (V5)
│       ├── auth.py             # POST /auth/register, /login, /refresh; GET /auth/me (V6.6)
│       ├── saved_searches.py   # GET/POST/DELETE /searches (V6.6)
│       └── predict.py          # POST /predict — stateless ML prediction, no DB (V6)
├── pipelines/       # Prefect flows + tasks (V2+)
├── scraping/        # Portal Inmobiliario + Toctoc scrapers (V2)
├── alerts/          # Sistema de alertas (console/JSON/email/desktop)
└── dashboard/
    ├── app.py                  # Streamlit: 8 tabs incl. Finanzas, Enriquecimiento, Calidad
    ├── financial_panel.py      # DCF, cap rate, yield simulator (V5)
    └── quality_panel.py        # Data quality dashboard (V5)

frontend/            # React + Deck.gl — 8 tabs (V6)
├── src/
│   ├── App.tsx                 # Tab nav + auth button (Entrar/logout) + AuthModal
│   ├── store.ts                # Zustand (filters, profile, watchlist, compare, geolocation, auth, savedSearches)
│   ├── api.ts                  # Fetch wrappers + auth/searches API (authRegister/Login/Me, savedSearches CRUD)
│   ├── types.ts                # TypeScript types (incl. SavedSearch, AuthUser, AuthToken)
│   └── components/
│       ├── AuthModal.tsx       # Login/register modal (V6.7)
│       ├── Sidebar.tsx         # Filters + profile sliders + geolocation + "Guardar búsqueda" button
│       ├── DeckMap.tsx         # Deck.gl map + Metro/Comunas/Colegios/Parques overlays + address geocoding
│       ├── RankingPanel.tsx    # Ranked list: watchlist, comparator A/B, CSV export, total count
│       ├── DetailPanel.tsx     # Property detail + SHAP + radar chart + comparables
│       ├── CommunesPanel.tsx   # Commune ranking: crime_tier, educacion_score
│       ├── ComparatorPanel.tsx # Side-by-side A vs B comparator (V5.6)
│       ├── WatchlistPanel.tsx  # Saved properties + CSV export + Mis Búsquedas Guardadas (V6.7)
│       ├── TrendPanel.tsx      # SVG price trend + multi-commune compare (V5)
│       └── FinanzasPanel.tsx   # Native React DCF/cap-rate/yield/scenarios (V6)

db/migrations/
├── 001_transaction_features.sql
├── 002_scraped_listings.sql
├── 003_thesis_features.sql      # age, age_sq, city_zone, construction_year_bucket, log_surface
├── 004_osm_features.sql         # dist_metro_km, dist_bus_stop_km, amenities_500m/1km
├── 005_commune_enrichment.sql
├── 006_commune_stats_enrichment.sql
├── 007_spatial_indexes.sql      # GiST + B-tree performance indexes
├── 008_gtfs_features.sql        # dist_gtfs_bus_km (V6.3)
└── 009_users_saved_searches.sql # users, saved_searches tables (V6.6)

scripts/
├── setup_pipeline.py            # Complete pipeline orchestrator (V5, --skip-gtfs flag)
└── setup_pipeline.sh            # Single-command cold start (V5)

data/processed/
├── commune_growth_index.csv     # INE growth data + metro stations
├── commune_ine_census.csv       # INE Censo 2017 estimates (V5.2)
├── commune_crime_index.csv      # CEAD crime index estimates (V5.3)
└── gtfs_stops.pkl               # Cached DTPM bus stops (auto-generated, V6.3)
```

## Scoring Profiles

The opportunity score supports 4 built-in profiles + custom mode:

| Profile | Weights | Use case |
|---------|---------|----------|
| `default` | underval 70% + confidence 30% | Baseline |
| `location` | underval 40% + location 40% + confidence 20% | Accesibilidad / zona |
| `growth` | underval 35% + growth 35% + confidence 30% | Crecimiento demográfico |
| `liquidity` | underval 50% + volume 30% + confidence 20% | Salida rápida |
| `custom` | user-defined, auto-normalized | Inversión personalizada |
| `safety` | underval 45% + crime 25% + confidence 20% + growth 10% | Seguridad e inversión en comunas seguras |

**CLI:** `py src/scoring/opportunity_score.py --profile location`
**API:** `POST /profiles/score` with `{"profile": "location"}` or `{"weights": {...}}`
**Dashboard:** selector en sidebar con sliders para modo custom
**Frontend:** sidebar radio + sliders, re-scores live sin escribir a DB

## DB Tables

| Table | Description |
|-------|-------------|
| `transactions_raw` | CSV datos crudos |
| `transactions_clean` | Normalizados, dedup, confidence score |
| `transaction_features` | gap_pct, dist_km_centroid, cluster_id, thesis features, OSM, GTFS |
| `model_scores` | Scores por versión, SHAP top features JSONB |
| `commune_stats` | Agregados por comuna (incl. crime_index, educacion_score) |
| `scraped_listings` | Listings de portales (V2), upsert por (source, external_id) |
| `users` | Cuentas de usuario (email + pbkdf2 hash) — V6.6 |
| `saved_searches` | Filtros guardados por usuario (JSONB) — V6.6 |
| `commune_calibration` | Residuales medianos por (model_version, county_name, project_type) — corrección post-hoc del modelo global (128 rows, 40 comunas) |
| `land_comparable_stats` | Benchmarks de precio de terreno por (model_version, county_name, year) — 318 rows (V7) |
| `v_opportunities` | Vista join: scores + clean data + calibration, filtra outliers. Incluye calibrated_predicted_uf_m2 / calibrated_gap_pct |
| `v_land_opportunities` | Transacciones land-dominant (unknown) puntuadas vs mediana comunal. 35k oportunidades (V7) |
| `v_scraped_market` | Vista: precios de mercado fresco por comuna/tipo |

## Key Env Vars

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | Full Postgres URL |
| `POSTGRES_HOST/PORT/DB/USER/PASSWORD` | localhost/5432/re_cl/re_cl_user/— | |
| `MODEL_VERSION` | `v1.0` | Tags scores — idempotent re-runs |
| `EXPORTS_DIR` | `data/exports` | HTML maps, CSV rankings |
| `SCORING_PROFILE` | `default` | Pipeline default profile |
| `WEIGHT_UNDERVALUATION` | `0.70` | Custom mode weight |
| `WEIGHT_CONFIDENCE` | `0.30` | Custom mode weight |
| `WEIGHT_LOCATION` | `0.00` | Custom mode weight |
| `WEIGHT_GROWTH` | `0.00` | Custom mode weight |
| `WEIGHT_VOLUME` | `0.00` | Custom mode weight |
| `WEIGHT_CRIME` | `0.00` | Safety profile crime weight |
| `UF_VALUE_APPROX` | `37000` | CLP→UF fallback for scraped data |
| `ALERT_MIN_SCORE` | `0.75` | Minimum score for opportunity alerts |
| `ALERT_MIN_GAP_PCT` | `-0.15` | Minimum gap_pct (negative = undervalued) |
| `ALERT_MIN_CONFIDENCE` | `0.65` | Minimum data_confidence for alerts |
| `JWT_SECRET_KEY` | `dev-secret-change-in-production` | JWT signing key (V6.6) |
| `JWT_EXPIRE_MINUTES` | `1440` | Token TTL in minutes (V6.6) |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/properties` | List + filters (project_type, county_name, city_zone, score, year) + `X-Total-Count` header |
| GET | `/properties/search?q=` | Full-text ILIKE search on county_name/project_type (V6) |
| GET | `/properties/{id}` | Detail + SHAP top-3 |
| GET | `/properties/{id}/comparables` | N comparables by Haversine + surface/age/type filters |
| GET | `/properties/communes` | Commune stats |
| GET | `/properties/communes/enriched` | Commune stats + crime_index + INE fields |
| GET | `/scores/{id}` | Score + SHAP |
| GET | `/scores/top` | Top-N scores |
| GET | `/scores/summary` | Aggregate stats |
| GET | `/profiles` | List built-in profiles |
| POST | `/profiles/score` | Re-score in-memory with custom profile/weights |
| GET | `/analytics/price-trend` | Price trend quarterly by type/commune |
| GET | `/analytics/price-trend/by-commune` | Trend for top N communes |
| GET | `/analytics/score-distribution` | Score distribution by decile |
| GET | `/alerts/opportunities` | Top alerts above threshold |
| GET | `/alerts/config` | Alert configuration from env vars |
| POST | `/alerts/test` | Trigger test alert (console only) |
| POST | `/auth/register` | Create user account → JWT (V6.6) |
| POST | `/auth/login` | Verify credentials → JWT (V6.6) |
| GET | `/auth/me` | Current user info (requires Bearer) (V6.6) |
| POST | `/auth/refresh` | Issue fresh JWT for authenticated user (V6.6) |
| GET | `/searches` | List saved searches for user (V6.6) |
| POST | `/searches` | Create saved search (V6.6) |
| DELETE | `/searches/{id}` | Delete saved search (V6.6) |
| POST | `/predict` | Stateless ML price prediction (no DB, loads pkl) (V6) |
| GET | `/health` | Health check |

**Middleware:** CORS (expose all X-* headers), rate limit 100 req/60s (testclient exempt), X-Data-Age-Days stale detection

## Dataset Constraints

- CBR Región Metropolitana, 2008-2018 (cbr_v1: 1,048,557 rows 2008-2016; cbr_2018: 266,913 rows 2015-2017; cbr_actualizacion_2018: 71,317 rows 2017-2018). Total transactions_raw: 1,386,787 rows. transactions_clean: 783,637. transaction_features: 734,334.
- `Real_Value` auto-detected CLP vs UF (ratio threshold 500).
- Coordinates validated within Chile bbox: lat [-56, -17], lon [-76, -65].
- `pythonpath = ["."]` in `pyproject.toml` — all `src.*` imports run from `re_cl/`.
- DBSCAN: `eps_km=0.5, min_samples=10` prod; tests use `eps_km=5.0, min_samples=3`.

## Status (2026-04-21)

| Component | Status |
|-----------|--------|
| DB schema + Docker | Done |
| Ingestion + cleaning | Done |
| Feature engineering (precio + espacial + temporal) | Done |
| Thesis features (age, age², city_zone, year_bucket, log_surface) | Done (V4.1) |
| OSM enrichment (metro, bus, schools, hospitals, parks, malls) | Done (V4.2) |
| GTFS RED bus stop proximity (dist_gtfs_bus_km) | Done (V6.3) |
| Hedonic model XGBoost + SHAP | Done |
| Scoring 6 profiles (default/location/growth/liquidity/custom/safety) | Done |
| Walk-forward backtesting + OLS benchmark | Done (V4.5) |
| Folium heatmap + commune ranking | Done |
| Streamlit dashboard (8 tabs + financial + quality panels) | Done |
| FastAPI (28 endpoints — properties, scores, profiles, analytics, alerts, auth, searches, predict) | Done |
| API middleware (CORS, rate limit, stale-data headers, X-Total-Count) | Done (V6) |
| /properties/search full-text + /properties/export CSV endpoints | Done (V6) |
| /predict stateless ML endpoint (no DB, lru_cache pkl) | Done (V6) |
| /auth/refresh endpoint (re-issue JWT) | Done (V6.6) |
| Tests (296 passing, 4 skipped statsmodels) | Done |
| Prefect orchestration (daily + weekly + backtest + GTFS + webhook) | Done (V2+/V6) |
| Scraping (Portal Inmobiliario + Toctoc) | Done (V2 — live validation pending) |
| React + Deck.gl frontend (8 tabs, Docker build) | Done |
| DeckMap: Metro/Comunas/Colegios/Parques overlays + address geocoding | Done (V5.5/V6) |
| FinanzasPanel: native React DCF/cap-rate/yield/scenarios | Done (V6) |
| AuthModal: login/register modal en frontend | Done (V6.7) |
| Frontend auth state: token + user en Zustand, persistido en localStorage | Done (V6.7) |
| Sidebar: botón "Guardar búsqueda actual" (requiere auth) | Done (V6.7) |
| WatchlistPanel: sección "Mis Búsquedas Guardadas" (aplicar/eliminar) | Done (V6.7) |
| App.tsx: botón Entrar/logout en nav top | Done (V6.7) |
| Docker full stack + Nginx (bug nginx.conf worker_processes corregido) | Done (V3/V6.7) |
| Alert system (console/JSON/email/desktop/webhook) | Done (V3/V6) |
| INE Census 2017 + CEAD crime static data (34 comunas RM) | Done (V5.2/V5.3) |
| JWT auth (register/login/refresh/me) + saved searches API | Done (V6.6) |
| DB: users + saved_searches tables (migration 009) | Done (V6.6) |
| HTML report generator (generate_report.py) | Done (V5) |
| Setup orchestrator (setup_pipeline.py/.sh) | Done (V5) |
| PostGIS GiST + B-tree indexes (migration 007) | Done |
| **Ejecutar pipeline con CSV real** (1,048,557 raw → 562,854 clean → R²=0.679 → 455,945 scored → 40 comunas → heatmap + report) | **Completado 2026-04-20** |
| Dashboard Deal Flow UX (dirección, Rol SII, vendedor CBR, Google Maps link, drill-down por comuna) | Completado 2026-04-20 |
| Portal Inmobiliario scraper — selectores MeLi Polaris UI 2025 + fix ext_id/county/surface (48/48 listings con datos) | Completado 2026-04-21 |
| **Commune calibration** — tabla commune_calibration + corrección post-hoc (128 rows, 40 comunas, migration 010) | **Completado 2026-04-21** |
| **Land scoring** — v_land_opportunities + land_comparable_stats (35k opps, comparable-based, migration 011) | **Completado 2026-04-21** |
| **UF/m² floors actualizados** — PRICE_LIMITS relajados (apartments 8, residential 5, retail 7); view floor 10 para built | **Completado 2026-04-21** |
| **Dashboard tab Terrenos** — render_land_tab() con KPIs, filtros, tabla y detalle top oportunidad | **Completado 2026-04-21** |
| **Dashboard calibrated columns** — pred/gap calibrado en ranking, detalle y tabla comunal | **Completado 2026-04-21** |
| **San Ramón encoding fix** — mojibake UTF-8 corregido en transactions_clean (2,300 registros) | **Completado 2026-04-21** |
| **Data audit multiagente** — verificación de v_opportunities, v_land_opportunities, calibration, San Ramón; floor 2.0 UF/m² land | **Completado 2026-04-21** |
| Scraper PI — fix ext_id (MLC regex), county (parts[1]), surface ([class*=attribute]), project_type fallback | Completado 2026-04-21 |
| Scraper Toctoc — fix URL (/venta/departamento), parser (propiedades.results), wait_for_function | Completado 2026-04-21 |
| base._parse_surface — manejo de rangos "23-38 m² útiles" con midpoint | Completado 2026-04-21 |
| scraped_listings poblado: 68 listings (48 PI + 20 Toctoc), 15-18 comunas | Completado 2026-04-21 |
| Backtesting calibración comunal: MAE +1.0%, RMSE +0.8% — Lo Prado +5.8%, La Granja +5.3% | Completado 2026-04-21 |
| React frontend: calibrated_predicted_uf_m2 + calibrated_gap_pct en DetailPanel + RankingPanel | Completado 2026-04-21 |
| **base.scrape_async** — fix wait_until domcontentloaded + context rotation cada 10 páginas (anti-bot) | Completado 2026-04-21 |
| **Toctoc escalado** — 100 páginas × 4 tipos = 8,000 writes, ~77 unique (alto overlap, Toctoc RM limitado) | Completado 2026-04-21 |
| **PI pagination gate** — MeLi exige login para _Desde_N; solución: --by-commune (40 comunas × page 1 × 4 tipos = ~7,680) | Completado 2026-04-21 |
| **PI --by-commune** — RM_COMMUNES dict (40 comunas) + _build_url(commune_slug) + run(by_commune=True) | Completado 2026-04-21 |
| **Phase 8 plan** — PLAN.md en .planning/phases/08-maximize-data/ con 3 tracks (CBR 2018, ieut spatial, scrapers) | Completado 2026-04-21 |
| **Migration 012** — data_source column en transactions_raw | Completado 2026-04-21 |
| **Migration 013** — 16 columnas ieut spatial en transaction_features | Completado 2026-04-21 |
| **load_cbr_2018.py** — ingesta CBR 2017-2018 (677k + 80k filas desde ieut-inciti) | Completado 2026-04-21 |
| **ieut_spatial_features.py** — 16 features BallTree desde shapefiles locales (Áreas Verdes, Comercio, Conectividad, Equipamiento, NIMBYs) | Completado 2026-04-21 |
| **yapo.py** — scraper Yapo.cl (Playwright, ~3-5k listings esperados) | Completado 2026-04-21 |
| **mercadolibre.py** — scraper ML API REST sin Playwright (~5-8k listings esperados) | Completado 2026-04-21 |
| **normalize_county.py** — fuzzy normalization county_name con rapidfuzz (score≥85 → comuna canónica) | Completado 2026-04-21 |
| **hedonic_model.py** — NUM_FEATURES + 16 ieut features; load_training_data SQL actualizado | Completado 2026-04-21 |
| **scraped_to_scored.py** — _add_model_defaults() + 16 NaN defaults ieut | Completado 2026-04-21 |
| **build_features.py** — paso 6: ieut_spatial_features (--skip-ieut flag) | Completado 2026-04-21 |
| **Ejecutar load_cbr_2018.py** — completo: 262,496 rows + actualizacion: 71,317 rows → transactions_raw: 1,386,787 total | **Completado 2026-04-21** |
| **Ejecutar clean_transactions.py** — 783,637 filas limpias | **Completado 2026-04-21** |
| **Ejecutar build_features.py --skip-ieut** — 734,334 rows en transaction_features | **Completado 2026-04-21** |
| **Reentrenar hedonic model** — 479,628 rows, R²=0.6819 (mejoró de 0.679) | **Completado 2026-04-21** |
| **Ejecutar opportunity_score.py** — 479,628 rows scored + SHAP → 405,838 en v_opportunities | **Completado 2026-04-21** |
| **Scraping PI --by-commune** — 4,523 listings (40 comunas × 4 tipos) | **Completado 2026-04-21** |
| **scraped_to_scored.py** — 1,870 scraped listings scored + escritos en model_scores | **Completado 2026-04-21** |
| **normalize_county.py** — county names normalizados en scraped_listings | **Completado 2026-04-21** |
| **load_cbr_2018.py fix** — StringDataRightTruncation: VARCHAR truncation + date parsing | **Completado 2026-04-21** |
| **hedonic_model.py fix** — ieut object dtype → float coercion antes de XGBoost | **Completado 2026-04-21** |
| **yapo.py fix** — source_name, raw_json, AJAX wait (bloqueado por reCAPTCHA v3) | **Completado 2026-04-21** |
| **mercadolibre.py fix** — source_name en _MLWriter (bloqueado por OAuth2/403) | **Completado 2026-04-21** |
| **ieut_spatial_features.py** — 751,506 rows actualizados, 16 features pobladas (~38min CPU) | **Completado 2026-04-21** |
| **Retrain hedonic model con ieut** — R²=0.6850 (subió de 0.6819), RMSE=39.9% | **Completado 2026-04-21** |
| **opportunity_score.py** — 961,126 scored (959,256 transactions + 1,870 scraped), 808,860 en v_opportunities | **Completado 2026-04-21** |
| **scraped_to_scored.py** — 1,870 scraped listings scored, top opp: Santiago apartments score=0.873 | **Completado 2026-04-21** |
| **Portal audit + fixes (3 agentes)** — Streamlit: 5 bugs (calibrated cols, project_type_name); FastAPI: 4 bugs (shap type, profiles query, alerts default_factory, stale middleware); React: DetailPanel error state, SHAP parsing | **Completado 2026-04-21** |
| **nginx.conf** — resolver 127.0.0.11 + proxy_read_timeout 120s (502/504 fix); API limit 5k→10k | **Completado 2026-04-21** |
| **Data Inmobiliaria** — Investigado: datainmobiliaria.cl, 9M+ propiedades, 15 años CBR, registro gratis=queries ilimitadas, API $100k CLP/mes | **Investigado 2026-04-21** |
| Yapo: requiere proxy o sesión manual (bloqueado por reCAPTCHA v3 en headless) | Pendiente |
| ML: requiere OAuth2 token (API bloqueada 403 PolicyAgent sin credenciales) | Pendiente |
| Data Inmobiliaria scraper — construir scraper para CBR 2019-2026 | Pendiente |

## Migration sequence

```bash
# Applied automatically by Docker on first boot (docker-compose up -d)
# Manual order for psql:
psql -U re_cl_user -d re_cl -f db/schema.sql
psql -U re_cl_user -d re_cl -f db/migrations/001_transaction_features.sql
psql -U re_cl_user -d re_cl -f db/migrations/002_scraped_listings.sql
psql -U re_cl_user -d re_cl -f db/migrations/003_thesis_features.sql
psql -U re_cl_user -d re_cl -f db/migrations/004_osm_features.sql
psql -U re_cl_user -d re_cl -f db/migrations/005_commune_enrichment.sql
psql -U re_cl_user -d re_cl -f db/migrations/006_commune_stats_enrichment.sql
psql -U re_cl_user -d re_cl -f db/migrations/007_spatial_indexes.sql
psql -U re_cl_user -d re_cl -f db/migrations/008_gtfs_features.sql
psql -U re_cl_user -d re_cl -f db/migrations/009_users_saved_searches.sql
psql -U re_cl_user -d re_cl -f db/migrations/010_commune_calibration.sql
psql -U re_cl_user -d re_cl -f db/migrations/011_land_scoring.sql
psql -U re_cl_user -d re_cl -f db/migrations/012_cbr_2018.sql
psql -U re_cl_user -d re_cl -f db/migrations/013_ieut_spatial.sql
```

## Notes

- `pythonpath = ["."]` in `pyproject.toml` — all `src.*` imports run from `re_cl/`.
- DBSCAN: `eps_km=0.5, min_samples=10` prod; tests use `eps_km=5.0, min_samples=3`.
- CBR data: 2008-2016 original + 2015-2018 ieut-inciti extension. `Real_Value` auto-detected CLP vs UF.
- ieut-inciti shapefiles: set IEUT_DATA_DIR env var. Default path: `C:\Users\jjbul\Dropbox\Documentos\Master\Post_llegada\ieut - inciti\Data`
- MercadoLibre scraper uses REST API (no Playwright). Yapo uses Playwright.
- Auth uses `pbkdf2_sha256` (passlib) — bcrypt has Python 3.13 compatibility issues.
- Rate limiter exempts `testclient` IP so pytest suites don't hit 429 after ~100 requests.
- GTFS cache: `data/processed/gtfs_stops.pkl` (7-day TTL). Use `--force-refresh` to update.
- JWT default secret is dev-only — set `JWT_SECRET_KEY` in `.env` for production.
- Nginx config: `worker_processes` must be at global level, NOT inside `events {}` block.
- Frontend auth token + user persisted in localStorage via Zustand persist middleware.
- Frontend Docker: multi-stage build (node:20-alpine builder → nginx:alpine), `npm run build`.
- Saved searches: stored in DB (PostgreSQL JSONB / SQLite TEXT), applied client-side via setFilters.
