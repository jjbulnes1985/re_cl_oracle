# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Proyecto

**RE_CL** — Plataforma multiagente para detectar inmuebles subvalorados en Chile.
Especificación completa en [RE_CL.md](RE_CL.md). Código en [re_cl/](re_cl/).

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Base de datos | PostgreSQL 15 + PostGIS |
| ETL/Pipelines | Python 3.11, Pandas, SQLAlchemy |
| ML/Scoring | XGBoost, scikit-learn, SHAP |
| GIS/Mapas | GeoPandas, Folium, Deck.gl |
| Dashboard | Streamlit |
| Frontend | React + Deck.gl (mapa 3D interactivo) |
| API | FastAPI |
| Orquestación | Prefect |
| Scraping | Playwright (Portal Inmobiliario, Toctoc) |
| Entorno | Docker Compose + Nginx |

## Comandos principales

```bash
# Levantar base de datos
cd re_cl && docker-compose up -d

# Instalar dependencias Python
pip install -r re_cl/requirements.txt

# ETL: Cargar CSV en PostgreSQL (~1M filas, 151MB)
python re_cl/src/ingestion/load_transactions.py

# Limpiar y normalizar datos
python re_cl/src/ingestion/clean_transactions.py

# Dry run (solo reporte, sin escribir en DB)
python re_cl/src/ingestion/clean_transactions.py --dry-run

# Tests
cd re_cl && pytest tests/ -v

# Dashboard
streamlit run re_cl/src/dashboard/app.py

# Reports (V5)
py re_cl/src/reports/generate_report.py              # → data/exports/report_YYYY-MM-DD.html
py re_cl/src/reports/generate_report.py --top-n 50

# Alerts y Analytics API (V5)
curl http://localhost:8000/alerts/opportunities
curl "http://localhost:8000/analytics/price-trend?county_name=Las+Condes"

# Setup completo — cold start (V5)
bash re_cl/scripts/setup_pipeline.sh
py re_cl/scripts/setup_pipeline.py --from-step 5
py re_cl/scripts/setup_pipeline.py --skip-osm --skip-backtest

### Validation
```bash
py scripts/validate_data.py --json --exit-code    # 12 checks, fails if critical issues
py scripts/run_alerts.py --dry-run                 # Preview current opportunities
py scripts/run_alerts.py --limit 10 --output json  # Send alerts + save JSON (V6)
```
```

## Datos

- **`Transactions w.Const.date_v2.csv`** — ~1M transacciones del CBR, RM Santiago, **2008-2016** (9 años), 23 columnas. NOTA: documentación anterior decía "2013-2014" — incorrecto. Rango real verificado por auditoría 2026-04-20.
  Columnas clave: `Real_Value`, `Calculated_Value`, `UF_m2_u`, `Longitude`, `Latitude`, `County_Name`, `Project_Type_Name`.
- **`Commercial Real Estate Analysis and Investments 3rd Edition.pdf`** — Referencia metodológica.

**Advertencia:** Real_Value puede estar en pesos (CLP) en algunos registros. `clean_transactions.py` lo detecta y convierte. Revisar el reporte antes de continuar.

## Arquitectura del código

