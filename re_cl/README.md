# RE_CL — Real Estate Intelligence Platform for Santiago RM

> Detects undervalued properties in Chile's Región Metropolitana using XGBoost hedonic pricing,
> OSM enrichment, CEAD crime data, and SHAP explainability.
>
> Built on a **2017 MIT thesis on Chilean real estate price indices** (MIT MSRED, Juan José Bulnes Valdés).

---

## Architecture Overview

RE_CL is a five-layer platform designed for professional real estate analysis and investment screening:

| Layer | Technology | Role |
|-------|-----------|------|
| **Storage** | PostgreSQL 15 + PostGIS | Transactions, scores, spatial data |
| **ETL / ML** | Python 3.11, XGBoost, SHAP, Prefect | Ingestion, feature engineering, hedonic model, scoring |
| **API** | FastAPI | REST endpoints consumed by frontend and external tools |
| **Visualization** | React + Deck.gl, Streamlit, Folium | Interactive 3D map, dashboard, static exports |
| **Infrastructure** | Docker Compose + Nginx | Single-host deployment, reverse proxy at `http://localhost` |

Data flows: `CSV (CBR) → transactions_raw → transactions_clean → transaction_features → model_scores → v_opportunities → API → Frontend`.

---

## Quick Start (Docker)

```bash
cp .env.example .env    # Fill in POSTGRES_PASSWORD and RAW_CSV_PATH
bash scripts/setup_pipeline.sh  # Docker + migrations + full pipeline (~15 min)
# Open: http://localhost          (React frontend)
#       http://localhost/dashboard (Streamlit)
#       http://localhost:8000/docs (API docs)
```

> **Requirements:** Docker Desktop, Docker Compose v2, Python 3.11 (for local scripts).

---

## Full Pipeline

Run each step independently or use the Prefect orchestration (see Flows below).

```bash
# 1. Start services
cd re_cl && docker-compose up -d

# 2. Apply DB migrations
docker exec -i re_cl_db psql -U postgres -d re_cl < db/schema.sql
docker exec -i re_cl_db psql -U postgres -d re_cl < db/migrations/001_transaction_features.sql
docker exec -i re_cl_db psql -U postgres -d re_cl < db/migrations/002_scraped_listings.sql

# 3. Ingest raw CSV (~1M rows, 151 MB)
python src/ingestion/load_transactions.py

# 4. Clean and normalize
python src/ingestion/clean_transactions.py --dry-run   # Review report first
python src/ingestion/clean_transactions.py

# 5. Feature engineering
python src/features/build_features.py

# 6. Train hedonic model + generate SHAP scores
python src/models/hedonic_model.py

# 7. Compute opportunity scores
python src/scoring/opportunity_score.py

# 8. Generate maps and commune rankings
python src/maps/heatmap.py
python src/maps/commune_ranking.py

# 9. (Optional) Score scraped listings
python src/scoring/scraped_to_scored.py
```

---

## Key Features

- **Hedonic pricing model** — XGBoost trained on ~1M CBR transactions (RM, 2013–2014), predicting UF/m² with temporal train/test split.
- **SHAP explainability** — Top-3 SHAP drivers per property surfaced in the API, dashboard, and frontend detail panel.
- **Undervaluation scoring** — `gap_pct` (actual vs. predicted price gap) converted to a percentile rank; configurable via profiles.
- **Spatial features** — Distance to commune centroid (EPSG:32719), DBSCAN clusters at 500 m radius via BallTree subsampling.
- **Temporal features** — Quarter dummies, season index, year; model trained on 2013 → validated on 2014 (walk-forward).
- **Scoring profiles** — Six investor profiles weighting subvaluation, location, growth, and liquidity differently.
- **OSM enrichment (V4.2)** — POIs via Overpass API: metro, schools, hospitals, parks, malls; distances as model features.
- **GTFS enrichment (V4.2)** — RED/Metro bus stops and route coverage within 1 km.
- **INE Census enrichment (V4.3)** — Population density, education level, overcrowding index at block level (Censo 2017).
- **CEAD crime index (V4.4)** — Criminalidad por comuna as a scoring penalty / map layer.
- **Prefect orchestration** — Automated daily (06:00) and weekly (Sunday 03:00) pipelines with full/scoring/maps/scraping flows.
- **Scrapers** — Playwright-based scrapers for Portal Inmobiliario and Toctoc; listings fed directly into `model_scores`.
- **Alert system** — Console, JSON, email, and desktop notifications when high-opportunity properties are detected.
- **Data confidence score** — Per-record quality flag used as a model feature and filtering criterion.

