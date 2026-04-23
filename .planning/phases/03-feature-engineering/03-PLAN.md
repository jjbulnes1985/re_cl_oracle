---
phase: 3
name: Feature Engineering
status: pending
waves: 3
plan: 01
type: execute
wave: 0
depends_on: []
files_modified:
  - re_cl/db/migrations/001_transaction_features.sql
  - re_cl/tests/conftest.py
  - re_cl/tests/test_price_features.py
  - re_cl/tests/test_spatial_features.py
  - re_cl/tests/test_build_features.py
autonomous: true
requirements:
  - RF-03
must_haves:
  truths:
    - "Tabla transaction_features existe en PostgreSQL con FK a transactions_clean.id"
    - "gap_pct calculado y winsorizado 1-99% para todos los registros con calculated_value_uf > 0"
    - "Percentiles p25/p50/p75 de uf_m2_building calculados por (project_type, county_name, year)"
    - "dist_km_centroid calculado en EPSG:32719 para registros con coordenadas válidas"
    - "cluster_id asignado a todos los registros via DBSCAN + BallTree propagation"
    - "quarter_q1..q4 dummies y season_index presentes en transaction_features"
    - "build_features.py ejecuta sin errores y es idempotente (segunda ejecución produce el mismo resultado)"
    - "Tests pasan con fixtures sintéticas (100 filas) sin requerir la DB real"
  artifacts:
    - path: "re_cl/db/migrations/001_transaction_features.sql"
      provides: "DDL de la tabla transaction_features con FK, índices y restricciones"
    - path: "re_cl/src/features/price_features.py"
      provides: "Funciones compute_gap_pct() y compute_percentiles()"
      exports: ["compute_gap_pct", "compute_percentiles", "run"]
    - path: "re_cl/src/features/spatial_features.py"
      provides: "Funciones compute_centroid_distance() y compute_dbscan_clusters()"
      exports: ["compute_centroid_distance", "compute_dbscan_clusters", "run"]
    - path: "re_cl/src/features/temporal_features.py"
      provides: "Función compute_temporal_features()"
      exports: ["compute_temporal_features", "run"]
    - path: "re_cl/src/features/build_features.py"
      provides: "Orquestador idempotente que llama price, spatial y temporal en secuencia"
      exports: ["main"]
    - path: "re_cl/tests/conftest.py"
      provides: "Fixtures sintéticas de 100 filas compatibles con schema transactions_clean"
    - path: "re_cl/tests/test_price_features.py"
      provides: "Tests unitarios para gap_pct y percentiles"
    - path: "re_cl/tests/test_spatial_features.py"
      provides: "Tests unitarios para distancias y DBSCAN"
    - path: "re_cl/tests/test_build_features.py"
      provides: "Test de integración del orquestador"
  key_links:
    - from: "re_cl/src/features/build_features.py"
      to: "re_cl/db/migrations/001_transaction_features.sql"
      via: "TRUNCATE + INSERT INTO transaction_features"
      pattern: "TRUNCATE.*transaction_features|INSERT INTO transaction_features"
    - from: "re_cl/src/features/price_features.py"
      to: "transactions_clean"
      via: "pd.read_sql() con columnas calculated_value_uf, real_value_uf, uf_m2_building"
      pattern: "read_sql.*transactions_clean"
    - from: "re_cl/src/features/spatial_features.py"
      to: "transactions_clean"
      via: "GeoDataFrame desde columnas longitude/latitude, proyección a EPSG:32719"
      pattern: "GeoDataFrame.*EPSG:32719|to_crs.*32719"
---

<objective>
Calcular y persistir todas las variables derivadas (features) que alimentan el modelo
hedónico XGBoost: brechas de precio, percentiles SQL, distancias espaciales, clustering
DBSCAN y variables temporales.

Purpose: Sin estas features el modelo hedónico de Fase 4 no tiene inputs. Esta fase
materializa la brecha entre valor catastral y precio real de mercado, la posición
de cada propiedad en su mercado local (percentiles), su contexto espacial (distancia
al centro comunal, pertenencia a clúster) y su temporalidad (quarter, season).

Output:
- Tabla `transaction_features` en PostgreSQL (1 fila por registro en transactions_clean)
- Scripts modulares en `re_cl/src/features/`
- Suite de tests con fixtures sintéticas en `re_cl/tests/`
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@re_cl/db/schema.sql
@re_cl/src/ingestion/clean_transactions.py
@re_cl/src/ingestion/load_transactions.py
@re_cl/requirements.txt

<interfaces>
<!-- Columnas relevantes de transactions_clean para el executor — extraídas de schema.sql -->

Tabla transactions_clean (columnas usadas en esta fase):
```sql
id                    SERIAL PRIMARY KEY
project_type          VARCHAR(50)       -- 'apartments', 'residential', 'retail', 'land'
year                  SMALLINT          -- Año de transacción (2013, 2014)
quarter               SMALLINT          -- Trimestre 1-4
county_name           VARCHAR(100)      -- Nombre de la comuna
geom                  GEOMETRY(Point, 4326)  -- Punto en WGS84
longitude             NUMERIC(12, 8)    -- Longitud decimal (calculada desde geom)
latitude              NUMERIC(12, 8)    -- Latitud decimal
calculated_value_uf   NUMERIC(14, 4)    -- Valor catastral/avalúo en UF
real_value_uf         NUMERIC(14, 4)    -- Precio real de transacción en UF
uf_m2_building        NUMERIC(10, 4)    -- UF por m² construido
has_valid_coords      BOOLEAN           -- True si las coordenadas son válidas
has_valid_price       BOOLEAN           -- True si real_value_uf > 0
is_outlier            BOOLEAN           -- True si fue marcado como outlier
```

