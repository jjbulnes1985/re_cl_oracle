# Prompt: Enriquecer datos Data Inmobiliaria (DI) — pipeline completo

## Contexto

Eres el ingeniero principal de RE_CL, una plataforma para detectar inmuebles subvalorados en Chile (RM Santiago). El proyecto usa un modelo XGBoost hedónico (R²=0.6850) que predice `uf_m2_building` y calcula scores de subvaloración.

Se están acumulando datos frescos de **Data Inmobiliaria** (transacciones CBR 2019-2026) mediante scraping diario automatizado. Cada vez que se completen comunas nuevas, estos datos deben pasar por el pipeline de enriquecimiento completo para ser usados por el modelo.

**Directorio de trabajo:** `c:\Users\jjbul\Dropbox\Trabajos (Material)\JJB\IA\Juan Montes\RE_CL\re_cl\`

---

## Estado actual (verificar antes de empezar)

Antes de ejecutar cualquier paso, corre este diagnóstico para saber exactamente cuántos rows nuevos hay que procesar:

```python
# diagnóstico_di.py — correr con: py diagnóstico_di.py
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
load_dotenv()
url = os.getenv("DATABASE_URL") or f"postgresql://{os.getenv('POSTGRES_USER','re_cl_user')}:{os.getenv('POSTGRES_PASSWORD','')}@{os.getenv('POSTGRES_HOST','localhost')}:{os.getenv('POSTGRES_PORT','5432')}/{os.getenv('POSTGRES_DB','re_cl')}"
engine = create_engine(url)
with engine.connect() as conn:
    raw_di   = conn.execute(text("SELECT COUNT(*) FROM transactions_raw WHERE data_source='data_inmobiliaria'")).scalar()
    clean_total = conn.execute(text("SELECT COUNT(*) FROM transactions_clean")).scalar()
    raw_total   = conn.execute(text("SELECT COUNT(*) FROM transactions_raw")).scalar()
    feat_total  = conn.execute(text("SELECT COUNT(*) FROM transaction_features")).scalar()
    score_total = conn.execute(text("SELECT COUNT(*) FROM model_scores")).scalar()
    geom_null   = conn.execute(text("SELECT COUNT(*) FROM transactions_raw WHERE data_source='data_inmobiliaria' AND geom IS NULL")).scalar()
    print(f"transactions_raw  total: {raw_total:,}  |  DI rows: {raw_di:,}  |  geom NULL: {geom_null}")
    print(f"transactions_clean:      {clean_total:,}")
    print(f"transaction_features:    {feat_total:,}")
    print(f"model_scores:            {score_total:,}")
    print(f"Gap raw→clean: {raw_total - clean_total:,} rows pendientes de limpiar")
    print(f"Gap clean→feat: {clean_total - feat_total:,} rows pendientes de featurizar")
```

**Baseline conocido (2026-04-30):**
| Tabla | Rows | Nota |
|-------|------|------|
| `transactions_raw` | 1,429,036 | incluye 42,249 DI |
| `transactions_clean` | 783,637 | DI aún no procesados |
| `transaction_features` | 734,334 | |
| `model_scores` | 961,318 | |

---

## Pipeline de enriquecimiento — ejecutar en orden

### PASO 0 — Verificar geom PostGIS

Los datos DI deben tener `geom` poblado para que funcionen los features espaciales. Si `geom NULL > 0`:

```bash
py -c "
import os; from dotenv import load_dotenv; from sqlalchemy import create_engine, text; load_dotenv()
url = os.getenv('DATABASE_URL')
engine = create_engine(url)
with engine.begin() as conn:
    r = conn.execute(text('''
        UPDATE transactions_raw SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
        WHERE longitude IS NOT NULL AND latitude IS NOT NULL AND geom IS NULL AND data_source='data_inmobiliaria'
    '''))
    print(f'geom actualizado: {r.rowcount} filas')