---

## API Reference

Base URL: `http://localhost:8000` | Interactive docs: `/docs`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/properties` | List properties with filters (commune, type, score range, bbox) |
| GET | `/properties/{id}` | Single property detail |
| GET | `/communes` | All communes with aggregate stats |
| GET | `/scores/{id}` | Score detail + SHAP top features |
| GET | `/scores/top` | Top N opportunities (default: 50) |
| GET | `/scores/summary` | Score distribution by commune |
| GET | `/profiles` | List available scoring profiles |
| POST | `/profiles/score` | Score a property using a custom profile |

All responses are JSON. Pagination via `limit` / `offset` query params.

---

## Frontend

React + Deck.gl SPA served at `http://localhost`. Four main tabs:

| Tab | Description |
|-----|-------------|
| **Map** | 3D scatter / heatmap / hexagon layers; color-coded by opportunity score |
| **Sidebar** | Filters (commune, property type, score threshold) + scoring profile sliders |
| **Ranking** | Paginated list of top-opportunity properties with quick-view metrics |
| **Detail** | Full property card with SHAP drivers and comparable transactions |
| **Communes** | Commune ranking table with growth index, median UF/m², and transaction volume |

> Screenshots: see `data/exports/` for static map exports and sample heatmaps.

---

## Streamlit Dashboard

Available at `http://localhost/dashboard`. Tabs include:

| Tab | Description |
|-----|-------------|
| **Mapa** | Folium heatmap with score overlay |
| **Oportunidades** | Filterable table of top opportunities |
| **Comunas** | Commune ranking with bar charts |
| **Modelo** | Feature importance and SHAP summary plots |
| **Scoring** | Profile comparison and score distribution |
| **Datos** | Raw data explorer with quality flags |
| **Finanzas** | Cap rate estimates, investment simulation, return scenarios |

---

## Scoring Profiles

| Profile | Subvaloración | Proximidad | Crecimiento comunal | Volumen | Confianza |
|---------|:---:|:---:|:---:|:---:|:---:|
| **default** | 70% | — | — | — | 30% |
| **location** | 40% | 40% | — | — | 20% |
| **growth** | 35% | — | 35% | — | 30% |
| **liquidity** | 50% | — | — | 30% | 20% |
| **custom** | user-defined | user-defined | user-defined | user-defined | user-defined |

Custom weights are entered via the frontend sliders or the `POST /profiles/score` endpoint and are automatically normalized to sum to 1.

---

## Model (V4.1 — MIT Thesis Integration)

The hedonic model targets `uf_m2_building` using XGBoost with temporal validation (train on 2013, evaluate on 2014).

**Feature dimensions:**

| Dimension | Variables |
|-----------|-----------|
| Price | `gap_pct`, `price_percentile_25/50/75`, `price_vs_median` |
| Location | `dist_km_centroid`, `cluster_id` (DBSCAN 500 m) |
| Temporal | `quarter_q1–q4`, `season_index`, `year` |
| Property | `surface_m2`, `surface_building_m2`, `surface_land_m2` |
| Quality | `data_confidence` |
| Categorical | `project_type`, `county_name` (label encoded) |

**V4 additions (OSM/INE/CEAD):**
`dist_metro_km`, `dist_school_km`, `dist_hospital_km`, `dist_park_km`, `dist_mall_km`, `amenities_500m`, `dist_bus_stop_km`, `n_bus_lines_1km`, `densidad_pob`, `nivel_educacion`, `hacinamiento_index`, `crime_index_comuna`.

**Thesis basis:** The price index methodology follows the repeat-sales and hedonic frameworks developed in the 2017 MIT MSRED thesis, adapted to Chilean CBR transaction data for the Región Metropolitana.

Trained model artifacts: `models/hedonic_model_v1.pkl`, `models/label_encoders_v1.pkl`.

---

## Data Sources

