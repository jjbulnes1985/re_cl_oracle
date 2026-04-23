# Phase 3: Feature Engineering - Research

**Researched:** 2026-04-13
**Domain:** Feature Engineering para modelo hedónico — Python, GeoPandas, scikit-learn, PostgreSQL
**Confidence:** HIGH (stack definido en CLAUDE.md; patrones verificados en documentación oficial)

---

## Summary

Esta fase calcula variables derivadas que alimentan el modelo hedónico XGBoost. El trabajo
se divide en tres dominios: (1) features de precio (gap_pct, percentiles por grupo), (2)
features espaciales (distancia al centroide comunal, clustering DBSCAN), y (3) features
temporales (quarter dummies, trimestre numérico). Todo se orquesta desde un único script
`build_features.py` que debe ser idempotente y loguear tiempo de ejecución.

El stack ya está definido en requirements.txt (pandas 2.2.2, geopandas 0.14.4, scikit-learn
1.4.2, sqlalchemy 2.0.30). No se necesitan nuevas dependencias para esta fase. El principal
riesgo técnico es el DBSCAN sobre 1M puntos — se resuelve usando la métrica haversine con
BallTree pre-computado o subsampling de centroides, no una matriz densa O(n²).

**Primary recommendation:** Crear una tabla separada `transaction_features` con FK a
`transactions_clean`. Calcular percentiles con SQL `percentile_cont` via SQLAlchemy (más
rápido que pandas groupby para grupos grandes), y hacer el DBSCAN sobre una muestra
estratificada de ~50-100k puntos con propagación de etiqueta por vecino más cercano.

---

## Project Constraints (from CLAUDE.md)

| Directiva | Detalle |
|-----------|---------|
| Base de datos | PostgreSQL 15 + PostGIS |
| ETL/Pipelines | Python 3.11, Pandas, SQLAlchemy |
| GIS | GeoPandas, Folium |
| ML | XGBoost, scikit-learn, SHAP |
| Credenciales | Nunca hardcodear. Usar `.env` + `python-dotenv` |
| NEEDS APPROVAL | Antes de truncar tablas, modificar schema en producción |
| Idempotencia | Todos los pipelines ETL deben ser idempotentes (RNF-03) |
| Datos sucios | Asumir duplicados, nulos, escalas inconsistentes, outliers (RNF-04) |
| Aprobación | No lanzar scrapers ni consumir APIs pagadas sin aprobación |

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RF-03 | Calcular brechas de precio (Real vs Calculated), percentiles por comuna/tipología, precios unitarios UF/m² y variables espaciales (distancia a centroide comunal, clustering) | Cubierto en todas las secciones de este documento |

### Success Criteria Mapeados

| Criterio | Enfoque Recomendado |
|----------|---------------------|
| SC-1: `gap_pct` calculado para todos los registros válidos | SQL o pandas: (real_value_uf - calculated_value_uf) / calculated_value_uf; excluir donde calculated_value_uf = 0 o NULL |
| SC-2: Percentiles p25/p50/p75 por (project_type, county_name, year) | SQL `percentile_cont` con WITHIN GROUP — evita cargar 1M filas a Python |
| SC-3: Distancia km al centroide comunal | GeoPandas: proyectar a UTM 19S → `.distance()` → dividir por 1000 |
| SC-4: DBSCAN con >= 5 clusters en RM | sklearn DBSCAN con haversine+BallTree sobre subsample; propagar etiqueta a todos |
| SC-5: Features guardadas via `build_features.py` | Script único con función `run()` por módulo |
| SC-6: `build_features.py` idempotente y con logging de tiempo | Patrón DELETE-WHERE + INSERT; `time.perf_counter()` + loguru |
</phase_requirements>

---

## Standard Stack

### Core (ya en requirements.txt)

| Library | Version | Purpose | Fuente |
|---------|---------|---------|--------|
| pandas | 2.2.2 | Cálculos tabulares, merge, groupby | `[VERIFIED: requirements.txt]` |
| geopandas | 0.14.4 | Spatial joins, centroid, distance, CRS | `[VERIFIED: requirements.txt]` |
| shapely | 2.0.4 | Geometrías punto/polígono | `[VERIFIED: requirements.txt]` |
| pyproj | 3.6.1 | Transformaciones CRS (WGS84 → UTM) | `[VERIFIED: requirements.txt]` |
| scikit-learn | 1.4.2 | DBSCAN, NearestNeighbors | `[VERIFIED: requirements.txt]` |
| sqlalchemy | 2.0.30 | Conexión a PostgreSQL, bulk insert | `[VERIFIED: requirements.txt]` |
| numpy | 1.26.4 | Arrays, operaciones vectorizadas | `[VERIFIED: requirements.txt]` |
| loguru | 0.7.2 | Logging estructurado (ya usado en ingestion) | `[VERIFIED: requirements.txt]` |

### No se necesitan dependencias adicionales para esta fase

Todo el stack necesario ya está declarado. No se requiere `pip install` de nuevos paquetes.

### Alternativas Consideradas y Descartadas

| En lugar de | Se podría usar | Por qué se descarta |
|-------------|---------------|---------------------|
| sklearn DBSCAN (subsample) | hdbscan (PyPI) | No está en requirements.txt; sklearn es suficiente para RM |
| SQL percentile_cont | pandas groupby quantile | SQL evita cargar 1M filas al proceso Python para esta operación |
| GeoPandas distance | scipy KDTree con haversine | GeoPandas es más legible y ya está en el stack |

---

## Research Question Answers

### Q1: Feature Storage Strategy — Tabla Separada vs ALTER TABLE

**Recomendación: Tabla separada `transaction_features`**