"
```

**Criterio de éxito:** `geom NULL = 0` para todos los rows DI.

---

### PASO 1 — Limpieza y normalización (`clean_transactions.py`)

```bash
py src/ingestion/clean_transactions.py
```

**Qué hace:**
- Deduplica por `id_role` (Rol SII)
- Detecta y convierte CLP → UF (umbral ratio 500)
- Calcula `data_confidence` (0–1) basado en completitud de campos
- Marca outliers (`is_outlier`, `outlier_reason`)
- Imputa superficies faltantes
- Calcula `uf_m2_building` y `uf_m2_land`
- Popula `transactions_clean`

**Verificar antes:** correr `--dry-run` primero para revisar el reporte:
```bash
py src/ingestion/clean_transactions.py --dry-run
```
Revisar que no haya anomalías en la distribución de precios DI (los datos son 2019-2026, deben tener precios más altos que el dataset histórico 2008-2018).

**Criterio de éxito:** `transactions_clean` debe crecer en ≥ 30,000 rows (asumiendo ~70% de filas DI pasan filtros de calidad).

---

### PASO 2 — Feature engineering (`build_features.py`)

```bash
py src/features/build_features.py --skip-ieut
```

Usar `--skip-ieut` a menos que los shapefiles ieut-inciti estén disponibles en `IEUT_DATA_DIR`. Si están disponibles, correr sin el flag (tarda ~30min adicionales).

**Qué calcula para cada fila nueva en `transactions_clean`:**

| Dimensión | Features | Script |
|-----------|----------|--------|
| Precio | `gap_pct`, `price_percentile_25/50/75`, `price_vs_median` | `price_features.py` |
| Espacial | `dist_km_centroid`, `cluster_id` (DBSCAN 500m) | `spatial_features.py` |
| Temporal | `quarter_q1-q4`, `season_index` | `temporal_features.py` |
| Tesis | `age`, `age_sq`, `construction_year_bucket`, `city_zone`, `log_surface` | thesis features |
| OSM | `dist_metro_km`, `dist_school_km`, `dist_hospital_km`, `dist_park_km`, `dist_mall_km`, `dist_bus_stop_km`, `amenities_500m/1km` | `osm_features.py` |
| GTFS | `dist_gtfs_bus_km` | `gtfs_features.py` |
| ieut | 16 features de shapefiles locales (dist_green_area_km, dist_autopista_km, etc.) | `ieut_spatial_features.py` |

**Criterio de éxito:** `transaction_features` debe crecer proporcionalmente a `transactions_clean`.

---

### PASO 3 — Evaluar si reentrenar el modelo

**Condición para reentrenar:** cuando DI tenga ≥ 10 comunas completas (actualmente 6/40). El modelo actual (R²=0.6850) fue entrenado con datos 2008-2018. Los datos DI son 2019-2026 — un período diferente, por lo que el impacto de reentrenar es alto.

**Verificar R² esperado:**
```bash
py src/models/hedonic_model.py --dry-run  # si existe el flag, solo evalúa sin escribir
```

**Para reentrenar:**
```bash
py src/models/hedonic_model.py
```

**Qué hace:**
- Train/test split temporal (últimos 2 años como test)
- Entrena XGBoost con todos los features disponibles
- Guarda `models/hedonic_model_v1.pkl` y `models/label_encoders_v1.pkl`
- Reporta R², RMSE, feature importances y SHAP top-10

**Criterio de éxito:** R² ≥ 0.70 (objetivo declarado en roadmap). Si baja, investigar antes de reemplazar el modelo actual.

> **IMPORTANTE:** Si el R² baja al incluir datos DI, puede ser por:
> 1. Inflación de precios 2019-2026 no capturada por features temporales
> 2. Cambios de mercado post-pandemia
> 3. Datos DI con menos comunas representadas aún
> En ese caso, mantener el modelo anterior y registrar en CLAUDE.md.

---

### PASO 4 — Scoring (`opportunity_score.py`)

```bash
py src/scoring/opportunity_score.py
py src/scoring/opportunity_score.py --profile location
py src/scoring/opportunity_score.py --profile growth
py src/scoring/opportunity_score.py --profile safety
```

**Qué hace:**
- Calcula `undervaluation_score` (percentile rank de `gap_pct`)
- Calcula scores compuestos por perfil
- Escribe en `model_scores` con SHAP top-3 en JSONB

**Criterio de éxito:** `model_scores` debe crecer en filas correspondientes a los nuevos datos.

---

### PASO 5 — Actualizar calibración comunal

Si se reentrenó el modelo, actualizar la calibración post-hoc:

```bash
py -c "
# Recalcular residuales medianos por (model_version, county_name, project_type)
# y actualizar tabla commune_calibration (128 rows, 40 comunas)
# Ver src/scoring/opportunity_score.py para lógica de calibración
"
```

Verificar que las comunas nuevas de DI (Ñuñoa, La Florida, Maipú, etc.) tengan entradas en `commune_calibration`.

---

### PASO 6 — Normalizar county_name (`normalize_county.py`)

```bash
py src/ingestion/normalize_county.py
py src/ingestion/normalize_county.py --report
```

Asegurarse de que los `county_name` de los datos DI estén normalizados al vocabulario canónico de 40 comunas RM (fuzzy match score ≥ 85).

---

### PASO 7 — Actualizar mapas y reporte

```bash
py src/maps/commune_ranking.py
py src/maps/heatmap.py
py src/reports/generate_report.py --top-n 50
```

El reporte HTML incluye:
- Top 50 oportunidades con score, SHAP drivers, comuna, tipo
- Distribución de scores por comuna
- Mapa de calor interactivo

**Verificar:** abrir `data/exports/report_YYYY-MM-DD.html` y confirmar que aparecen comunas DI (Ñuñoa, La Florida, Maipú, etc.) en los rankings.

---

### PASO 8 — Validación final

```bash
py scripts/validate_data.py --json --exit-code
```

12 checks automáticos. Debe pasar sin errores críticos. Revisar especialmente:
- `data_confidence` promedio de filas DI (esperado ≥ 0.65)
- Distribución de `uf_m2_building` por comuna DI vs histórico (detecta outliers de precio)
- Cobertura de `geom` (debe ser 100% para filas DI)
- Cobertura de features OSM (si dist_metro_km es NULL en filas DI, hay un problema en build_features)

---

## Checklist de enriquecimiento completo

```
[ ] PASO 0: geom NULL = 0 para todos los rows DI
[ ] PASO 1: clean_transactions.py — filas nuevas en transactions_clean
[ ] PASO 2: build_features.py — filas nuevas en transaction_features con TODOS los features
[ ] PASO 3: modelo reentrenado (o documentado por qué no conviene aún)
[ ] PASO 4: scoring actualizado — filas nuevas en model_scores
[ ] PASO 5: commune_calibration actualizada con comunas DI nuevas
[ ] PASO 6: county_name normalizados
[ ] PASO 7: heatmap + report generados
[ ] PASO 8: validate_data.py sin errores críticos
```

---

## Criterios de calidad mínimos para los datos DI

| Métrica | Mínimo aceptable |
|---------|-----------------|
| `data_confidence` promedio DI | ≥ 0.60 |
| Cobertura `geom` DI | 100% |
| Cobertura `dist_metro_km` DI | ≥ 90% |
| Cobertura `gap_pct` DI | ≥ 85% |
| `is_outlier` DI | ≤ 15% del total |
| R² modelo tras reentrenar | ≥ 0.68 (no bajar del baseline) |

---

## Contexto importante sobre los datos DI

- **Período:** 2019-2026 (datos frescos post-pandemia)
- **Fuente:** CBR vía datainmobiliaria.cl (transacciones reales inscriptas, no publicaciones)
- **Precio:** viene en UF directamente de la API
- **Coordenadas:** incluidas en la API (`lat`/`lng` de cada transacción)
- **Rol SII (`id_role`):** sirve para deduplicar y linkear con datos catastrales
- **Dirección SII (`apartment`):** campo texto libre, útil para geocodificación adicional
- **Avalúo fiscal (`calculated_value`):** en CLP, útil para calcular ratio avalúo/precio de mercado
- **Comunas actualmente disponibles:** Santiago (404), Providencia (434), Las Condes (142), Ñuñoa (15,637), La Florida (14,127), Maipú (11,505) — total 42,249 rows

---

## Notas de arquitectura

- `build_features.py` es **idempotente**: solo procesa filas nuevas en `transactions_clean` que aún no tienen entrada en `transaction_features`.
- `opportunity_score.py` es **idempotente**: versiona por `MODEL_VERSION` env var.
- Si `clean_transactions.py` falla con errores de coordenadas fuera de Chile bbox, revisar que los polígonos de búsqueda en `RM_COMMUNE_POLYGONS` del scraper sean correctos.
- El modelo NO debe reentrenarse en cada sesión DI — solo cuando haya suficiente data nueva (≥ 10 comunas) para justificar el costo de reentrenamiento.

---

## Documentación a actualizar tras completar

Actualizar en **CLAUDE.md** y **RE_CL.md**:
- Tabla de progreso DI (comunas completadas, total rows)
- Estado del modelo (R², fecha de último reentrenamiento)
- Rows en cada tabla del pipeline

```bash
# Comando para obtener resumen actualizado
py src/scraping/datainmobiliaria.py --list-status
```