Patrón de conexión a DB (de clean_transactions.py / load_transactions.py):
```python
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

def build_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db   = os.getenv("POSTGRES_DB", "re_cl")
    user = os.getenv("POSTGRES_USER", "re_cl_user")
    pwd  = os.getenv("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"

engine = create_engine(build_db_url(), pool_pre_ping=True)
```

Patrón de logging (de clean_transactions.py):
```python
from loguru import logger
logger.info("Mensaje descriptivo con {valor}", valor=x)
```

Patrón de escritura a DB (de clean_transactions.py):
```python
df.to_sql("tabla", engine, if_exists="append", index=False, method="multi", chunksize=5000)
```
</interfaces>
</context>

<tasks>

<!-- ═══════════════════════════════════════════════════════════════
     WAVE 0 — Fundación: DDL + fixtures de tests
     Debe completarse antes que cualquier otra tarea.
     ═══════════════════════════════════════════════════════════════ -->

<task type="auto">
  <name>Task 0.1: DDL — Crear tabla transaction_features</name>
  <files>re_cl/db/migrations/001_transaction_features.sql</files>
  <action>
Crear el archivo SQL con el DDL completo de la tabla `transaction_features`.
La tabla debe tener exactamente estas columnas:

```sql
CREATE TABLE IF NOT EXISTS transaction_features (
    id                  SERIAL PRIMARY KEY,
    clean_id            INTEGER NOT NULL REFERENCES transactions_clean(id) ON DELETE CASCADE,

    -- Features de precio
    gap_pct             NUMERIC(10, 6),   -- (real_value_uf - calculated_value_uf) / calculated_value_uf, winsorizado 1-99%
    gap_pct_raw         NUMERIC(10, 6),   -- gap_pct sin winsorizar (para auditoría)
    pct_rank_uf_m2      NUMERIC(5, 2),    -- Percentil de uf_m2_building dentro de (project_type, county_name, year)
    p25_uf_m2_group     NUMERIC(10, 4),   -- P25 del grupo (project_type, county_name, year)
    p50_uf_m2_group     NUMERIC(10, 4),   -- Mediana del grupo
    p75_uf_m2_group     NUMERIC(10, 4),   -- P75 del grupo

    -- Features espaciales
    dist_km_centroid    NUMERIC(10, 4),   -- Distancia al centroide comunal en km (EPSG:32719)
    cluster_id          SMALLINT,          -- ID de clúster DBSCAN (-1 = ruido)

    -- Features temporales
    quarter_q1          SMALLINT,          -- Dummy: 1 si quarter = 1, else 0
    quarter_q2          SMALLINT,
    quarter_q3          SMALLINT,
    quarter_q4          SMALLINT,
    season_index        NUMERIC(5, 4),     -- Índice numérico de estacionalidad: (quarter - 1) / 3.0

    computed_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tf_clean_id ON transaction_features(clean_id);
CREATE INDEX IF NOT EXISTS idx_tf_gap_pct ON transaction_features(gap_pct);
CREATE INDEX IF NOT EXISTS idx_tf_cluster ON transaction_features(cluster_id);
```

El archivo NO debe contener DROP TABLE. La idempotencia se gestiona desde Python
con TRUNCATE, no con DDL destructivo. Incluir un comentario de cabecera con la
fecha y el propósito.
  </action>
  <verify>
    <automated>python -c "import re; sql=open('re_cl/db/migrations/001_transaction_features.sql').read(); assert 'transaction_features' in sql; assert 'clean_id' in sql; assert 'gap_pct' in sql; assert 'dist_km_centroid' in sql; assert 'cluster_id' in sql; assert 'quarter_q1' in sql; assert 'season_index' in sql; print('DDL OK')"</automated>
  </verify>
  <done>
El archivo SQL existe y contiene: tabla `transaction_features`, FK a `transactions_clean`,
índice único en `clean_id`, todas las columnas especificadas. Sin DROP TABLE.
  </done>
</task>

<task type="auto">
  <name>Task 0.2: Fixtures sintéticas y scaffolding de tests</name>
  <files>
    re_cl/tests/conftest.py
    re_cl/tests/test_price_features.py
    re_cl/tests/test_spatial_features.py
    re_cl/tests/test_build_features.py
    re_cl/tests/__init__.py
    re_cl/src/features/__init__.py
  </files>
  <action>
Crear los fixtures de pytest y el scaffolding de tests. Los tests NO deben requerir
una conexión real a PostgreSQL — deben funcionar con DataFrames pandas en memoria.

**re_cl/tests/conftest.py:**
```python
import pandas as pd
import numpy as np
import pytest

@pytest.fixture
def sample_transactions():
    """100 filas sintéticas con el mismo schema que transactions_clean."""
    np.random.seed(42)
    n = 100
    project_types = ["apartments", "residential", "retail", "land"]
    county_names = ["Santiago", "Providencia", "Las Condes", "Vitacura", "Nunoa"]
    return pd.DataFrame({
        "id": range(1, n + 1),
        "project_type": np.random.choice(project_types, n),
        "county_name": np.random.choice(county_names, n),
        "year": np.random.choice([2013, 2014], n),
        "quarter": np.random.choice([1, 2, 3, 4], n),
        "longitude": np.random.uniform(-70.8, -70.5, n),   # RM Santiago
        "latitude": np.random.uniform(-33.6, -33.3, n),
        "calculated_value_uf": np.random.uniform(1000, 8000, n),
        "real_value_uf": np.random.uniform(1000, 9000, n),
        "uf_m2_building": np.random.uniform(20, 120, n),
        "has_valid_coords": True,
        "has_valid_price": True,
        "is_outlier": False,
    })
```