```
re_cl/
├── db/schema.sql                     # DDL: transactions_raw, transactions_clean, model_scores, v_opportunities
├── db/migrations/
│   ├── 001_transaction_features.sql  # transaction_features, commune_stats
│   └── 002_scraped_listings.sql      # scraped_listings, v_scraped_market
├── src/ingestion/
│   ├── load_transactions.py          # ETL chunked: CSV → transactions_raw + geom PostGIS
│   └── clean_transactions.py         # Limpieza: dedup, normalización UF, imputación, outliers, confidence score
├── src/features/
│   ├── price_features.py             # gap_pct (winsorizado), percentiles p25/p50/p75 por (tipo,comuna,año)
│   ├── spatial_features.py           # dist_km_centroid (EPSG:32719), DBSCAN clusters (subsample+BallTree)
│   ├── temporal_features.py          # quarter dummies, season_index
│   ├── build_features.py             # Orquestador idempotente → tabla transaction_features
│   ├── osm_features.py               # OSM/Metro proximity features (V4.2)
│   └── commune_context.py            # INE census + CEAD crime enrichment (V5.2/V5.3)
├── src/backtesting/
│   ├── __init__.py
│   └── walk_forward.py               # Walk-forward backtest + OLS benchmark (V4.5)
├── src/models/
│   └── hedonic_model.py              # XGBoost: predice uf_m2_building, train/test temporal, SHAP
├── src/scoring/
│   ├── undervaluation.py             # gap_pct → undervaluation_score (percentile rank)
│   ├── opportunity_score.py          # Score compuesto + perfiles (default/location/growth/liquidity/custom/safety)
│   ├── scoring_profile.py            # Definición y validación de perfiles de scoring
│   ├── shap_explainer.py             # Top-3 SHAP features por propiedad
│   └── scraped_to_scored.py          # Listings scrapeados → model_scores
├── src/maps/
│   ├── heatmap.py                    # Mapa Folium interactivo con scores
│   └── commune_ranking.py            # Ranking y estadísticas por comuna
├── src/reports/
│   ├── __init__.py
│   └── generate_report.py            # Self-contained HTML report generator (V5)
├── src/pipelines/
│   └── flows.py                      # Prefect: full/scoring/maps/scraping/daily + OSM/backtest flows
├── src/scraping/
│   ├── portal_inmobiliario.py        # Scraper Portal Inmobiliario (Playwright)
│   └── toctoc.py                     # Scraper Toctoc (Playwright)
├── src/alerts/                       # Sistema de alertas (console/JSON/email/desktop)
├── src/api/
│   ├── main.py                       # FastAPI app
│   ├── db.py                         # Engine singleton
│   └── routes/
│       ├── properties.py             # GET /properties, /communes, /properties/{id}, /communes/enriched
│       ├── scores.py                 # GET /scores/{id}, /top, /summary
│       ├── profiles.py               # GET /profiles, POST /profiles/score
│       ├── analytics.py              # GET /analytics/price-trend, /by-commune, /score-distribution (V5)
│       └── alerts.py                 # GET /alerts/opportunities, /config, POST /test (V5)
├── src/dashboard/
│   ├── app.py                        # Streamlit: 7 tabs incl. Finanzas, Enriquecimiento
│   ├── financial_panel.py            # DCF, cap rate, yield simulator (V5)
│   └── quality_panel.py             # Data quality dashboard (V5)
├── scripts/
│   ├── setup_pipeline.py             # Complete pipeline orchestrator (V5)
│   └── setup_pipeline.sh             # Single-command cold start (V5)
├── frontend/                         # React + Deck.gl — 8 tabs
│   ├── src/
│   │   ├── App.tsx                   # Tab navigation (Map, Ranking, Comunas, Detail, Comparar, Watchlist, Tendencias, Finanzas)
│   │   ├── store.ts                  # Zustand global state (filters, profile, watchlist, selected)
│   │   ├── api.ts                    # Fetch wrappers FastAPI
│   │   └── components/
│   │       ├── DeckMap.tsx           # Mapa 3D scatter/heatmap/hexagon + Metro/Communes overlays + geolocation
│   │       ├── Sidebar.tsx           # Filtros + scoring profile sliders
│   │       ├── RankingPanel.tsx      # Lista de propiedades rankeadas (watchlist, CSV export, comparator)
│   │       ├── DetailPanel.tsx       # Detalle propiedad + SHAP drivers + radar chart + comparables
│   │       ├── CommunesPanel.tsx     # Ranking comunas (crime_tier, educacion_score columns)
│   │       ├── ComparatorPanel.tsx   # Side-by-side property comparator (V5.6)
│   │       ├── WatchlistPanel.tsx    # Saved properties + CSV export (V5)
│   │       └── TrendPanel.tsx        # Price trend SVG line chart (V5)
│   └── Dockerfile
├── data/
│   ├── raw/                          # CSV fuente (no commitear)
│   ├── processed/                    # Modelos pkl, commune_growth_index.csv, commune_ine_census.csv, commune_crime_index.csv
│   └── exports/                      # Mapas HTML, rankings CSV, backtesting_report.json, report_YYYY-MM-DD.html
├── models/                           # hedonic_model_v1.pkl, label_encoders_v1.pkl
├── tests/                            # 113+ test functions, ~296 con parametrize (pytest)
├── docker-compose.yml                # DB + API + Dashboard + Frontend + Nginx
├── Dockerfile                        # Python services (API + Dashboard)
├── nginx.conf                        # Reverse proxy: localhost → servicios
└── requirements.txt                  # Incluye prefect (V2 orquestación) y playwright (V2 scraping)
```

