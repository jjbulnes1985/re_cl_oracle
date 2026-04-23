# Phase 8: Maximizar Datos — CBR 2017-2018 + Spatial ieut-inciti + Scraping

**Status:** Planned  
**Goal:** Máxima cobertura de datos de entrenamiento y mercado vivo. Tres frentes paralelos: (1) ingestar CBR 2017-2018 del ieut-inciti extendiéndolo de 2016 a 2018, (2) construir features espaciales desde shapefiles locales ieut-inciti (más precisos que OSM), (3) escalar scrapers a ≥10,000 listings únicos.

---

## Contexto

### Datos disponibles en `C:\Users\jjbul\Dropbox\Documentos\Master\Post_llegada\ieut - inciti\Data\`

#### CBR adicional
| Archivo | Filas | Años | Notas |
|---------|-------|------|-------|
| `CBR_SII/transacciones27062018_completo.csv` | 677,586 | 2008-2017 | Mismo schema que CSV principal; añade 2017 |
| `CBR_SII/Actualizacion_191118/191118_Actualizacion_2018.csv` | 80,690 | 2017-2018 | FECHA en serial Excel; schema diferente |
| `CBR_SII/AS_1807/*.csv` | ~100k | 2012-2018 | Snapshots intermedios por tipo |

#### Shapefiles espaciales (todos en CRS local Chile)
| Categoría | Archivos | Features a derivar |
|-----------|----------|-------------------|
| AREAS VERDES | `Areas_Verdes_AMS.shp` | `dist_green_area_km` |
| COMERCIO | `Ferias_Libres_AMS.shp`, `Malls_AMS.shp`, `Manzanas_Comerciales_AMS.shp` | `dist_feria_km`, `dist_mall_local_km`, `n_commercial_blocks_500m` |
| CONECTIVIDAD | `Estaciones_de_Metro_AMS.shp`, `Paraderos_de_Transantiago_AMS.shp`, `Autopistas_AMS.shp`, `Ciclovias_AMS.shp` | `dist_metro_local_km`, `dist_bus_local_km`, `dist_autopista_km`, `dist_ciclovia_km` |
| EQUIPAMIENTO | `Establecimientos_Educacionales_Publicos_AMS.shp`, `Jardines_infantiles_AMS.shp`, `Centros_de_Salud_Publica_AMS.shp`, `Equipamiento_Cultural_AMS.shp`, `Unidades_Policiales_AMS.shp` | `dist_school_local_km`, `dist_jardines_km`, `dist_health_local_km`, `dist_cultural_km`, `dist_policia_km` |
| NIMBYS | `Aeropuertos_AMS.shp`, `Manzanas_Industriales_AMS.shp`, `Vertederos_AMS.shp` | `dist_airport_km`, `dist_industrial_km`, `dist_vertedero_km` (negative amenity) |

---

## Tasks

### TRACK A — CBR 2017-2018 Ingestion

**A1. Schema extension (migration 012)**
- Archivo: `re_cl/db/migrations/012_cbr_2018.sql`
- Añadir columna `data_source VARCHAR(50) DEFAULT 'cbr_v1'` a `transactions_raw` (IF NOT EXISTS)
- Crear tabla staging: `transactions_raw_2018 (LIKE transactions_raw INCLUDING ALL)` para ingestión segura

**A2. Loader para `transacciones27062018_completo.csv`**
- Archivo: `re_cl/src/ingestion/load_cbr_2018.py`
- Columnas: misma estructura que CSV principal pero delimitador `;` en vez de `,`
- Mapear: `x` → `longitude`, `y` → `latitude`, `uf_m2_u` → `UF_m2_u`, `real_value` → `Real_Value`
- Coordenadas ya en WGS84 (lon/lat decimal directos vs el CSV principal que tenía algunas en PSAD56)
- Filtro: solo filas con `year >= 2015` para evitar overlap con dataset existente (que ya tiene 2008-2016)
- Target: `transactions_raw` con `data_source='cbr_2018'`
- Dedup: skip si `(role, inscription_date, real_value)` ya existe