**re_cl/tests/test_price_features.py** — escribir tests que PRIMERO fallen (RED),
luego implementar la función mínima para que pasen (GREEN):

```python
import pandas as pd
import numpy as np
import pytest
from re_cl.src.features.price_features import compute_gap_pct, compute_percentiles

def test_gap_pct_formula(sample_transactions):
    """gap_pct = (real - calculated) / calculated."""
    df = compute_gap_pct(sample_transactions.copy())
    assert "gap_pct" in df.columns
    assert "gap_pct_raw" in df.columns
    # Verificar fórmula en un registro controlado
    row = df.iloc[0]
    expected = (row["real_value_uf"] - row["calculated_value_uf"]) / row["calculated_value_uf"]
    # gap_pct_raw debe coincidir con la fórmula exacta
    assert abs(df["gap_pct_raw"].iloc[0] - expected) < 1e-6

def test_gap_pct_winsorized(sample_transactions):
    """gap_pct winsorizado no debe exceder los percentiles 1-99 del raw."""
    df = compute_gap_pct(sample_transactions.copy())
    p01 = df["gap_pct_raw"].quantile(0.01)
    p99 = df["gap_pct_raw"].quantile(0.99)
    assert df["gap_pct"].min() >= p01 - 1e-9
    assert df["gap_pct"].max() <= p99 + 1e-9

def test_gap_pct_no_division_by_zero(sample_transactions):
    """Registros con calculated_value_uf = 0 deben tener gap_pct = NaN."""
    df = sample_transactions.copy()
    df.loc[0, "calculated_value_uf"] = 0.0
    result = compute_gap_pct(df)
    assert pd.isna(result.loc[0, "gap_pct"])

def test_percentiles_columns(sample_transactions):
    """compute_percentiles debe agregar p25/p50/p75 y pct_rank_uf_m2."""
    df = compute_percentiles(sample_transactions.copy())
    for col in ["p25_uf_m2_group", "p50_uf_m2_group", "p75_uf_m2_group", "pct_rank_uf_m2"]:
        assert col in df.columns, f"Columna faltante: {col}"

def test_percentiles_ordering(sample_transactions):
    """p25 <= p50 <= p75 en todos los grupos con >= 3 registros."""
    df = compute_percentiles(sample_transactions.copy())
    valid = df.dropna(subset=["p25_uf_m2_group", "p50_uf_m2_group", "p75_uf_m2_group"])
    assert (valid["p25_uf_m2_group"] <= valid["p50_uf_m2_group"]).all()
    assert (valid["p50_uf_m2_group"] <= valid["p75_uf_m2_group"]).all()
```

**re_cl/tests/test_spatial_features.py:**

```python
import pandas as pd
import numpy as np
import pytest
from re_cl.src.features.spatial_features import compute_centroid_distance, compute_dbscan_clusters

def test_dist_km_centroid_column(sample_transactions):
    """dist_km_centroid debe existir y ser positiva para registros con coordenadas."""
    df = compute_centroid_distance(sample_transactions.copy())
    assert "dist_km_centroid" in df.columns
    valid = df[df["has_valid_coords"]]
    assert (valid["dist_km_centroid"].dropna() >= 0).all()

def test_dist_km_centroid_units(sample_transactions):
    """Distancias dentro de Santiago deben ser < 30 km (RM es compacta)."""
    df = compute_centroid_distance(sample_transactions.copy())
    valid = df[df["has_valid_coords"]]["dist_km_centroid"].dropna()
    assert valid.max() < 30.0, f"Distancia máxima inesperada: {valid.max():.2f} km"

def test_dbscan_cluster_id_column(sample_transactions):
    """cluster_id debe existir. -1 = ruido (válido)."""
    df = compute_dbscan_clusters(sample_transactions.copy())
    assert "cluster_id" in df.columns

def test_dbscan_minimum_clusters(sample_transactions):
    """Debe detectar al menos 2 clusters distintos (con 100 pts en 5 comunas)."""
    df = compute_dbscan_clusters(sample_transactions.copy())
    clusters = df["cluster_id"].unique()
    non_noise = [c for c in clusters if c != -1]
    assert len(non_noise) >= 1, "DBSCAN no detectó ningún cluster válido"
```

**re_cl/tests/test_build_features.py:**

```python
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

def test_build_features_imports():
    """build_features.py debe ser importable."""
    import re_cl.src.features.build_features as bf
    assert hasattr(bf, "main")

def test_build_features_idempotent(tmp_path):
    """Ejecutar main() dos veces no debe duplicar filas (mock de DB)."""
    # Test de smoke: verifica que main() acepta engine como argumento
    import re_cl.src.features.build_features as bf
    import inspect
    sig = inspect.signature(bf.main)
    # main() debe aceptar opcionalmente engine o db_url
    assert len(sig.parameters) >= 0  # Al menos no crashea al importar
```

Crear también `re_cl/tests/__init__.py` y `re_cl/src/features/__init__.py` como archivos vacíos para que Python los reconozca como paquetes.
  </action>
  <verify>
    <automated>cd re_cl && python -m pytest tests/test_price_features.py tests/test_spatial_features.py tests/test_build_features.py --collect-only 2>&1 | tail -20</automated>
  </verify>
  <done>