## Modelo de datos

- `transactions_raw` — Datos crudos del CSV, sin transformar.
- `transactions_clean` — Datos normalizados, deduplicados, con flags de calidad y `data_confidence`.
- `model_scores` — Scores calculados por versión de modelo, con SHAP top features en JSONB.
- `v_opportunities` — Vista que une scores + datos limpios, filtrando outliers.

## Variables de entorno

Copiar `.env.example` a `.env` en `re_cl/`. Variables requeridas:
`POSTGRES_PASSWORD`, `RAW_CSV_PATH`, `DATABASE_URL` (o las `POSTGRES_*` individuales).

## Estado (actualizado: 2026-05-01)

### Snapshot ejecutivo

- **842,227 candidatos** en `opportunity.candidates` (829k CBR + 12,891 DI nuevos + 5k scraped)
- **2,509,377 valuaciones** (845k comparables + 821k hedonic_xgb + 843k triangulated)
- **1,680,427 scores** (842k as_is + 6 use cases comerciales)
- **21,026 oportunidades alta score (≥0.7)** — ranking institucional disponible
- **8,043 competidores OSM** en 6 categorías (gas/farma/super/banco/clínica/restaurant)
- **Modelo XGBoost v1.0** R²=0.6712, n_train=520,574 (CBR 2008-2026)
- **DI scraping** 10/40 comunas RM (~55,140 rows), nightly automático 06:00 con 3 cuentas
- **Frontend UX Phase 5** — HomeShell único + 7 componentes nuevos + Geltner-grade simulator
- **Multi-agente backend** — 6 de 7 agentes implementados (A3 Risk pendiente fase 2)

### Próximos pasos prioritarios

1. **VPN/proxy para 3x throughput DI** (`scripts/PROXY_SETUP.md` con 3 estrategias listas)
2. **Completar 30 comunas DI restantes** (~10 días con VPN, ~25 sin)
3. **A3 Risk Agent** (PRC scraping + flags ambientales)
4. **Validar cap rates** con tasador externo (Tinsa / GPS Property)
5. **Extender al país** (Chile completo) — fase 2