**A3. Loader para `191118_Actualizacion_2018.csv`**
- Archivo: añadir función `load_actualizacion_2018()` en `load_cbr_2018.py`
- FECHA está en serial Excel (días desde 1900-01-01) → convertir con `pd.to_datetime(origin='1899-12-30', unit='D')`
- Columnas disponibles: `LON`, `LAT` (en formato `-70562014` → dividir por 1e6 → `-70.562014`)
- Schema diferente → mapear a `transactions_raw` con defaults para columnas faltantes
- Filtro: `year >= 2017` (datos nuevos)
- Target: `transactions_raw` con `data_source='cbr_actualizacion_2018'`

**A4. Re-run cleaning pipeline**
- Ejecutar `clean_transactions.py` sobre los nuevos registros
- El script ya es idempotente — saltará duplicados
- Target: `transactions_clean` debería crecer de ~562k a ~600-620k registros

**A5. Re-build features para nuevos registros**
- Ejecutar `build_features.py` — idempotente, solo procesa registros sin features
- Requiere spatial join con shapefiles para nuevas features (Task B)

**A6. Retrain hedonic model con datos 2008-2018**
- Hold-out temporal: `year >= 2017` como test set (en vez de 2014 Q4)
- Más años → mejor generalización temporal
- Esperar features ieut-inciti (Track B) antes de reentrenar para máximo beneficio

---

### TRACK B — ieut-inciti Spatial Features

**B1. Migration 013 — nuevas columnas spatial**
- Archivo: `re_cl/db/migrations/013_ieut_spatial.sql`
```sql
ALTER TABLE transaction_features
  ADD COLUMN IF NOT EXISTS dist_green_area_km FLOAT,
  ADD COLUMN IF NOT EXISTS dist_feria_km FLOAT,
  ADD COLUMN IF NOT EXISTS dist_mall_local_km FLOAT,
  ADD COLUMN IF NOT EXISTS n_commercial_blocks_500m INT,
  ADD COLUMN IF NOT EXISTS dist_metro_local_km FLOAT,
  ADD COLUMN IF NOT EXISTS dist_bus_local_km FLOAT,
  ADD COLUMN IF NOT EXISTS dist_autopista_km FLOAT,
  ADD COLUMN IF NOT EXISTS dist_ciclovia_km FLOAT,
  ADD COLUMN IF NOT EXISTS dist_school_local_km FLOAT,
  ADD COLUMN IF NOT EXISTS dist_jardines_km FLOAT,
  ADD COLUMN IF NOT EXISTS dist_health_local_km FLOAT,
  ADD COLUMN IF NOT EXISTS dist_cultural_km FLOAT,
  ADD COLUMN IF NOT EXISTS dist_policia_km FLOAT,
  ADD COLUMN IF NOT EXISTS dist_airport_km FLOAT,
  ADD COLUMN IF NOT EXISTS dist_industrial_km FLOAT,
  ADD COLUMN IF NOT EXISTS dist_vertedero_km FLOAT;
```

**B2. `src/features/ieut_spatial_features.py`** — nuevo módulo
```
Clase IeutSpatialFeatures:
  - Carga shapefiles con geopandas desde DATA_DIR configurable (env var IEUT_DATA_DIR)
  - Convierte CRS a EPSG:4326 (todos los shapefiles están en CRS local Chile → usar .to_crs(4326))
  - Para cada transacción: calcula distancia mínima a cada capa con BallTree (haversine)
  - n_commercial_blocks_500m: count de Manzanas_Comerciales dentro de 500m
  - Batch processing: 10k filas a la vez, guarda progreso en columna `ieut_computed_at`
  
Inputs:
  AREAS_VERDES_PATH = IEUT_DATA_DIR / "AREAS VERDES/Areas_Verdes_AMS.shp"
  COMERCIO_PATHS = { feria: ..., mall: ..., manzana_comercial: ... }
  CONECTIVIDAD_PATHS = { metro: ..., bus: ..., autopista: ..., ciclovia: ... }
  EQUIPAMIENTO_PATHS = { school: ..., jardines: ..., health: ..., cultural: ..., policia: ... }
  NIMBY_PATHS = { airport: ..., industrial: ..., vertedero: ... }

Output: UPDATE transaction_features SET dist_* = ... WHERE id = ...
```