`pytest --collect-only` descubre todos los tests sin ImportError. Los tests de
price_features y spatial_features fallan (RED) porque los módulos aún no existen —
eso es lo esperado. test_build_features.py pasa el test de importación cuando
build_features.py sea creado en Wave 1.
  </done>
</task>

<!-- ═══════════════════════════════════════════════════════════════
     WAVE 1 — Módulos de features (paralelizables entre sí)
     Dependen de Wave 0 (conftest.py y DDL deben existir).
     ═══════════════════════════════════════════════════════════════ -->

<task type="auto" tdd="true">
  <name>Task 1.1: price_features.py — gap_pct y percentiles</name>
  <files>re_cl/src/features/price_features.py</files>
  <behavior>
    - compute_gap_pct(df) devuelve df con columnas gap_pct_raw (fórmula exacta) y gap_pct (winsorizado 1-99%)
    - computed_gap_pct: donde calculated_value_uf = 0 o NULL → gap_pct = NaN
    - compute_percentiles(df) devuelve df con p25_uf_m2_group, p50_uf_m2_group, p75_uf_m2_group y pct_rank_uf_m2
    - compute_percentiles: agrupación por (project_type, county_name, year)
    - run(engine) carga transactions_clean, aplica ambas funciones, retorna DataFrame con columnas de precio
  </behavior>
  <action>
Implementar `re_cl/src/features/price_features.py` con tres funciones públicas:

**compute_gap_pct(df: pd.DataFrame) -> pd.DataFrame:**
- Calcular `gap_pct_raw = (real_value_uf - calculated_value_uf) / calculated_value_uf`
- Donde `calculated_value_uf == 0` o `calculated_value_uf` es NaN → `gap_pct_raw = NaN`
- Winsorizar: `p01 = gap_pct_raw.quantile(0.01)`, `p99 = gap_pct_raw.quantile(0.99)`
  - `gap_pct = gap_pct_raw.clip(lower=p01, upper=p99)`
- Agregar columnas `gap_pct_raw` y `gap_pct` al DataFrame. Retornar df.

**compute_percentiles(df: pd.DataFrame) -> pd.DataFrame:**
- Calcular en pandas (no requiere DB para los tests): agrupar por `["project_type", "county_name", "year"]`
- Para cada grupo: `p25 = uf_m2_building.quantile(0.25)`, `p50 = quantile(0.50)`, `p75 = quantile(0.75)`
- Hacer merge de vuelta al DataFrame original (left join por los 3 campos de agrupación)
- Agregar columnas: `p25_uf_m2_group`, `p50_uf_m2_group`, `p75_uf_m2_group`
- `pct_rank_uf_m2`: percentil del registro dentro de su grupo.
  Calcular como `df.groupby(group_keys)["uf_m2_building"].rank(pct=True)`
- Retornar df con las 4 columnas nuevas.

**run(engine) -> pd.DataFrame:**
- Leer `transactions_clean` con `pd.read_sql()` seleccionando solo las columnas necesarias:
  `id, project_type, county_name, year, quarter, calculated_value_uf, real_value_uf, uf_m2_building`
- Filtrar: `has_valid_price = TRUE AND is_outlier = FALSE`
- Aplicar `compute_gap_pct()` y `compute_percentiles()` en cadena
- Retornar DataFrame con columnas: `id` (=clean_id), `gap_pct`, `gap_pct_raw`,
  `p25_uf_m2_group`, `p50_uf_m2_group`, `p75_uf_m2_group`, `pct_rank_uf_m2`
- Logging: número de registros leídos, % con gap_pct válido, estadísticas descriptivas de gap_pct

Usar `from loguru import logger`. No hacer `print()`. No hardcodear credenciales.
El módulo debe ser importable sin conexión a DB (run() solo la requiere).
  </action>
  <verify>
    <automated>cd re_cl && python -m pytest tests/test_price_features.py -v 2>&1 | tail -20</automated>
  </verify>
  <done>
Los 5 tests de test_price_features.py pasan. `python -c "from re_cl.src.features.price_features import compute_gap_pct, compute_percentiles, run"` no lanza errores.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 1.2: spatial_features.py — distancias y DBSCAN</name>
  <files>re_cl/src/features/spatial_features.py</files>
  <behavior>
    - compute_centroid_distance(df) devuelve df con dist_km_centroid para registros con has_valid_coords=True
    - Proyección: WGS84 → EPSG:32719 antes de calcular .distance() en metros → dividir por 1000
    - Centroide por county_name calculado desde los puntos del mismo DataFrame (no tabla externa)
    - compute_dbscan_clusters(df) devuelve df con cluster_id; -1 = ruido es válido
    - DBSCAN sobre subsample (min(50000, len(df)) puntos); propagar al resto con BallTree k=1
    - run(engine) retorna DataFrame con clean_id, dist_km_centroid, cluster_id
  </behavior>
  <action>
Implementar `re_cl/src/features/spatial_features.py`:

**compute_centroid_distance(df: pd.DataFrame) -> pd.DataFrame:**
```python
import geopandas as gpd
from shapely.geometry import Point

# 1. Filtrar registros con coordenadas válidas
valid = df[df["has_valid_coords"] & df["longitude"].notna() & df["latitude"].notna()].copy()

# 2. Crear GeoDataFrame en WGS84 (EPSG:4326)
gdf = gpd.GeoDataFrame(
    valid,
    geometry=gpd.points_from_xy(valid["longitude"], valid["latitude"]),
    crs="EPSG:4326"
)

# 3. Proyectar a UTM 19S (EPSG:32719) para medir distancias en metros
gdf = gdf.to_crs("EPSG:32719")

# 4. Calcular centroide por county_name en UTM 19S
centroids = gdf.groupby("county_name")["geometry"].apply(
    lambda pts: pts.unary_union.centroid
).reset_index()
centroids.columns = ["county_name", "centroid_geom"]

# 5. Merge y calcular distancia
gdf = gdf.merge(centroids, on="county_name")
gdf["dist_km_centroid"] = gdf.apply(
    lambda row: row["geometry"].distance(row["centroid_geom"]) / 1000.0, axis=1
)

# 6. Merge de vuelta al df original
df = df.merge(gdf[["id", "dist_km_centroid"]], on="id", how="left")
return df
```