| Criterio | ALTER TABLE (columnas nuevas) | Tabla separada |
|----------|------------------------------|----------------|
| Reescritura de tabla | Sí (para columnas con default NULL) — PostgreSQL reescribe la tabla para columnas no-NULL con default expresión | No |
| Idempotencia | Difícil: ADD COLUMN IF NOT EXISTS + UPDATE crea lógica compleja | Simple: DELETE WHERE clean_id IN (...) + INSERT |
| Re-ejecución parcial | Peligroso: UPDATE parcial puede dejar estado inconsistente | Seguro: DELETE + INSERT es atómico |
| Schema coupling | Alta: cada nueva feature requiere DDL en producción | Baja: solo la tabla de features cambia |
| Query joins | Ninguno (columnas en misma tabla) | Un JOIN extra — aceptable para 1M filas con FK index |
| Compatibilidad con model_scores | model_scores ya usa clean_id como FK | transaction_features puede usar el mismo patrón |

`[ASSUMED]` — PostgreSQL 15 en ADD COLUMN con DEFAULT NULL no requiere reescritura (metadata-only). Pero si el default es una expresión, sí. Verificar antes del DDL.

**DDL recomendado:**
```sql
CREATE TABLE IF NOT EXISTS transaction_features (
    id              SERIAL PRIMARY KEY,
    clean_id        INTEGER REFERENCES transactions_clean(id) ON DELETE CASCADE,
    -- Price features
    gap_pct         NUMERIC(10, 6),   -- (real - calc) / calc
    gap_pct_log     NUMERIC(10, 6),   -- log1p(gap_pct + 1) para distribución
    gap_pct_win     NUMERIC(10, 6),   -- winsorized al percentil 1-99
    pct_rank_uf_m2  NUMERIC(6, 4),    -- percentil de UF/m² dentro del grupo
    p25_uf_m2       NUMERIC(10, 4),   -- p25 del grupo (project_type, county, year)
    p50_uf_m2       NUMERIC(10, 4),
    p75_uf_m2       NUMERIC(10, 4),
    -- Spatial features
    dist_to_centroid_km NUMERIC(10, 4),
    spatial_cluster     INTEGER,      -- -1 = ruido DBSCAN
    -- Temporal features
    quarter_sin     NUMERIC(8, 6),    -- sin(2π*quarter/4)
    quarter_cos     NUMERIC(8, 6),    -- cos(2π*quarter/4)
    is_q1           BOOLEAN,
    is_q2           BOOLEAN,
    is_q3           BOOLEAN,
    -- Metadata
    features_version VARCHAR(10) DEFAULT 'v1.0',
    computed_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(clean_id, features_version)
);
CREATE INDEX IF NOT EXISTS idx_tf_clean ON transaction_features(clean_id);
CREATE INDEX IF NOT EXISTS idx_tf_cluster ON transaction_features(spatial_cluster);
```

---

### Q2: Price Gap Calculation — gap_pct, Log Transform, Winsorizing

**Fórmula base:**
```python
gap_pct = (real_value_uf - calculated_value_uf) / calculated_value_uf
```

**Casos a manejar antes del cálculo:**
- `calculated_value_uf IS NULL` → excluir (gap_pct = NULL)
- `calculated_value_uf = 0` → excluir (división por cero)
- `is_outlier = TRUE` → calcular igual pero no usar en entrenamiento del modelo (data_confidence ya lo pondera)

**¿Log transform?**

`[CITED: Wiley Real Estate Economics 2023 — Lorenz, "Interpretable machine learning for real estate market analysis"]`

Los modelos hedónicos con XGBoost no requieren transformación logarítmica del target ni de features (los árboles son invariantes a transformaciones monotónicas). Sin embargo, `log1p(gap_pct + 1)` puede usarse si la distribución de gap_pct es muy asimétrica (skewness > 2) para mejorar visualizaciones e interpretación.

Para el modelo XGBoost: usar `gap_pct` sin transformar. Para visualizaciones y análisis exploratorio: guardar también `gap_pct_log`.

**¿Winsorizing?**

`[CITED: IMF Handbook on RPPIs, Chapter 5 — Hedonic Regression Methods]`

Estándar en modelos hedónicos. Winsorizar al 1-99 percentil elimina valores extremos que distorsionan la distribución sin eliminar registros.

```python
import numpy as np
from scipy.stats.mstats import winsorize  # o numpy clip manual

# Winsorizar al 1%-99% (más robusto que IQR para feature engineering)
p1 = df['gap_pct'].quantile(0.01)
p99 = df['gap_pct'].quantile(0.99)
df['gap_pct_win'] = df['gap_pct'].clip(lower=p1, upper=p99)
```

**Distribución esperada en datos chilenos:**
- `gap_pct` < 0 → propiedad vendida por debajo de su valor calculado (undervalued)
- `gap_pct` > 0 → propiedad vendida por encima (overvalued)
- Mediana cercana a 0 si Calculated_Value es una estimación fiscal (avalúo SII)
- Alta varianza esperada para `land` y `retail` (mercados más delgados)

`[ASSUMED]` — La distribución real de gap_pct en datos del CBR chileno 2013-2014 es desconocida hasta que se ejecute el cálculo. Inspeccionar la distribución antes de decidir el percentil de winsorizing.

---

### Q3: Percentile Computation at Scale — SQL vs Python

**Recomendación: SQL `percentile_cont` via SQLAlchemy**

**Razón principal:** Para calcular p25/p50/p75 agrupados por `(project_type, county_name, year)` en 1M filas, la opción más eficiente es un query SQL único que PostgreSQL ejecuta con un solo scan de la tabla, sin mover datos a Python.

**Número de grupos esperados:**
- 5 tipologías × ~52 comunas RM × 2 años = ~520 grupos
- Algunos grupos pueden tener < 30 transacciones (para retail/land en comunas pequeñas)