**B3. Añadir ieut_spatial_features a `build_features.py`**
- Paso 6 (después de GTFS en paso 5)
- Flag `--skip-ieut` para correr sin shapefiles
- Log tiempo de ejecución por capa

**B4. Añadir nuevas features al modelo XGBoost**
- Editar `src/models/hedonic_model.py`
- Añadir a `NUM_FEATURES`: dist_green_area_km, dist_feria_km, dist_mall_local_km, n_commercial_blocks_500m, dist_metro_local_km, dist_bus_local_km, dist_autopista_km, dist_ciclovia_km, dist_school_local_km, dist_jardines_km, dist_health_local_km, dist_cultural_km, dist_policia_km, dist_airport_km, dist_industrial_km, dist_vertedero_km
- NaN tolerance: XGBoost las manejará nativamente

**B5. Añadir defaults ieut en `scraped_to_scored.py`**
- `_add_model_defaults()` ya existe — extender con `np.nan` para todas las nuevas features
- Las scraped listings no tienen shapefiles → NaN → XGBoost usa split gain sin ellas

---

### TRACK C — Scraping Maximization

**C1. Yapo scraper**
- Archivo: `re_cl/src/scraping/yapo.py`
- URL pattern: `https://www.yapo.cl/region_metropolitana/inmuebles?ca=15&l=0&cpa=1&pag=N`
- Parser: JSON en `window.__NEXT_DATA__` o listado HTML
- Expected: 3,000-5,000 listings

**C2. MercadoLibre Inmuebles scraper**  
- Archivo: `re_cl/src/scraping/mercadolibre.py`
- API REST disponible: `https://api.mercadolibre.com/sites/MLC/search?category=MLC1459&state=TUxDUFJNQWw&offset=N`
- No requiere Playwright — requests puro + JSON parsing
- Rate limit: 1 req/s, máx 1000 resultados por query → sub-queries por tipo
- Expected: 5,000-8,000 listings

**C3. PI --by-commune automatizado**
- Ya existe. Añadir Prefect task para run diario automático
- 40 communes × 4 types × page 1 = 160 requests = ~7,680 listings max
- Scheduled: diario 07:00 (antes de scoring diario 08:00)

**C4. county_name normalization pipeline**
- Archivo: `re_cl/src/ingestion/normalize_county.py`
- Problema actual: scraped_listings tiene strings como "1 - 300", "Las Majadas. Pirque"
- Solución: fuzzy matching contra las 40 comunas RM + dirección parsing
- Usar `rapidfuzz` (ya en requirements) para score > 85% → asignar comuna
- Fallback: NULL → excluido del scoring
- Correr post-scraping, pre-scoring

**C5. Scraped listing enrichment con shapefiles**
- `scraped_to_scored.py`: si listing tiene lat/lon → calcular ieut features en tiempo real (no guardar en DB, solo para scoring)
- Usar BallTree precargado (singleton) para eficiencia

**C6. Pipeline integrado en Prefect**
- Editar `src/pipelines/flows.py`
- Flow `daily_market`: PI commune scrape → Yapo → ML scrape → normalize_county → scraped_to_scored
- Scheduling: daily 06:00

---

## Criterios de éxito