| Fase | Estado |
|------|--------|
| 0. Entorno y base (schema, docker, requirements) | Completado |
| 1. Ingesta CSV → PostgreSQL | Completado |
| 1. Limpieza y normalización | Completado |
| 2. Feature engineering | Completado |
| 3. Modelo hedónico XGBoost + scoring + SHAP | Completado |
| 3. Scoring profiles (default/location/growth/liquidity/custom) | Completado (V2) |
| 4. Mapas Folium + commune ranking | Completado |
| 5. Dashboard Streamlit + profile sliders | Completado |
| 6. API FastAPI (properties, scores, profiles) + 296 tests | Completado |
| V2. Prefect orchestration (full/scoring/maps/scraping/daily) | Completado |
| V2. Scrapers (Portal Inmobiliario + Toctoc) | Completado (validación live pendiente) |
| V2. React + Deck.gl frontend | Completado |
| V3. Docker full stack + Nginx (todo en http://localhost) | Completado |
| V3. Sistema de alertas (console/JSON/email/desktop) | Completado |
| V3. Datos INE comunas (growth_index, 42 comunas RM) | Completado |
| V3. scraped_to_scored (listings → model_scores) | Completado |
| V3. Prefect deployments (daily 06:00 + weekly Dom 03:00) | Completado |
| V3. Levantar stack Docker en producción local (WSL2 + Docker Desktop) | Completado |
| V4.1 Thesis features (age, age², city_zone, year_bucket, log_surface) | Completado |
| V4.2 OSM enrichment (metro, colegios, hospitales, parques, malls) | Completado |
| V4.5 Backtesting walk-forward + OLS benchmark vs tesis MIT | Completado |
| V4.6 Frontend visual (radar, badges de score, stats bar, sparklines) | Completado |
| V5. Safety scoring profile (crime_index 25% weight) | Completado |
| V5. Simulador financiero (DCF, cap rate, yield) en Streamlit | Completado |
| V5. INE Censo 2017 + CEAD criminalidad static data (34 comunas RM) | Completado |
| V5. commune_context.py (enriquecimiento INE + CEAD) | Completado |
| V5. Analytics API (/analytics/price-trend, /score-distribution) | Completado |
| V5. Alerts API (/alerts/opportunities, /config, POST /test) | Completado |
| V5. /properties/{id}/comparables + /communes/enriched endpoints | Completado |
| V5. HTML report generator (generate_report.py) | Completado |
| V5. Comparador de propiedades (ComparatorPanel frontend) | Completado |
| V5. Watchlist panel + CSV export (frontend) | Completado |
| V5. Tendencias panel — SVG price trend chart (frontend) | Completado |
| V5. React frontend: 8 tabs (Map, Ranking, Comunas, Detail, Comparar, Watchlist, Tendencias, Finanzas) | Completado |
| V5. Setup orchestrator (setup_pipeline.py + setup_pipeline.sh) | Completado |
| V5. Streamlit quality_panel.py (dashboard calidad de datos) | Completado |
| V5. Prefect: tareas OSM + backtesting integradas | Completado |
| V6. GTFS RED bus stop proximity (dist_gtfs_bus_km, /properties/osm/bus-stops) | Completado |
| V6. OSM map layers con bus stops en DeckMap (toggle Zustand persistido) | Completado |
| V6. JWT auth (register/login/refresh/me) + saved searches API | Completado |
| V6. AuthModal + auth state en React + Sidebar guardar búsqueda | Completado |
| V6. FinanzasPanel React nativo (DCF/cap-rate/yield/escenarios) | Completado |
| V6. /predict endpoint stateless ML + /properties/search full-text | Completado |
| V6. PostGIS GiST + B-tree indexes (migration 007) | Completado |
| V6. 296 tests (4 skipped: statsmodels) — cobertura alertas + reports | Completado |
| **Ejecutar pipeline con CSV real** (1,048,557 raw → 562,854 clean → modelo R²=0.679 → 455,945 scored → 40 comunas → heatmap + report) | **Completado 2026-04-20** |
| Dashboard Deal Flow UX — dirección, Rol SII, vendedor CBR, Google Maps, drill-down comunas | Completado 2026-04-20 |
| Portal Inmobiliario scraper — selectores MeLi Polaris UI 2025 (poly-card, __PRELOADED_STATE__, JSON-LD) | Completado 2026-04-20 |
| Phase 9: Scraping paralelo PI+Toctoc (ThreadPoolExecutor) + DI guest mode + 5,003 listings | Completado 2026-04-22 |
| **Data Inmobiliaria CBR 2019-2026** — acumulación progresiva 40 comunas RM (quota ~15k/IP/día) | **En progreso 6/40 comunas** (Santiago 404, Providencia 434, Las Condes 142, Ñuñoa 15,637, La Florida 14,127, Maipú 11,505 — 42,249 rows total — 2026-04-30) |
| **DI multi-cuenta automatizado** — 3 cuentas configuradas (di_cookies 1/2/3), Task Scheduler 06:00 diario con run_di_bulk_multi.py + rotación automática de cuentas | **Completado 2026-04-30** |
| **Pipeline enriquecimiento DI** — 42,249 rows DI procesados: clean (824,333) → features (774,602) → scoring 4 perfiles (2,079,680 scores) → v_opportunities (1,737,208) | **Completado 2026-04-30** |
| **Fix opportunity_score.py** — write_scores ahora borra por (model_version, scoring_profile) en vez de solo model_version — 4 perfiles coexisten en model_scores | **Completado 2026-04-30** |
| **Fix model_scores schema** — columnas location_score, growth_score, safety_score, liquidity_score, crime_index agregadas via ALTER TABLE | **Completado 2026-04-30** |
| **Opportunity Engine v2 — COMPLETO** — schema `opportunity.*` (8 tablas), 829k candidatos, 1.6M valuaciones, 37k gas_station scored, 2,242 competidores OSM, 6 endpoints API, tab frontend "Oportunidades" | **Completado 2026-04-30** |
| **Opportunity Engine v2 — gas_station cross-validation** — Las Condes VALID (251/2508 en top decile, mean score 0.571) | **Completado 2026-04-30** |
| **Opportunity Engine v2 — pharmacy + supermarket scoring** — 242,941 + 15,480 candidatos scored | **Completado 2026-04-30** |
| **Opportunity Engine v2 — accessibility real** — 116,752 puntos de vías trunk/primary/secondary RM, BallTree distancia real, 538,960 scores actualizados | **Completado 2026-04-30** |
| **Opportunity Engine v2 — CSV export** — botón descarga en OpportunityPanel frontend | **Completado 2026-04-30** |
| **Opportunity Engine v2 — HTML reports** — 4 reportes: gas_station RM, gas_station Maipú, pharmacy, supermarket, as_is | **Completado 2026-04-30** |
| **Opportunity Engine v2 — 7 use cases completos** — gas_station (37k/6060 high) + pharmacy (242k/25060) + supermarket (15k/3264) + bank_branch (220k/5195) + clinic (100k/6887) + restaurant (220k/12467) + as_is (829k/11827) · 8,043 competidores OSM | **Completado 2026-04-30** |
| **Opportunity Engine v2 — Hedonic XGBoost valuations** — 774,602 predicciones XGBoost + 779,208 trianguladas (comparables + hedonic avg) | **Completado 2026-04-30** |
| **Opportunity Engine v2 — Executive summary report** — `executive_summary_2026-04-30.html` con top 5 por cada uno de los 5 use cases principales | **Completado 2026-04-30** |
| **UX Phase 3 — map-first interface** — Deck.gl ScatterplotLayer + TextLayer con precios visibles, NLP search ("casa Maipú score alto"), modo dual Inversionista/Operador, ficha narrativa (oraciones, no datasheet), filtros como floating chips, riesgos antes del upside | **Completado 2026-04-30** |
| **UX Phase 4 — Idealista-style** — Filter bar prominente con dropdowns explícitos (Comuna multi-select, Tipo chips, Precio slider con presets, Tamaño slider, Score 3-toggle, Eriazo toggle), mapa fullscreen + sidebar lista, ficha de detalle 1 pantalla con riesgos primero | **Completado 2026-05-01** |
| **DI nightly automático funcionando** — 4 comunas adicionales (Vitacura, Pirque, Talagante, Buin partial, Melipilla) = 12,891 rows. Total: 10/40 comunas | **Completado 2026-05-01** |
| **Reentrenamiento modelo con DI 2019-2026** — n_train: 443k → 520k, R²: 0.6787 → 0.6712 (slight drop esperado por mayor varianza post-pandemia), 820k hedonic predictions actualizadas | **Completado 2026-05-01** |
| **IP rotation support** — proxy/VPN URL per account vía `DI_PROXY_1/2/3` env vars, test_proxy.py script de validación, PROXY_SETUP.md con 3 estrategias (VPN free, residential proxy USD 35-140, VMs cloud USD 15/mes) | **Completado 2026-05-01** |
| **Pipeline post-retrain ejecutado** — 12,891 candidatos DI ingestados → 56 nuevos eriazo → 12,058 nuevas valuaciones comparables + trianguladas → re-score base completo (842,227 candidatos) con modelo nuevo. **21,026 oportunidades alta score** (vs 11,827 antes, +9k). Re-score commercial overlays + 8 reportes HTML regenerados | **Completado 2026-05-01** |
| **Modelo definitivo v1.0 (2026-05-01)** — XGBoost hedónico con 17 features · n_train: 520,574 · n_test: 12,265 · R²=0.6712 · RMSE=11.43 UF/m² (41.1% mediana) · MAE=7.79 UF/m². Entrenado sobre datos CBR 2008-2026 (incluye DI 2019-2026 reciente) | **Completado 2026-05-01** |
| **UX Phase 5 — Rediseño E2E** — Cutover de 9 tabs a HomeShell único (vista principal con header + mapa + rail + drawer). Onboarding 3-pantallas (objetivo + presupuesto + zonas), mapping objetivo→use_case oculto. PropertyDrawer con frase narrativa, 3 tarjetas (Si arriendas / Si vendes / Tendencia), riesgos primero. QuickReturnSimulator Geltner-grade DCF embebido (IRR + ROI + payback con sliders hold period / pie / tasa). WatchlistDrawer con persistencia localStorage. EmptyStateCoach con sugerencias inteligentes. Bundle 1068KB → 898KB (-16%) | **Completado 2026-05-01** |
| **Master Plan Geltner + Multi-agente** — `prompts/master_plan_geltner.md` integra metodología Geltner (Income/Sales/Cost), best practices industria (Colliers/CBRE/JLL/Tinsa), arquitectura multi-agente 6 agentes (Valuation/Demand/Risk/ScoreFusion/Narrative/Monitoring), criterios parametrizables RM Chile fase 1 → país fase 2 | **Completado 2026-05-01** |
| **A5 Narrative Agent (backend)** — endpoint `/opportunity/candidates/{id}/narrative?profile=&hold_years=` genera frase humana institucional + estructurados (monthly_rent_uf, yield_pct, projected_value_uf, appreciation_pct, disclaimer) reemplazando lógica frontend | **Completado 2026-05-01** |
| **A6 Monitoring Agent** — `src/opportunity/monitoring.py` recolecta métricas (score distribution, DI progress, valuation confidence, top comunas), guarda baseline + reportes timestamped en `data/monitoring/`, detecta drift score >5%, alertas severity high/medium/low | **Completado 2026-05-01** |
| **Frontend completo wired** — ComparatorOverlay (modal A vs B con highlight ganador), HeatmapToggle (panel ranking comunas por métrica seleccionable), SettingsDrawer con ExpertModeToggle (revela SHAP/scores/profile) | **Completado 2026-05-01** |
| Yapo scraper — bloqueado por reCAPTCHA v3 (necesita proxy rotation o cookie manual) | Bloqueado |
| MercadoLibre scraper — bloqueado por OAuth2/403 PolicyAgent | Bloqueado |

## Roadmap V5 (completado)

| Fase | Descripción | Estado |
|------|-------------|--------|
| V5.1 Pipeline completo | Setup orchestrator (setup_pipeline.py/.sh) + cold start one-command | Completado |
| V5.2 INE Censo 2017 | densidad_pob, nivel_educacion, hacinamiento (34 comunas RM, static data) | Completado |
| V5.3 CEAD Criminalidad | crime_index_comuna static data + commune_context.py + safety profile | Completado |
| V5.4 GTFS RED | Paraderos/rutas bus complementando metro en osm_features | Pendiente (V6) |
| V5.5 Capas OSM en mapa | Visualización de metro, parques, colegios sobre Deck.gl | Pendiente (V6) |
| V5.6 Comparador propiedades | ComparatorPanel side-by-side + /properties/{id}/comparables API | Completado |
| V5.7 Datos CBR recientes | Data Inmobiliaria u otra fuente cuando esté disponible | Futura |
| V5. Analytics API | /analytics/price-trend, /by-commune, /score-distribution | Completado |
| V5. Alerts API | /alerts/opportunities, /config, POST /test | Completado |
| V5. Simulador financiero | DCF, cap rate, yield + escenarios en Streamlit financial_panel.py | Completado |
| V5. HTML Report | generate_report.py → data/exports/report_YYYY-MM-DD.html | Completado |
| V5. Watchlist + Tendencias | WatchlistPanel + TrendPanel (SVG chart) en frontend React | Completado |
| V5. Frontend 8 tabs | Map, Ranking, Comunas, Detail, Comparar, Watchlist, Tendencias, Finanzas | Completado |
| V5. Quality dashboard | Streamlit quality_panel.py — métricas de calidad de datos | Completado |

## Modelo conceptual (resumen)

### Features del modelo XGBoost (V4 — post thesis integration)
| Dimensión | Variables |
|-----------|-----------|
| Precio | `gap_pct`, `price_percentile_25/50/75`, `price_vs_median` |
| Ubicación | `dist_km_centroid`, `cluster_id` (DBSCAN 500m), `city_zone` (4 zonas RM) |
| Temporal | `quarter_q1-q4`, `season_index`, `year` |
| Propiedad | `surface_m2`, `surface_building_m2`, `log_surface`, `surface_land_m2` |
| Antigüedad | `age`, `age_sq`, `construction_year_bucket` (7 buckets) |
| OSM | `dist_metro_km`, `dist_school_km`, `dist_hospital_km`, `dist_park_km`, `dist_mall_km`, `dist_bus_stop_km`, `amenities_500m`, `amenities_1km` |
| Calidad | `data_confidence` |
| Categórico | `project_type`, `county_name`, `city_zone`, `construction_year_bucket` |

### Thesis findings integrados (MIT 2017, J.J. Bulnes)
- Depreciación: 2.28%/año — capturada con `age` y `age_sq`
- Vintage effect: pre-1960 más valioso — capturado con `construction_year_bucket`
- Ley de rendimientos decrecientes: coeff superficie ≈ 0.928 — `log_surface`
- Estacionalidad Q4: +1.2% — validado por backtesting
- Segmentación territorial: 4 zonas (centro_norte, este, oeste, sur) — `city_zone`

### Scoring profiles
- **default**: subvaloración 70% + confianza 30%
- **location**: subvaloración 40% + proximidad centroid 40% + confianza 20%
- **growth**: subvaloración 35% + crecimiento comunal 35% + confianza 30%
- **liquidity**: subvaloración 50% + volumen transacciones 30% + confianza 20%
- **custom**: pesos definidos por usuario (auto-normalizados)

## Reglas de desarrollo

- **NEEDS APPROVAL** antes de: truncar tablas, modificar schema en producción, lanzar scrapers, consumir APIs pagadas.
- **SAFE**: lectura de datos, análisis, creación de archivos nuevos, tests locales, dry-run.
- Nunca hardcodear credenciales. Usar `.env` + `python-dotenv`.
- Toda feature debe tener: objetivo, riesgo, criterio de terminado y test mínimo.
- Actualizar este CLAUDE.md en cada hito importante del proyecto.