**SQL recomendado:**
```sql
-- Computar percentiles por grupo y hacer JOIN de vuelta
WITH percentiles AS (
    SELECT
        project_type,
        county_name,
        year,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY uf_m2_building) AS p25_uf_m2,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY uf_m2_building) AS p50_uf_m2,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY uf_m2_building) AS p75_uf_m2
    FROM transactions_clean
    WHERE is_outlier = FALSE
      AND uf_m2_building IS NOT NULL
    GROUP BY project_type, county_name, year
)
SELECT
    tc.id AS clean_id,
    p.p25_uf_m2,
    p.p50_uf_m2,
    p.p75_uf_m2,
    -- Percentil rank del registro dentro de su grupo
    percent_rank() OVER (
        PARTITION BY tc.project_type, tc.county_name, tc.year
        ORDER BY tc.uf_m2_building
    ) AS pct_rank_uf_m2
FROM transactions_clean tc
LEFT JOIN percentiles p
    ON tc.project_type = p.project_type
   AND tc.county_name = p.county_name
   AND tc.year = p.year
WHERE tc.is_outlier = FALSE;
```

`[CITED: Crunchy Data Blog — Percentage Calculations Using Postgres Window Functions]` — PostgreSQL computa window functions en un único scan de tabla, versus múltiples passes en pandas.

**Alternativa pandas (cuando SQL no aplica):**
```python
# Si se prefiere hacerlo en Python (más depurable pero más lento)
q_funcs = {
    'p25_uf_m2': lambda x: x.quantile(0.25),
    'p50_uf_m2': lambda x: x.quantile(0.50),
    'p75_uf_m2': lambda x: x.quantile(0.75),
}
group_cols = ['project_type', 'county_name', 'year']
percentiles = (
    df[~df['is_outlier']]
    .groupby(group_cols)['uf_m2_building']
    .agg(**q_funcs)
    .reset_index()
)
df = df.merge(percentiles, on=group_cols, how='left')
```

**Estimación de performance para 1M filas:**
- SQL `percentile_cont` agrupado: ~2-5 segundos en PostgreSQL con índice en `(project_type, county_name, year)` `[ASSUMED]`
- pandas groupby quantile + merge: ~8-15 segundos en RAM `[ASSUMED]`

---

### Q4: Spatial Features con GeoPandas

#### 4a. Centroide por comuna (de nube de puntos)

Como el dataset no incluye polígonos de comunas, el centroide se calcula como la mediana
geométrica de los puntos dentro de cada `county_name`:

```python
import geopandas as gpd
from shapely.geometry import Point

# Cargar transactions_clean con geom
gdf = gpd.read_postgis(
    "SELECT id, county_name, geom FROM transactions_clean WHERE has_valid_coords",
    engine,
    geom_col='geom',
    crs='EPSG:4326'
)

# Centroide por comuna = centroide del convex hull de todos los puntos comunales
# (más robusto que mediana de lat/lon para formas no convexas)
commune_centroids = (
    gdf.dissolve(by='county_name')
    .geometry
    .centroid
    .rename('centroid_geom')
    .reset_index()
)
```

`[CITED: geopandas.org/en/stable/docs/user_guide/projections.html]`

**EPSG para Chile — RM Santiago:**
- WGS84 input: `EPSG:4326` (ya en schema)
- UTM proyectado para distancias en metros: `EPSG:32719` (WGS 84 / UTM zone 19S)
  - Santiago RM cae en la zona 19S (longitud -70° a -66°)
  - Alternativa oficial chilena: `EPSG:5361` (SIRGAS-Chile 2002 / UTM zone 19S)

`[CITED: epsg.io/32719 — WGS 84 / UTM zone 19S]`
`[CITED: epsg.io/5361 — SIRGAS-Chile 2002 / UTM zone 19S]`

#### 4b. Distancia al centroide comunal en km

```python
# Proyectar a UTM 19S para distancia en metros
gdf_utm = gdf.to_crs('EPSG:32719')
centroids_utm = commune_centroids.set_index('county_name')['centroid_geom']
centroids_utm = gpd.GeoSeries(centroids_utm, crs='EPSG:4326').to_crs('EPSG:32719')

# Merge por county_name y calcular distancia
gdf_utm['centroid_geom'] = gdf_utm['county_name'].map(centroids_utm)
gdf_utm['dist_to_centroid_m'] = gdf_utm.geometry.distance(
    gpd.GeoSeries(gdf_utm['centroid_geom'], crs='EPSG:32719')
)
gdf_utm['dist_to_centroid_km'] = gdf_utm['dist_to_centroid_m'] / 1000.0
```

**Importante:** `gdf.geometry.distance()` en GeoPandas opera elemento a elemento cuando ambas
series están alineadas por índice. Para evitar el bucle `apply()`, alinear los índices antes.

`[CITED: geopandas.org — GeoSeries.distance, vectorized when indices align]`

#### 4c. DBSCAN Clustering Espacial

**Problema de escala:** DBSCAN naive sobre 1M puntos con haversine requiere O(n²) memoria en
el peor caso. Para RM Santiago, con alta densidad en comunas centrales, esto es impracticable.

**Estrategia recomendada: Subsample + Label Propagation**

