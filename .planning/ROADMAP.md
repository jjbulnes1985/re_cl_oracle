# RE_CL Roadmap

> Plataforma multiagente para detectar inmuebles subvalorados en Chile.
> Stack: Python 3.11 · PostgreSQL + PostGIS · XGBoost · SHAP · Folium · Streamlit · FastAPI

## v1.0 MVP

- [x] **Phase 1: Entorno y Base de Datos** — Schema PostGIS, Docker, dependencias
- [x] **Phase 2: Ingesta y Limpieza del CSV** — ETL chunked + normalización
- [x] **Phase 3: Feature Engineering** — Variables derivadas para el modelo
- [x] **Phase 4: Modelo Hedónico y Scoring** — XGBoost + SHAP + Opportunity Score
- [x] **Phase 5: Mapas y Visualización** — Heatmap Folium + ranking comunal
- [x] **Phase 6: Dashboard Streamlit** — UI interactiva con filtros y fichas
- [x] **Phase 7: API y Tests** — FastAPI endpoints + pytest suite

## v2.0 Mercado en Vivo

- [ ] **Phase 8: Maximizar Scraping** — Cobertura máxima de portales + Data Inmobiliaria

---

## Phase 1: Entorno y Base de Datos

**Status:** Complete

**Goal:** Repositorio limpio con PostgreSQL+PostGIS corriendo vía Docker, schema de datos definido y dependencias Python instalables.

**Requirements:** RNF-01, RNF-02, RNF-03

**Success Criteria:**
1. `docker-compose up -d` levanta PostgreSQL+PostGIS sin errores
2. `psql` puede conectarse y muestra las tablas: transactions_raw, transactions_clean, model_scores, v_opportunities
3. `pip install -r requirements.txt` completa sin errores en Python 3.11
4. `.env.example` documenta todas las variables requeridas

---

## Phase 2: Ingesta y Limpieza del CSV

**Status:** Complete

**Goal:** Dataset del CBR (~1M registros, 151MB) cargado en PostgreSQL con coordenadas geoespaciales PostGIS, datos normalizados y reporte de calidad generado.

**Requirements:** RF-01, RF-02, RNF-01, RNF-04

**Success Criteria:**
1. `load_transactions.py` carga ~1M registros en < 10 minutos usando chunks de 50k filas
2. Columna `geom` (PostGIS Point WGS84) generada para todos los registros con coordenadas válidas
3. `clean_transactions.py --dry-run` reporta distribución de Real_Value y detecta escala (pesos vs UF)
4. `transactions_clean` tiene `data_confidence` calculado por registro
5. Outliers marcados (no eliminados) con `is_outlier` y `outlier_reason`
6. `clean_transactions.py` es idempotente (puede correrse múltiples veces)

---

## Phase 3: Feature Engineering

**Goal:** Variables derivadas calculadas y almacenadas para alimentar el modelo hedónico: brechas de precio, percentiles, distancias espaciales y variables temporales.

**Requirements:** RF-03

**Success Criteria:**
1. `price_features.py` calcula `gap_pct` = (real_value_uf - calculated_value_uf) / calculated_value_uf para todos los registros válidos
2. Percentiles p25/p50/p75 de UF/m² calculados por (project_type, county_name, year)
3. `spatial_features.py` calcula distancia en km al centroide de cada comuna
4. Clustering DBSCAN generado con al menos 5 clusters identificables en RM
5. Todas las features guardadas en tabla `transaction_features` o como columnas en `transactions_clean`
6. Script `build_features.py` es idempotente y loguea tiempo de ejecución

---

## Phase 4: Modelo Hedónico y Scoring

**Goal:** Modelo XGBoost entrenado que predice UF/m², score de oportunidad multicapa calculado para todos los registros, con SHAP values para explicabilidad.

**Requirements:** RF-04, RF-05, RF-10

**Success Criteria:**
1. `hedonic_model.py` entrena XGBoost con hold-out temporal (2014 Q4) como test set
2. RMSE del modelo < 30% del precio mediano por tipología en el test set
3. `undervaluation.py` calcula `gap_percentile` (0-100) por (tipología, año)
4. `opportunity_score.py` genera score final (0-1) combinando undervaluation + data_confidence
5. `shap_explainer.py` extrae top-3 SHAP features por registro y las guarda en JSONB
6. Tabla `model_scores` poblada con versión del modelo y timestamp
7. Vista `v_opportunities` retorna resultados correctamente filtrados

---

## Phase 5: Mapas y Visualización

**Goal:** Heatmap interactivo de oportunidades exportable como HTML, más ranking comunal con estadísticas de scoring.