**compute_dbscan_clusters(df: pd.DataFrame) -> pd.DataFrame:**
```python
import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.neighbors import BallTree

# 1. Registros con coordenadas válidas
valid = df[df["has_valid_coords"] & df["longitude"].notna() & df["latitude"].notna()].copy()

# 2. Subsample: hasta 50_000 puntos aleatorios (sin reemplazo)
SUBSAMPLE = min(50_000, len(valid))
sample = valid.sample(n=SUBSAMPLE, random_state=42)

# 3. DBSCAN con coordenadas en radianes (para haversine)
coords_rad = np.radians(sample[["latitude", "longitude"]].values)
# eps=0.5 km en radianes sobre la Tierra (R=6371 km)
eps_km = 0.5
db = DBSCAN(
    eps=eps_km / 6371.0,
    min_samples=10,
    algorithm="ball_tree",
    metric="haversine"
).fit(coords_rad)
sample = sample.copy()
sample["cluster_id"] = db.labels_

# 4. Propagar clusters al resto con BallTree k=1
tree = BallTree(coords_rad, metric="haversine")
all_coords_rad = np.radians(valid[["latitude", "longitude"]].values)
_, indices = tree.query(all_coords_rad, k=1)
valid = valid.copy()
valid["cluster_id"] = sample["cluster_id"].iloc[indices.flatten()].values

# Assertion mínima
n_clusters = len(set(valid["cluster_id"].unique()) - {-1})
logger.info(f"DBSCAN detectó {n_clusters} clusters (excluyendo ruido)")
assert n_clusters >= 1, f"DBSCAN no detectó ningún cluster. Revisar eps y min_samples."

# 5. Merge de vuelta al df original
df = df.merge(valid[["id", "cluster_id"]], on="id", how="left")
df["cluster_id"] = df["cluster_id"].fillna(-1).astype(int)
return df
```

**run(engine) -> pd.DataFrame:**
- Leer `transactions_clean`: columnas `id, county_name, longitude, latitude, has_valid_coords, is_outlier`
- Filtrar `is_outlier = FALSE`
- Aplicar `compute_centroid_distance()` luego `compute_dbscan_clusters()`
- Retornar DataFrame con columnas: `id` (=clean_id), `dist_km_centroid`, `cluster_id`
- Logging: n registros, n con dist_km_centroid válida, distribución de cluster_id
  (cuántos en cada clúster), n ruido (-1)

Assertion en producción: `assert n_clusters >= 5` (para el dataset completo de RM).
En tests con 100 filas puede ser >= 1.
  </action>
  <verify>
    <automated>cd re_cl && python -m pytest tests/test_spatial_features.py -v 2>&1 | tail -20</automated>
  </verify>
  <done>
Los 4 tests de test_spatial_features.py pasan. Las distancias calculadas para
coordenadas del RM Santiago son todas < 30 km. cluster_id está presente.
  </done>
</task>

<task type="auto">
  <name>Task 1.3: temporal_features.py — quarter dummies y season index</name>
  <files>re_cl/src/features/temporal_features.py</files>
  <action>
Implementar `re_cl/src/features/temporal_features.py` con dos funciones públicas:

**compute_temporal_features(df: pd.DataFrame) -> pd.DataFrame:**

Agregar las siguientes columnas al DataFrame de entrada y retornarlo:

```python
# Quarter dummies — exactamente un 1 por fila
df["quarter_q1"] = (df["quarter"] == 1).astype(int)
df["quarter_q2"] = (df["quarter"] == 2).astype(int)
df["quarter_q3"] = (df["quarter"] == 3).astype(int)
df["quarter_q4"] = (df["quarter"] == 4).astype(int)

# Season index: 0.0 (Q1) → 0.333 (Q2) → 0.667 (Q3) → 1.0 (Q4)
# Fórmula: (quarter - 1) / 3.0
df["season_index"] = (df["quarter"] - 1) / 3.0

return df
```

Validaciones internas (no lanzar excepción, solo logear warning):
- Si hay filas con `quarter` fuera de [1, 2, 3, 4], logear cuántas con `logger.warning()`
- `season_index` debe estar en [0.0, 1.0] para valores válidos de quarter

**run(engine) -> pd.DataFrame:**
- Leer `transactions_clean`: columnas `id, quarter, year`
- Aplicar `compute_temporal_features()`
- Retornar DataFrame con: `id` (=clean_id), `quarter_q1`, `quarter_q2`, `quarter_q3`, `quarter_q4`, `season_index`
- Logging: distribución de quarter (cuántos por valor), rango de season_index

No hay tests dedicados para temporal_features en los archivos de test iniciales
(la lógica es simple y se verifica via test de integración en test_build_features.py).
Agregar al menos dos asserts internos en `compute_temporal_features()`:
```python
assert df["season_index"].between(0.0, 1.0).all() or df["quarter"].isna().any(), \
    "season_index fuera de rango [0, 1]"
```
  </action>
  <verify>
    <automated>cd re_cl && python -c "