| Source | Description | Volume | Status |
|--------|-------------|--------|--------|
| **CBR Transactions** | Conservador de Bienes Raíces RM, 2013–2014 | ~1M rows, 151 MB | Loaded |
| **OSM Overpass API** | POIs: metro, schools, hospitals, parks, malls | Per commune | V4.2 |
| **GTFS RED/Metro** | Bus stops, route coverage | City-wide | V4.2 |
| **INE Censo 2017** | Population density, education, overcrowding (manzana level) | 42 communes RM | V4.3 estimates |
| **CEAD** | Criminalidad por comuna | 42 communes RM | V4.4 estimates |
| **Portal Inmobiliario** | Active listings (Playwright scraper) | Live | Scraper ready |
| **Toctoc** | Active listings (Playwright scraper) | Live | Scraper ready |

> Raw CSV is not committed to the repository. Set `RAW_CSV_PATH` in `.env`.

---

## Backtesting

Walk-forward validation using the CBR dataset:

- **Train:** 2013 transactions
- **Test:** 2014 transactions (out-of-sample)
- **Metrics:** RMSE, MAE, R² on UF/m²; opportunity detection precision/recall vs. realized price growth

Results are logged to `data/processed/` and surfaced in the Model tab of the Streamlit dashboard.

Future backtesting (V4.5) will extend to multi-year walk-forward windows once more recent CBR data is integrated.

---

## Development

```bash
# Install dependencies
pip install -r re_cl/requirements.txt

# Run all 62 tests
cd re_cl && pytest tests/ -v

# Dry-run cleaning (no DB writes)
python src/ingestion/clean_transactions.py --dry-run

# Prefect flows (requires Prefect server running)
python src/pipelines/flows.py          # Register all flows
# Schedules: daily 06:00 (scoring + maps + scraping)
#            weekly Sunday 03:00 (full pipeline)
```

**Adding a new feature:**
1. Define objective, risk, and completion criterion in the relevant source file docstring.
2. Add the feature computation to the appropriate `src/features/` module.
3. Register it in `build_features.py`.
4. Add a test in `tests/`.
5. Update `CLAUDE.md` feature table.

**Rules:**
- Never hardcode credentials. Use `.env` + `python-dotenv`.
- Obtain approval before truncating tables, modifying production schema, or running scrapers.
- All new features require a test.

---

## Project Structure

```
re_cl/
├── db/
│   ├── schema.sql                    # DDL: transactions_raw/clean, model_scores, v_opportunities
│   └── migrations/                   # 001_transaction_features, 002_scraped_listings
├── src/
│   ├── ingestion/                    # load_transactions.py, clean_transactions.py
│   ├── features/                     # price, spatial, temporal features + build_features.py
│   ├── models/                       # hedonic_model.py (XGBoost + SHAP)
│   ├── scoring/                      # undervaluation, opportunity_score, profiles, shap_explainer
│   ├── maps/                         # heatmap.py, commune_ranking.py
│   ├── pipelines/                    # flows.py (Prefect)
│   ├── scraping/                     # portal_inmobiliario.py, toctoc.py
│   ├── alerts/                       # console/JSON/email/desktop alert system
│   ├── api/                          # FastAPI app, routes (properties/scores/profiles)
│   └── dashboard/                    # Streamlit app
├── frontend/                         # React + Deck.gl (TypeScript)
│   └── src/
│       ├── App.tsx                   # Tab navigation
│       ├── store.ts                  # Zustand global state
│       ├── api.ts                    # FastAPI fetch wrappers
│       └── components/               # DeckMap, Sidebar, RankingPanel, DetailPanel, CommunesPanel
├── data/
│   ├── raw/                          # Source CSV (not committed)
│   ├── processed/                    # Model artifacts, commune_growth_index.csv
│   └── exports/                      # HTML maps, CSV rankings
├── models/                           # hedonic_model_v1.pkl, label_encoders_v1.pkl
├── tests/                            # 62 pytest tests
├── docker-compose.yml                # DB + API + Dashboard + Frontend + Nginx
├── Dockerfile                        # Python services
├── nginx.conf                        # Reverse proxy
├── requirements.txt
└── .env.example                      # Template: POSTGRES_PASSWORD, RAW_CSV_PATH, DATABASE_URL
```

---

## License

Proprietary. All rights reserved — Juan José Bulnes Valdés, 2024–2026.