```python
import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.neighbors import BallTree

# 1. Tomar una muestra estratificada por county_name (~50k-100k puntos)
sample = (
    df_with_coords
    .groupby('county_name', group_keys=False)
    .apply(lambda x: x.sample(min(len(x), 200), random_state=42))
)

# 2. Convertir a radianes para haversine
coords_sample = np.radians(sample[['latitude', 'longitude']].values)

# 3. DBSCAN con haversine + ball_tree
# eps en radianes: 0.5km / 6371km ≈ 0.0000785 radianes
eps_km = 0.5  # 500m radio
eps_rad = eps_km / 6371.0

db = DBSCAN(
    eps=eps_rad,
    min_samples=10,
    metric='haversine',
    algorithm='ball_tree',
    n_jobs=-1
).fit(coords_sample)

sample['spatial_cluster'] = db.labels_

# 4. Propagar etiqueta a TODOS los registros usando BallTree
coords_all = np.radians(df_with_coords[['latitude', 'longitude']].values)
tree = BallTree(coords_sample, metric='haversine')
_, indices = tree.query(coords_all, k=1)
df_with_coords['spatial_cluster'] = sample['spatial_cluster'].values[indices.flatten()]
```

**Ajuste de parámetros para RM:**
- `eps = 0.3-1.0 km` → esperado: clusters por barrio/sector en Santiago
- `min_samples = 10-30` → dado que hay 1M de puntos, usar valores más altos
- Verificar que `len(set(labels_) - {-1}) >= 5` para cumplir SC-4

`[CITED: scikit-learn.org/stable/modules/generated/sklearn.cluster.DBSCAN.html]`
`[CITED: scikit-learn.org — precomputed sparse distance strategy para large datasets]`

**Alternativa si subsample no da suficientes clusters:**
Usar `DBSCAN` directamente sobre la muestra más grande con `metric='precomputed'` y
`NearestNeighbors.radius_neighbors_graph` en modo sparse.

---

### Q5: Temporal Features

Para un dataset con solo 2 años (2013-2014) y datos por trimestre, las features temporales
más relevantes para el modelo hedónico son:

| Feature | Tipo | Justificación |
|---------|------|---------------|
| `quarter` (1-4) | Ordinal | Estacionalidad: mercado de verano (Q1 en Chile = enero-marzo) suele tener menor actividad |
| `quarter_sin`, `quarter_cos` | Cíclico | Codificación circular: preserva la continuidad Q4→Q1 para el modelo |
| `is_q1`, `is_q2`, `is_q3` | Dummy | XGBoost puede aprender interacciones no lineales con dummies explícitas |
| `year` (2013/2014) | Binario/Ordinal | Captura la tendencia inter-anual (2014 tuvo menor actividad por cambios tributarios en Chile) |
| `year_building_age` | Numérico | Edad del inmueble al momento de transacción = `year - year_building` |

`[CITED: Wiley Real Estate Economics 2024 — "House price seasonality, market activity, and the December discount"]`

**Features temporales descartadas para esta fase:**
- Lag features (requieren series continuas — 2013-2014 solo = 8 trimestres, insuficiente)
- Índice de actividad mensual (no hay granularidad mensual, solo trimestral)
- Fourier transforms (insuficientes períodos)

**Cálculo de codificación cíclica:**
```python
import numpy as np

df['quarter_sin'] = np.sin(2 * np.pi * df['quarter'] / 4)
df['quarter_cos'] = np.cos(2 * np.pi * df['quarter'] / 4)
```

---

### Q6: Feature Importance para Modelos Hedónicos en Chile

`[CITED: Springer — "Feature Importance Analysis and Model Performance Evaluation for Real Estate Price Prediction", 2024]`
`[CITED: Wiley — "Interpretable machine learning for real estate market analysis", Lorenz 2023]`

**Jerarquía de importancia esperada para XGBoost hedónico:**

1. **Espaciales** (más importantes): commune/barrio captura el mayor % de varianza de precio en bienes raíces
   - `county_name` encoded (label o target encoding por UF/m² mediano)
   - `dist_to_centroid_km` — distancia al centro comunal
   - `spatial_cluster` — sector/barrio dentro de la comuna

2. **Estructurales** (segundo): características físicas del inmueble
   - `uf_m2_building` — precio unitario por m² construido
   - `surface_building_m2` — tamaño del inmueble
   - `year_building_age` — antigüedad

3. **Precio vs Avalúo** (diagnóstico): la brecha es lo que el modelo debe predecir/explicar
   - `gap_pct` — no debe ser un input del modelo, es la variable a predecir o a diagnosticar
   - Los percentiles (`p25_uf_m2`, `pct_rank_uf_m2`) sí son features válidos del modelo

4. **Temporales** (menor importancia en este dataset corto):
   - `year`, `quarter_sin`, `quarter_cos`

**Nota específica para Chile 2013-2014:**
- Año 2014 tuvo cambios tributarios al mercado inmobiliario (reforma tributaria de Bachelet)
  que afectaron la relación precio-avalúo. El feature `year` puede capturar parte de esto.
  `[ASSUMED]` — Verificar con el analista del negocio si hay información adicional.

---

### Q7: Idempotency Pattern

**Recomendación: DELETE-WHERE + INSERT (scoped delete-write)**

El patrón de `TRUNCATE + reload` usado en `clean_transactions.py` es correcto para una
tabla que siempre se regenera completamente. Para `transaction_features`, el mismo patrón
aplica porque todas las features se recalculan en cada corrida.

```python
from sqlalchemy import text
import time
from loguru import logger

def build_features(engine, version: str = 'v1.0') -> None:
    t0 = time.perf_counter()

    # 1. Eliminar features de esta versión (idempotente)
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM transaction_features WHERE features_version = :v"),
            {'v': version}
        )
        logger.info(f"Limpieza previa: {result.rowcount:,} filas eliminadas")

    # 2. Calcular y cargar features
    df_features = _compute_all_features(engine)

    # 3. Insertar (con chunksize para 1M filas)
    df_features.to_sql(
        'transaction_features', engine,
        if_exists='append', index=False,
        method='multi', chunksize=5000
    )

    elapsed = time.perf_counter() - t0
    logger.info(f"build_features completado en {elapsed:.1f}s — {len(df_features):,} features escritas")
```