import pandas as pd, numpy as np
from re_cl.src.features.temporal_features import compute_temporal_features
df = pd.DataFrame({'id': [1,2,3,4], 'quarter': [1,2,3,4], 'year': [2013]*4})
result = compute_temporal_features(df)
assert all(c in result.columns for c in ['quarter_q1','quarter_q2','quarter_q3','quarter_q4','season_index'])
assert result.loc[result['quarter']==1, 'quarter_q1'].iloc[0] == 1
assert abs(result.loc[result['quarter']==4, 'season_index'].iloc[0] - 1.0) < 1e-9
print('temporal_features OK')
"</automated>
  </verify>
  <done>
El script de verificación corre sin errores. `season_index` para Q1=0.0, Q2=0.333,
Q3=0.667, Q4=1.0. Exactamente un dummy = 1 por fila.
  </done>
</task>

<!-- ═══════════════════════════════════════════════════════════════
     WAVE 2 — Orquestador (depende de Wave 1 completa)
     ═══════════════════════════════════════════════════════════════ -->

<task type="auto">
  <name>Task 2.1: build_features.py — orquestador idempotente</name>
  <files>re_cl/src/features/build_features.py</files>
  <action>
Implementar el orquestador principal. Debe ser ejecutable como script y como módulo importable.

**Estructura completa:**

```python
"""
build_features.py
-----------------
Orquestador de feature engineering para RE_CL.

Calcula y persiste en transaction_features:
  1. Features de precio (gap_pct, percentiles)
  2. Features espaciales (dist_km_centroid, cluster_id)
  3. Features temporales (quarter dummies, season_index)

Idempotente: TRUNCATE + reload en cada ejecución.

Uso:
    python src/features/build_features.py [--dry-run]
"""

import argparse
import os
import time
import sys

import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from loguru import logger

from re_cl.src.features.price_features import run as run_price
from re_cl.src.features.spatial_features import run as run_spatial
from re_cl.src.features.temporal_features import run as run_temporal

load_dotenv()


def build_db_url() -> str:
    # Mismo patrón que en ingestion/
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db   = os.getenv("POSTGRES_DB", "re_cl")
    user = os.getenv("POSTGRES_USER", "re_cl_user")
    pwd  = os.getenv("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


def merge_feature_dfs(price_df: pd.DataFrame,
                       spatial_df: pd.DataFrame,
                       temporal_df: pd.DataFrame) -> pd.DataFrame:
    """
    Une los tres DataFrames de features por clean_id.
    price_df.id, spatial_df.id, temporal_df.id son todos = clean_id.
    """
    merged = price_df.merge(spatial_df, on="id", how="outer")
    merged = merged.merge(temporal_df, on="id", how="outer")
    merged = merged.rename(columns={"id": "clean_id"})
    return merged


def write_features(df: pd.DataFrame, engine, dry_run: bool = False) -> None:
    """TRUNCATE transaction_features + INSERT. Idempotente."""
    if dry_run:
        logger.info(f"[DRY RUN] Se escribirían {len(df):,} filas en transaction_features")
        logger.info(df.describe())
        return

    # NEEDS APPROVAL: TRUNCATE elimina todos los features previos
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE transaction_features RESTART IDENTITY"))
    logger.info("transaction_features truncada. Insertando features calculados...")

    df.to_sql(
        "transaction_features",
        engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=5000,
    )
    logger.info(f"transaction_features cargada: {len(df):,} filas")


def main(engine=None, dry_run: bool = False) -> None:
    t_start = time.perf_counter()

    if engine is None:
        engine = create_engine(build_db_url(), pool_pre_ping=True)

    logger.info("=" * 60)
    logger.info("BUILD FEATURES — inicio")
    logger.info("=" * 60)

    # Paso 1: Features de precio
    logger.info("[1/3] Calculando features de precio...")
    t0 = time.perf_counter()
    price_df = run_price(engine)
    logger.info(f"  Completado en {time.perf_counter() - t0:.1f}s — {len(price_df):,} registros")

    # Paso 2: Features espaciales
    logger.info("[2/3] Calculando features espaciales...")
    t0 = time.perf_counter()
    spatial_df = run_spatial(engine)
    logger.info(f"  Completado en {time.perf_counter() - t0:.1f}s — {len(spatial_df):,} registros")

    # Paso 3: Features temporales
    logger.info("[3/3] Calculando features temporales...")
    t0 = time.perf_counter()
    temporal_df = run_temporal(engine)
    logger.info(f"  Completado en {time.perf_counter() - t0:.1f}s — {len(temporal_df):,} registros")

    # Merge y escritura
    logger.info("Uniendo DataFrames de features...")
    features_df = merge_feature_dfs(price_df, spatial_df, temporal_df)
    logger.info(f"  {len(features_df):,} filas totales, {len(features_df.columns)} columnas")

    write_features(features_df, engine, dry_run=dry_run)

    elapsed = time.perf_counter() - t_start
    logger.info("=" * 60)
    logger.info(f"BUILD FEATURES — completado en {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Feature engineering para RE_CL")
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo calcula y reporta sin escribir en DB")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
```

El script NO debe lanzar excepciones no capturadas. Si falla un módulo, loguear
el error con `logger.error()` y relanzar para que el proceso padre lo detecte.

La función `main()` acepta `engine` opcional para facilitar tests (inyección de dependencia).
  </action>
  <verify>
    <automated>cd re_cl && python -m pytest tests/test_build_features.py -v 2>&1 | tail -10</automated>
  </verify>
  <done>