**Requirements:** RF-06, RF-07

**Success Criteria:**
1. `heatmap.py` genera mapa Folium con al menos 5 comunas visibles y coloreadas por opportunity_score
2. El mapa incluye filtro por tipología (Apartments, Residential, Land) mediante capas
3. `commune_ranking.py` produce tabla con: comuna, n_transacciones, score_mediano, pct_subvaloradas
4. Exportación HTML del mapa funciona y puede abrirse en navegador sin servidor
5. `commune_stats` poblada con datos para al menos 10 comunas de RM
6. El heatmap usa hex bins o clustering para evitar falsa precisión en zonas de baja densidad

---

## Phase 6: Dashboard Streamlit

**Goal:** Interfaz de usuario funcional que integra mapa, ranking, ficha de activo y filtros, usable por un inversionista sin conocimientos técnicos.

**Requirements:** RF-08

**Success Criteria:**
1. `streamlit run src/dashboard/app.py` abre sin errores
2. Sidebar tiene filtros: tipología, comuna, score mínimo (slider), año
3. Mapa Folium se embebe y responde a los filtros del sidebar
4. Tabla de ranking muestra top-20 propiedades con score, gap_pct y top SHAP driver
5. Click en una propiedad muestra ficha: valor real, valor predicho, gap, 3 drivers SHAP, 5 comparables cercanos
6. Panel de calidad de datos muestra % nulos por columna y distribución de data_confidence

---

## Phase 7: API y Tests

**Goal:** API REST básica funcional con FastAPI y suite de tests con cobertura mínima en pipelines críticos.

**Requirements:** RF-09, RF-10, RNF-02, RNF-03

**Success Criteria:**
1. `uvicorn src.api.main:app` levanta sin errores
2. `GET /properties?county=Ñuñoa&type=apartments&min_score=0.5` retorna JSON con resultados paginados
3. `GET /scores/{id}` retorna score completo con SHAP features
4. `pytest tests/ -v` pasa con 0 failures
5. `test_clean.py` cubre: normalización UF, deduplicación, detección de outliers
6. `test_scoring.py` cubre: rango de scores (0-1), presencia de SHAP features, correlación gap/score > 0.6
7. `test_api.py` cubre endpoints con datos mock

### Phase 9: Phase 9: Scraping Paralelo Multi-fuente (sin credenciales)

**Goal:** Maximize scraped listings from Portal Inmobiliario, Toctoc, and Data Inmobiliaria without credentials/proxies by converting the three serial scrapers into an asyncio.gather()-based parallel system, with automatic post-scraping pipeline (normalize_county -> scraped_to_scored) and Prefect daily scheduling for Data Inmobiliaria. Target: >5,000 unique listings per full run.
**Requirements**: RF-11, PH9-D01..D09 (internal Phase 9 decisions), PH9-SC01 (>5k listings), PH9-SC02 (pipeline automation)
**Depends on:** Phase 8
**Plans:** 4/4 plans complete

Plans:
- [x] 09-01-PLAN.md -- Foundation: fix PI RM_COMMUNES duplicate (40 unique) + DB pool size=10 for scraper tasks
- [x] 09-02-PLAN.md -- Parallel wrappers: toctoc.run_parallel (4 types via asyncio.gather) + portal_inmobiliario.run_parallel (40 communes x 4 types in batches of 6)
- [x] 09-03-PLAN.md -- Prefect integration: 5 new tasks (pi/toctoc/di/normalize/score) + parallel_scrape_flow + scripts/run_parallel_scrape.py one-command CLI
- [x] 09-04-PLAN.md -- Validation: live run >5k listings + scripts/validate_parallel_scrape.py + Prefect daily cron for datainmobiliaria_daily_flow

---

## Phase 8: Maximizar Scraping

**Goal:** Obtener la mayor cantidad posible de listings únicos del mercado inmobiliario de RM desde todas las fuentes viables: portales web (Portal Inmobiliario, Toctoc, Yapo, GoplacesIt, MercadoLibre Inmuebles), Data Inmobiliaria (si existe acceso), y cualquier API o fuente alternativa. Incluye limpieza de county_name, deduplicación cross-fuente, y re-scoring automático post-scraping.

**Requirements:** RF-11

**Success Criteria:**
1. scraped_listings tiene > 10,000 listings únicos por (source, external_id)
2. county_name normalizado: > 95% de registros mapean a una de las 40 comunas RM conocidas
3. Al menos 3 fuentes activas (PI, Toctoc + 1 adicional)
4. Pipeline scraping → scored corre sin errores manuales
5. Listings disponibles en dashboard y API