**¿Por qué no UPSERT aquí?**
- UPSERT (ON CONFLICT DO UPDATE) es más complejo de implementar y no aporta beneficio
  si `build_features.py` siempre recalcula todo desde cero.
- Si en el futuro se necesita actualizar features incrementalmente (por nueva versión del
  modelo), cambiar a `DELETE WHERE clean_id IN (ids_nuevos) + INSERT`.

`[CITED: datainproduction.substack.com — "Idempotency: The Property That Will Save Your Pipelines"]`

---

## Architecture Patterns

### Estructura de archivos recomendada

```
re_cl/src/features/
├── __init__.py
├── build_features.py          # Orquestador único (SC-5, SC-6)
├── price_features.py          # gap_pct, winsorizing, percentiles (SC-1, SC-2)
└── spatial_features.py        # distancia centroide, DBSCAN (SC-3, SC-4)
```

**Nota:** Los temporal features son simples enough para vivir en `price_features.py`
o en un módulo dedicado `temporal_features.py` si se prefiere separación de concerns.

### Pattern: Módulo con función `run(engine, version)`

Cada módulo expone una función `run()` que:
1. Lee datos necesarios de PostgreSQL
2. Calcula features
3. Retorna un DataFrame con columnas `[clean_id, feature1, feature2, ...]`
4. El orquestador hace el merge y escribe a `transaction_features`

```python
# build_features.py
from re_cl.src.features import price_features, spatial_features
import time
from loguru import logger

def main(version: str = 'v1.0') -> None:
    t0 = time.perf_counter()
    engine = create_engine(build_db_url())

    logger.info("Calculando price features...")
    df_price = price_features.run(engine)

    logger.info("Calculando spatial features...")
    df_spatial = spatial_features.run(engine)

    logger.info("Mergeando y escribiendo...")
    df = df_price.merge(df_spatial, on='clean_id', how='outer')
    df['features_version'] = version

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM transaction_features WHERE features_version = :v"),
                     {'v': version})
    df.to_sql('transaction_features', engine, if_exists='append', index=False,
              method='multi', chunksize=5000)

    elapsed = time.perf_counter() - t0
    logger.info(f"build_features DONE — {elapsed:.1f}s — {len(df):,} filas")

if __name__ == '__main__':
    main()
```

### Anti-Patrones a Evitar

- **Anti-patrón: `df.apply()` fila a fila para cálculo de distancias** — usar `.distance()` vectorizado de GeoPandas
- **Anti-patrón: DBSCAN sobre 1M filas con métrica densa** — usar subsample + label propagation
- **Anti-patrón: cargar 1M filas a Python solo para calcular percentiles** — hacer en SQL
- **Anti-patrón: hardcodear el EPSG o las credenciales** — usar `gdf.estimate_utm_crs()` o EPSG:32719 constante, y `.env`
- **Anti-patrón: `pd.read_sql("SELECT * FROM transactions_clean")` sin filtros** — filtrar por `has_valid_coords`, `has_valid_price`, `is_outlier = FALSE` según la feature

---

## Don't Hand-Roll

| Problema | No construir | Usar en cambio | Por qué |
|----------|-------------|----------------|---------|
| Distancia geográfica en km | Fórmula haversine manual | `gdf.to_crs('EPSG:32719').distance()` | GeoPandas maneja CRS, edge cases polares, precisión numérica |
| Clustering espacial | K-Means propio o grilla de celdas | `sklearn.cluster.DBSCAN` con haversine | DBSCAN detecta formas arbitrarias, maneja ruido (-1) |
| Percentiles por grupo | Loop por grupo + pd.Series.quantile | SQL `percentile_cont WITHIN GROUP` | PostgreSQL optimiza en un scan; el loop Python es 10-100x más lento |
| Winsorizing | `clip()` con percentiles hardcodeados | `df.quantile([0.01, 0.99])` + `.clip()` | Percentiles se calculan del dato, no asumidos |
| Encoding de variables cíclicas | One-hot de quarter (pierde continuidad) | Sin/cos encoding | Sin/cos preserva que Q4 y Q1 son adyacentes |

---

## Common Pitfalls

### Pitfall 1: División por cero en gap_pct
**What goes wrong:** `calculated_value_uf = 0` o NULL → NaN/Inf en el cálculo
**Why it happens:** Algunos registros del CBR tienen avalúo = 0 (propiedades no valorizadas, terrenos sin construcción)
**How to avoid:**
```python
df['gap_pct'] = np.where(
    (df['calculated_value_uf'].notna()) & (df['calculated_value_uf'] != 0),
    (df['real_value_uf'] - df['calculated_value_uf']) / df['calculated_value_uf'],
    np.nan
)
```
**Warning signs:** `gap_pct.isna().sum()` mucho mayor que `real_value_uf.isna().sum()`

### Pitfall 2: Distancias incorrectas por usar EPSG:4326 (grados) en lugar de UTM (metros)
**What goes wrong:** `gdf.distance()` sobre EPSG:4326 retorna grados, no metros. 1 grado ≈ 111km pero varía con la latitud.
**Why it happens:** El GeoDataFrame tiene CRS WGS84 del schema.sql (correcto para almacenamiento) pero no para medición.
**How to avoid:** Siempre llamar `.to_crs('EPSG:32719')` antes de `.distance()`. Verificar que el resultado esté en rango 0-50km para RM.
**Warning signs:** Distancias en el rango 0.001 - 0.5 (serían grados, no km)