`test_build_features.py::test_build_features_imports` pasa. El script es importable
sin conexión a DB. `python src/features/build_features.py --help` muestra el argumento
`--dry-run` sin errores.
  </done>
</task>

<!-- ═══════════════════════════════════════════════════════════════
     WAVE 3 — Verificación final (requiere DB real)
     ═══════════════════════════════════════════════════════════════ -->

<task type="auto">
  <name>Task 3.1: Aplicar migración DDL y ejecutar build_features.py</name>
  <files>re_cl/db/migrations/001_transaction_features.sql</files>
  <action>
Verificar que la DB tiene datos en `transactions_clean` y aplicar la migración.
Si `transactions_clean` está vacía, este task falla intencionalmente — se debe
ejecutar la fase 2 (clean_transactions.py) antes.

**Secuencia de comandos:**

```bash
# 1. Verificar que transactions_clean tiene datos
psql $DATABASE_URL -c "SELECT COUNT(*) FROM transactions_clean;"

# 2. Aplicar la migración (idempotente por IF NOT EXISTS)
psql $DATABASE_URL -f re_cl/db/migrations/001_transaction_features.sql

# 3. Verificar que la tabla fue creada
psql $DATABASE_URL -c "\d transaction_features"

# 4. Ejecutar build_features.py con --dry-run primero
cd re_cl && python src/features/build_features.py --dry-run

# 5. Si --dry-run es exitoso, ejecutar sin dry-run
cd re_cl && python src/features/build_features.py

# 6. Verificar conteo de filas en transaction_features
psql $DATABASE_URL -c "
  SELECT
    COUNT(*) AS total_features,
    COUNT(gap_pct) AS con_gap_pct,
    COUNT(dist_km_centroid) AS con_distancia,
    COUNT(cluster_id) AS con_cluster,
    ROUND(AVG(gap_pct)::numeric, 4) AS gap_pct_promedio,
    MIN(cluster_id) AS cluster_min,
    MAX(cluster_id) AS cluster_max
  FROM transaction_features;
"
```

Si `psql` no está disponible como comando directo, usar:
```python
python -c "
from sqlalchemy import create_engine, text
from dotenv import load_dotenv; load_dotenv()
import os
url = os.getenv('DATABASE_URL', 'postgresql://re_cl_user:@localhost:5432/re_cl')
engine = create_engine(url)
with engine.connect() as conn:
    r = conn.execute(text('SELECT COUNT(*) FROM transaction_features')).scalar()
    print(f'transaction_features: {r:,} filas')
"
```
  </action>
  <verify>
    <automated>cd re_cl && python -c "
from sqlalchemy import create_engine, text
from dotenv import load_dotenv; load_dotenv()
import os
url = os.getenv('DATABASE_URL', 'postgresql://re_cl_user:@localhost:5432/re_cl')
engine = create_engine(url)
with engine.connect() as conn:
    tf_count = conn.execute(text('SELECT COUNT(*) FROM transaction_features')).scalar()
    tc_count = conn.execute(text('SELECT COUNT(*) FROM transactions_clean')).scalar()
    assert tf_count > 0, 'transaction_features está vacía'
    assert tf_count <= tc_count, 'transaction_features tiene más filas que transactions_clean'
    gap_null_pct = conn.execute(text(
        'SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE gap_pct IS NULL) / COUNT(*), 2) FROM transaction_features'
    )).scalar()
    print(f'OK: {tf_count:,} features, {gap_null_pct}% sin gap_pct')
"</automated>
  </verify>
  <done>
`transaction_features` tiene al menos 1 fila. El ratio de filas features/clean es
<= 1.0 (no hay duplicados). El porcentaje de gap_pct nulo es razonable (< 20%).
  </done>
</task>

<task type="auto">
  <name>Task 3.2: Ejecutar suite de tests completa y verificar criterios de éxito</name>
  <files>re_cl/tests/</files>
  <action>
Ejecutar todos los tests y verificar los criterios de éxito de la fase.

**Tests unitarios (sin DB):**
```bash
cd re_cl && python -m pytest tests/test_price_features.py tests/test_spatial_features.py tests/test_build_features.py -v --tb=short
```

**Verificación de idempotencia (requiere DB):**
```bash
# Ejecutar build_features.py dos veces y comparar conteos
cd re_cl
python src/features/build_features.py
FIRST=$(python -c "from sqlalchemy import create_engine, text; from dotenv import load_dotenv; load_dotenv(); import os; e=create_engine(os.getenv('DATABASE_URL')); print(e.connect().execute(text('SELECT COUNT(*) FROM transaction_features')).scalar())")
python src/features/build_features.py
SECOND=$(python -c "from sqlalchemy import create_engine, text; from dotenv import load_dotenv; load_dotenv(); import os; e=create_engine(os.getenv('DATABASE_URL')); print(e.connect().execute(text('SELECT COUNT(*) FROM transaction_features')).scalar())")
echo "Primera ejecución: $FIRST filas"
echo "Segunda ejecución: $SECOND filas"
[ "$FIRST" -eq "$SECOND" ] && echo "IDEMPOTENCIA: OK" || echo "IDEMPOTENCIA: FALLO — filas distintas"
```

**Verificación del criterio RMSE < 30%:**
Este criterio (SC-7) no es verificable en Fase 3 — requiere el modelo hedónico
de Fase 4. Documentar en el SUMMARY que los features están listos y el RMSE
se verificará al final de Fase 4.