| # | Criterio | Verificación |
|---|----------|-------------|
| 1 | `transactions_raw` crece a ≥700k con `data_source` taggeado | `SELECT data_source, count(*) FROM transactions_raw GROUP BY 1` |
| 2 | `transactions_clean` crece a ≥600k (nuevos 2017-2018 superan UF floors) | `SELECT count(*) FROM transactions_clean` |
| 3 | Todas las 16 features ieut_spatial en `transaction_features` para ≥95% de registros | `SELECT count(*) WHERE dist_green_area_km IS NOT NULL` |
| 4 | Hedonic model retrained con nuevo dataset: R² ≥ 0.70 (actual 0.679) | `models/hedonic_model_v1.1.pkl` metadata |
| 5 | `scraped_listings` ≥ 10,000 listings únicos (source, external_id) | `SELECT source, count(DISTINCT external_id) FROM scraped_listings GROUP BY 1` |
| 6 | county_name normalizado: ≥95% mapean a comunas RM conocidas | `SELECT count(*) WHERE county_name IN (SELECT DISTINCT county_name FROM commune_stats)` |
| 7 | Al menos 3 fuentes activas en scraped_listings | `SELECT DISTINCT source FROM scraped_listings` |
| 8 | `scraped_to_scored.py` corre sin errores | Exit code 0 |

---

## Orden de ejecución recomendado

```bash
# A1-A3: Ingestar datos CBR 2017-2018
py re_cl/db/migrations/012_cbr_2018.sql  # via psql
py re_cl/src/ingestion/load_cbr_2018.py  # ~677k + 80k rows

# B1-B2: Features espaciales
psql -f re_cl/db/migrations/013_ieut_spatial.sql
py re_cl/src/features/ieut_spatial_features.py  # ~30min en CPU

# A4-A5: Limpiar y buildear features para nuevos registros  
py re_cl/src/ingestion/clean_transactions.py
py re_cl/src/features/build_features.py

# A6: Reentrenar modelo con más datos + features
py re_cl/src/models/hedonic_model.py  # → hedonic_model_v1.1.pkl

# C1-C4: Scrapers adicionales
py re_cl/src/scraping/yapo.py --max-pages 100
py re_cl/src/scraping/mercadolibre.py  # API REST, no playwright
py re_cl/src/ingestion/normalize_county.py  # fix county names

# Scoring final
py re_cl/src/scoring/scraped_to_scored.py
```

---

## Archivos a crear

| Archivo | Descripción |
|---------|-------------|
| `re_cl/db/migrations/012_cbr_2018.sql` | data_source column |
| `re_cl/db/migrations/013_ieut_spatial.sql` | 16 nuevas columnas spatial |
| `re_cl/src/ingestion/load_cbr_2018.py` | Loader 2017-2018 CBR |
| `re_cl/src/features/ieut_spatial_features.py` | Shapefile → BallTree → distances |
| `re_cl/src/scraping/yapo.py` | Yapo scraper (Playwright) |
| `re_cl/src/scraping/mercadolibre.py` | ML API scraper (requests) |
| `re_cl/src/ingestion/normalize_county.py` | Fuzzy county name normalization |

## Archivos a modificar

| Archivo | Cambio |
|---------|--------|
| `re_cl/src/features/build_features.py` | Paso 6: ieut_spatial_features |
| `re_cl/src/models/hedonic_model.py` | NUM_FEATURES + 16 nuevas |
| `re_cl/src/scoring/scraped_to_scored.py` | _add_model_defaults() + 16 NaN defaults |
| `re_cl/src/pipelines/flows.py` | daily_market flow |
| `re_cl/CLAUDE.md` | Actualizar status + comandos |

---

## Variables de entorno necesarias

```bash
IEUT_DATA_DIR=C:/Users/jjbul/Dropbox/Documentos/Master/Post_llegada/ieut - inciti/Data
CBR_2018_PATH=C:/Users/jjbul/Dropbox/Documentos/Master/Post_llegada/ieut - inciti/Data/CBR_SII/transacciones27062018_completo.csv
CBR_2018_UPDATE_PATH=C:/Users/jjbul/Dropbox/Documentos/Master/Post_llegada/ieut - inciti/Data/CBR_SII/Actualizacion_191118/191118_Actualizacion_2018.csv
```