### Pitfall 3: DBSCAN en 1M puntos consume toda la RAM
**What goes wrong:** `sklearn DBSCAN` con `metric='haversine'` y `algorithm='ball_tree'` sobre 1M puntos puede requerir >16GB RAM
**Why it happens:** Bulk-computes all neighborhoods antes de correr el algoritmo
**How to avoid:** Subsample a 50-100k puntos representativos. Propagar etiqueta con BallTree.query(k=1).
**Warning signs:** `MemoryError` o swap usage >80% durante la fase de fitting

### Pitfall 4: Grupos con muy pocas transacciones dan percentiles no representativos
**What goes wrong:** Un grupo `('retail', 'Tiltil', 2013)` puede tener 2-3 transacciones, dando percentiles sin significado estadístico
**Why it happens:** El mercado de retail es muy delgado en comunas periféricas de RM
**How to avoid:** Filtrar grupos con `COUNT < 10` y usar el percentil del nivel superior (tipología+año sin commune). Loguear cuántos grupos tienen menos de 10 obs.
**Warning signs:** p25 == p75 (distribución colapsada a un solo valor)

### Pitfall 5: `build_features.py` no es idempotente si falla a mitad
**What goes wrong:** Si el script falla después del DELETE y antes del INSERT, la tabla queda vacía
**Why it happens:** Dos operaciones DML sin transacción
**How to avoid:** Envolver DELETE + INSERT en una transacción SQLAlchemy:
```python
with engine.begin() as conn:
    conn.execute(text("DELETE FROM transaction_features WHERE features_version = :v"), {'v': version})
    # Si el INSERT falla, el DELETE se hace rollback automáticamente
    # Pero to_sql no usa la misma conexión — ver patrón alternativo abajo
```
O usar una tabla temporal de staging:
```python
# Escribir a staging, luego swap atómico
df.to_sql('transaction_features_staging', engine, if_exists='replace', ...)
with engine.begin() as conn:
    conn.execute(text("DELETE FROM transaction_features WHERE features_version = :v"), {'v': version})
    conn.execute(text("INSERT INTO transaction_features SELECT * FROM transaction_features_staging"))
    conn.execute(text("DROP TABLE IF EXISTS transaction_features_staging"))
```

### Pitfall 6: Centroide calculado de nube de puntos vs centroide geográfico real de la comuna
**What goes wrong:** El centroide de los puntos de transacción es el centroide del mercado, no el centroide administrativo de la comuna. Para comunas con alta concentración en una zona (ej. Las Condes en sector oriente), esto puede diferir 2-5km del centroide real.
**Why it happens:** No se tienen polígonos de comunas en el schema.
**How to avoid:** Aceptar esta aproximación para el MVP (la distancia al centroide del mercado es igualmente informativa). Documentar la limitación. En fases posteriores, incorporar polígonos del INE.
**Warning signs:** Distancias de 0 km para muchos registros (todos los puntos están exactamente en el centroide calculado de su comuna — eso sería una señal de coordenadas falsas).

---

## Code Examples

### Cálculo completo de gap_pct con protecciones
```python
# Source: [ASSUMED] — patrón estándar para división segura en pandas
import numpy as np
import pandas as pd

def compute_gap_pct(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula gap_pct = (real - calc) / calc con winsorizing.
    Registros con calc == 0 o NULL resultan en NaN (no se propaga error).
    """
    valid_mask = (
        df['calculated_value_uf'].notna() &
        (df['calculated_value_uf'] != 0) &
        df['real_value_uf'].notna()
    )

    df['gap_pct'] = np.where(
        valid_mask,
        (df['real_value_uf'] - df['calculated_value_uf']) / df['calculated_value_uf'],
        np.nan
    )

    # Winsorizing al 1%-99%
    p1 = df['gap_pct'].quantile(0.01)
    p99 = df['gap_pct'].quantile(0.99)
    df['gap_pct_win'] = df['gap_pct'].clip(lower=p1, upper=p99)

    # Log transform para análisis (no para el modelo XGBoost)
    # gap_pct puede ser negativo → usar log1p(gap_pct + 2) o symmetric log
    # Aquí se guarda gap_pct_win como principal feature del modelo
    df['gap_pct_log'] = np.log1p(df['gap_pct_win'].abs()) * np.sign(df['gap_pct_win'])

    return df
```

### Consulta SQL para percentiles agrupados
```python
# Source: PostgreSQL docs — percentile_cont WITHIN GROUP
PERCENTILE_QUERY = """
WITH group_stats AS (
    SELECT
        project_type,
        county_name,
        year,
        COUNT(*) AS n_obs,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY uf_m2_building) AS p25,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY uf_m2_building) AS p50,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY uf_m2_building) AS p75
    FROM transactions_clean
    WHERE is_outlier = FALSE
      AND uf_m2_building IS NOT NULL
      AND uf_m2_building > 0
    GROUP BY project_type, county_name, year
    HAVING COUNT(*) >= 10  -- mínimo estadístico
)
SELECT
    tc.id     AS clean_id,
    gs.p25    AS p25_uf_m2,
    gs.p50    AS p50_uf_m2,
    gs.p75    AS p75_uf_m2,
    gs.n_obs  AS group_n_obs
FROM transactions_clean tc
LEFT JOIN group_stats gs
    ON  tc.project_type = gs.project_type
    AND tc.county_name  = gs.county_name
    AND tc.year         = gs.year
WHERE tc.is_outlier = FALSE
"""
```