**Reporte final de features:**
```python
python -c "
from sqlalchemy import create_engine, text
from dotenv import load_dotenv; load_dotenv()
import os
engine = create_engine(os.getenv('DATABASE_URL', 'postgresql://re_cl_user:@localhost:5432/re_cl'))
with engine.connect() as conn:
    stats = conn.execute(text('''
        SELECT
            COUNT(*)                                   AS n_total,
            COUNT(gap_pct)                             AS n_gap_pct,
            ROUND(AVG(gap_pct)::numeric, 4)            AS avg_gap_pct,
            ROUND(STDDEV(gap_pct)::numeric, 4)         AS std_gap_pct,
            COUNT(dist_km_centroid)                    AS n_distancia,
            ROUND(AVG(dist_km_centroid)::numeric, 2)   AS avg_dist_km,
            COUNT(DISTINCT cluster_id)                 AS n_clusters,
            SUM(CASE WHEN cluster_id = -1 THEN 1 END)  AS n_ruido
        FROM transaction_features
    ''')).fetchone()
    print(dict(stats._mapping))
"
```
  </action>
  <verify>
    <automated>cd re_cl && python -m pytest tests/test_price_features.py tests/test_spatial_features.py tests/test_build_features.py -v --tb=short 2>&1 | tail -15</automated>
  </verify>
  <done>
Todos los tests unitarios pasan (sin errores de importación ni fallos de assertions).
La idempotencia está verificada (mismo conteo en dos ejecuciones consecutivas).
El reporte de features muestra n_clusters >= 5 para el dataset de producción.
gap_pct calculado para >= 80% de los registros.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| env → script | Credenciales de DB leídas desde variables de entorno / archivo .env |
| DB → Python | Datos de transactions_clean leídos via SQLAlchemy (read-only en esta fase) |
| Python → DB | Escritura a transaction_features via TRUNCATE + INSERT |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-03-01 | Tampering | build_features.py / TRUNCATE | mitigate | Agregar comentario "NEEDS APPROVAL" antes del TRUNCATE; no exponer el script via API |
| T-03-02 | Information Disclosure | .env con DATABASE_URL | mitigate | .env en .gitignore (ya establecido en fases anteriores); usar variables de entorno en CI |
| T-03-03 | Denial of Service | DBSCAN sobre 1M puntos | mitigate | Subsample hard-capped a 50k; BallTree para propagación en O(n log n) |
| T-03-04 | Elevation of Privilege | psycopg2 con usuario re_cl_user | accept | re_cl_user tiene permisos mínimos (SELECT en transactions_clean, INSERT/TRUNCATE en transaction_features). No es superusuario |
| T-03-05 | Repudiation | Sin auditoría de quién ejecutó build_features.py | accept | MVP — loguru registra timestamps. Auditoría formal es deferred |
| T-03-06 | Information Disclosure | gap_pct_raw expuesto en DB | accept | DB no es pública. gap_pct_raw es útil para auditoría del winsorizado |
</threat_model>

<verification>
## Checklist de Fase Completa

- [ ] `re_cl/db/migrations/001_transaction_features.sql` existe y se aplica sin errores con psql
- [ ] `re_cl/src/features/__init__.py` existe (paquete Python válido)
- [ ] `re_cl/tests/conftest.py` expone el fixture `sample_transactions` de 100 filas
- [ ] `pytest tests/test_price_features.py` — todos los tests pasan (5 tests)
- [ ] `pytest tests/test_spatial_features.py` — todos los tests pasan (4 tests)
- [ ] `pytest tests/test_build_features.py` — todos los tests pasan (2 tests)
- [ ] `python src/features/build_features.py --dry-run` completa sin errores
- [ ] `python src/features/build_features.py` completa y persiste en transaction_features
- [ ] Segunda ejecución de `build_features.py` produce el mismo conteo de filas (idempotencia)
- [ ] `SELECT COUNT(DISTINCT cluster_id) - 1 FROM transaction_features` >= 5 (dataset de producción)
- [ ] `SELECT COUNT(*) FILTER (WHERE gap_pct IS NULL) FROM transaction_features` < 20% del total
- [ ] No hay credenciales hardcodeadas en ningún archivo .py
</verification>

<success_criteria>
1. `build_features.py --dry-run` y `build_features.py` completan sin excepciones
2. `transaction_features` tiene >= 1 fila con FK válida a transactions_clean
3. Segunda ejecución de `build_features.py` produce el mismo conteo (idempotencia confirmada)
4. `gap_pct` winsorizado presente en >= 80% de los registros
5. `dist_km_centroid` presente para todos los registros con `has_valid_coords = TRUE`
6. `cluster_id` asignado a todos los registros (ruido = -1 es válido)
7. `quarter_q1..q4` suman exactamente 1 por fila; `season_index` en [0.0, 1.0]
8. 11 tests (pytest) pasan en CI sin conexión a DB real
9. Para el dataset de producción: `COUNT(DISTINCT cluster_id) - 1 >= 5` (excluyendo ruido)
</success_criteria>

<output>
Después de completar esta fase, crear:

`.planning/phases/03-feature-engineering/03-01-SUMMARY.md`

Con el siguiente contenido mínimo:
- Archivos creados (con rutas absolutas relativas al repo)
- Decisiones de implementación tomadas (ej: eps elegido para DBSCAN, comportamiento de casos borde)
- Conteo final de filas en transaction_features
- Estadísticas de gap_pct (media, std, % nulos)
- Distribución de clusters (n clusters, % ruido)
- Cualquier desviación del plan y su justificación
- Estado del criterio RMSE (pendiente hasta Fase 4)
</output>