### DBSCAN espacial con haversine sobre subsample
```python
# Source: sklearn.cluster.DBSCAN docs + haversine pattern
import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.neighbors import BallTree

def run_spatial_clustering(
    df: pd.DataFrame,
    eps_km: float = 0.5,
    min_samples: int = 15,
    sample_size: int = 80_000,
    random_state: int = 42
) -> np.ndarray:
    """
    Retorna array de labels (int) de tamaño len(df).
    -1 indica ruido (sin cluster).
    """
    coords_all = df[['latitude', 'longitude']].dropna().values
    coords_rad_all = np.radians(coords_all)

    # Subsample estratificado para evitar OOM en 1M puntos
    if len(df) > sample_size:
        rng = np.random.default_rng(random_state)
        sample_idx = rng.choice(len(df), size=sample_size, replace=False)
        coords_sample = coords_rad_all[sample_idx]
    else:
        sample_idx = np.arange(len(df))
        coords_sample = coords_rad_all

    # DBSCAN con haversine en radianes
    eps_rad = eps_km / 6371.0
    db = DBSCAN(
        eps=eps_rad,
        min_samples=min_samples,
        metric='haversine',
        algorithm='ball_tree',
        n_jobs=-1
    ).fit(coords_sample)

    # Propagar etiquetas a todos los puntos via vecino más cercano
    tree = BallTree(coords_sample, metric='haversine')
    _, nearest_in_sample = tree.query(coords_rad_all, k=1)
    labels_all = db.labels_[nearest_in_sample.flatten()]

    n_clusters = len(set(labels_all) - {-1})
    noise_pct = (labels_all == -1).mean() * 100
    logger.info(f"DBSCAN: {n_clusters} clusters, {noise_pct:.1f}% ruido")
    assert n_clusters >= 5, f"DBSCAN generó solo {n_clusters} clusters — ajustar eps o min_samples"

    return labels_all
```

---

## Environment Availability

> Los paquetes listados en requirements.txt se asumen instalados en el entorno Docker.
> Verificar antes de ejecutar build_features.py:

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL 15 + PostGIS | Lectura de transactions_clean, escritura de transaction_features | Depende de `docker-compose up` | 15.x | — |
| Python 3.11 | Todos los scripts | Asumido en Docker | 3.11 | — |
| geopandas 0.14.4 | spatial_features.py | En requirements.txt | 0.14.4 | — |
| scikit-learn 1.4.2 | DBSCAN | En requirements.txt | 1.4.2 | — |
| scipy (via numpy/sklearn) | winsorize opcional | Incluido via scikit-learn | Transitivo | numpy.clip como fallback |

`[ASSUMED]` — El entorno Docker tiene acceso a PostgreSQL activo y transactions_clean
poblada (prerequisito de esta fase). Verificar con `docker-compose ps` antes de ejecutar.

**Step 2.6: No hay dependencias externas nuevas** — esta fase solo usa el stack ya declarado.

---

## Validation Architecture

> nyquist_validation: true en config.json — incluir esta sección.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.2.0 |
| Config file | `re_cl/pytest.ini` o `pyproject.toml` (verificar existencia — Wave 0 gap) |
| Quick run command | `pytest re_cl/tests/features/ -x -v` |
| Full suite command | `pytest re_cl/tests/ -v --cov=re_cl/src/features` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SC-1 | `gap_pct` = (real - calc) / calc correcto | unit | `pytest re_cl/tests/features/test_price_features.py::test_gap_pct -x` | ❌ Wave 0 |
| SC-1b | `gap_pct` es NaN cuando calculated_value_uf = 0 | unit | `pytest re_cl/tests/features/test_price_features.py::test_gap_pct_division_by_zero -x` | ❌ Wave 0 |
| SC-2 | p25 <= p50 <= p75 para todos los grupos | unit | `pytest re_cl/tests/features/test_price_features.py::test_percentile_ordering -x` | ❌ Wave 0 |
| SC-2b | Grupos con < 10 obs tienen percentiles NULL | unit | `pytest re_cl/tests/features/test_price_features.py::test_small_group_handling -x` | ❌ Wave 0 |
| SC-3 | Distancia > 0 para registros no en el centroide | unit | `pytest re_cl/tests/features/test_spatial_features.py::test_centroid_distance_positive -x` | ❌ Wave 0 |
| SC-3b | Distancia en km (no en grados) | unit | `pytest re_cl/tests/features/test_spatial_features.py::test_distance_in_km -x` | ❌ Wave 0 |
| SC-4 | DBSCAN genera >= 5 clusters en sample RM | unit | `pytest re_cl/tests/features/test_spatial_features.py::test_dbscan_min_clusters -x` | ❌ Wave 0 |
| SC-5/SC-6 | `build_features.py` es idempotente | integration | `pytest re_cl/tests/features/test_build_features.py::test_idempotent -x` | ❌ Wave 0 |
| SC-6b | `build_features.py` loguea tiempo de ejecución | unit | `pytest re_cl/tests/features/test_build_features.py::test_logs_execution_time -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest re_cl/tests/features/ -x -v`
- **Per wave merge:** `pytest re_cl/tests/ -v`
- **Phase gate:** Full suite green antes de `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `re_cl/tests/features/__init__.py` — módulo de tests
- [ ] `re_cl/tests/features/test_price_features.py` — cubre SC-1, SC-2
- [ ] `re_cl/tests/features/test_spatial_features.py` — cubre SC-3, SC-4
- [ ] `re_cl/tests/features/test_build_features.py` — cubre SC-5, SC-6
- [ ] `re_cl/tests/features/conftest.py` — fixtures: DataFrame mínimo con ~20 filas de datos sintéticos de RM
- [ ] Verificar existencia de `re_cl/pytest.ini` o configuración en `pyproject.toml`

**Nota sobre tests con DB:** Los tests de unit pueden usar DataFrames sintéticos en memoria.
Solo `test_idempotent` necesita una DB real — marcarlo como `@pytest.mark.integration` y
excluirlo del quick run con `-m "not integration"`.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | SQL percentile_cont en 1M filas toma 2-5s; pandas groupby toma 8-15s | Q3 | Diferencia no importa si ambos son aceptables; la recomendación SQL sigue siendo válida por arquitectura |
| A2 | DBSCAN sobre 50-100k subsample produce >= 5 clusters identificables en RM | Q4c | Si no: aumentar eps o reducir min_samples; el assertion en el código lo detectará |
| A3 | La distribución de gap_pct para datos CBR 2013-2014 tiene skewness > 2 | Q2 | Si no: winsorizing al 1-99 sigue siendo buena práctica; log transform puede omitirse |
| A4 | Reforma tributaria de Bachelet (2014) afectó precios en el dataset | Q5 | No afecta el modelo si el feature `year` se incluye — capturará cualquier efecto |
| A5 | El entorno Docker tiene `docker-compose up` corriendo con PostgreSQL accesible | Environment | Si no: build_features.py falla en el primer `create_engine`. Prerequisito de fase. |
| A6 | PostgreSQL 15 ADD COLUMN con DEFAULT NULL no reescribe la tabla | Q1 | Si se usa ADD COLUMN en lugar de tabla separada, verificar antes. La tabla separada evita este riesgo. |

---

## Open Questions

1. **¿Usar uf_m2_building o uf_m2_land para percentiles en tipología "land"?**
   - Lo que sabemos: `land` solo tiene `surface_land_m2` válido, no `surface_building_m2`
   - Lo que no está claro: Si `uf_m2_building` está NULL para la mayoría de registros `land`
   - Recomendación: Usar `uf_m2_land` para tipología `land`, `uf_m2_building` para el resto.
     Revisar el reporte de calidad de `clean_transactions.py` para confirmar.

2. **¿Cuántos registros tienen `has_valid_coords = TRUE`?**
   - Lo que sabemos: coordenadas lat/lon disponibles para "la mayoría"
   - Lo que no está claro: el % exacto con coordenadas válidas que pueden participar en features espaciales
   - Recomendación: Calcular features de precio para todos; features espaciales solo para los que tienen coords. La tabla `transaction_features` tendrá NULLs en columnas espaciales para los sin coords.

3. **¿Target encoding o label encoding para `county_name` en el modelo XGBoost?**
   - Esta pregunta aplica a la Fase 4 (modelo), no a esta fase. Registrar para ese momento.
   - Para esta fase, `county_name` se usa solo como key de agrupación, no como feature encodeada.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| DBSCAN naive sobre dataset completo | Subsample + label propagation via BallTree | Best practice desde ~2020 | Evita OOM en datasets > 100k puntos |
| Log-transform del precio para modelos de árbol | Sin transformación (árboles son invariantes) | Consenso ML 2018+ | Simplifica el pipeline |
| Percentiles en Python por loop de grupos | SQL `percentile_cont WITHIN GROUP` | Disponible desde PostgreSQL 9.4 | 10x+ más rápido para grupos grandes |
| One-hot encoding de quarter | Sin/cos encoding cíclico | Best practice desde 2019 en modelos temporales | Preserva continuidad Q4→Q1 |

---

## Sources

### Primary (HIGH confidence)
- `[VERIFIED: requirements.txt]` — versiones exactas del stack disponible
- `[VERIFIED: re_cl/db/schema.sql]` — columnas exactas de transactions_clean
- `[CITED: scikit-learn.org/stable/modules/generated/sklearn.cluster.DBSCAN.html]` — parámetros DBSCAN, métrica haversine, estrategia precomputed sparse
- `[CITED: geopandas.org/en/stable/docs/user_guide/projections.html]` — to_crs(), CRS handling
- `[CITED: epsg.io/32719]` — WGS 84 / UTM zone 19S para Chile continental
- `[CITED: epsg.io/5361]` — SIRGAS-Chile 2002 / UTM zone 19S (sistema oficial chileno)
- `[CITED: PostgreSQL docs — percentile_cont WITHIN GROUP]`

### Secondary (MEDIUM confidence)
- `[CITED: Crunchy Data Blog — Percentage Calculations Using Postgres Window Functions]` — performance SQL vs pandas
- `[CITED: Wiley Real Estate Economics 2024 — House price seasonality]` — features temporales
- `[CITED: Wiley Real Estate Economics 2023 — Lorenz, Interpretable ML for real estate]` — feature importance hierarchy
- `[CITED: Springer 2024 — Feature Importance Analysis for Real Estate Price Prediction]` — XGBoost feature importance
- `[CITED: IMF Handbook on RPPIs Chapter 5]` — winsorizing en modelos hedónicos
- `[CITED: datainproduction.substack.com — Idempotency patterns]` — delete-write vs upsert

### Tertiary (LOW confidence)
- Performance estimates (2-5s SQL, 8-15s pandas) son `[ASSUMED]` — no benchmarkeados en este entorno

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verificado en requirements.txt del proyecto
- Architecture (tabla separada, módulos): HIGH — basado en schema existente y patrones establecidos
- Price features (gap_pct, winsorizing): HIGH — estándar en literatura hedónica
- Percentile SQL approach: HIGH — documentado en PostgreSQL docs, patrón estándar
- Spatial (UTM EPSG, GeoPandas distance): HIGH — verificado en epsg.io y docs oficiales
- DBSCAN subsample strategy: MEDIUM — patrón documentado pero parámetros específicos requieren tuning
- Temporal features: MEDIUM — solo 2 años de datos limitan las opciones
- Performance estimates: LOW — no benchmarkeados en este hardware/dataset específico

**Research date:** 2026-04-13
**Valid until:** 2026-07-13 (stack estable; DBSCAN y GeoPandas APIs no cambian frecuentemente)
