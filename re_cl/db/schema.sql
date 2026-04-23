-- RE_CL: Plataforma de Detección de Inmuebles Subvalorados en Chile
-- Schema principal con soporte geoespacial via PostGIS
-- Versión: 1.0 — MVP

-- ============================================================
-- EXTENSIONES
-- ============================================================
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- Para búsquedas de texto en direcciones


-- ============================================================
-- TABLA: transactions_raw
-- Datos crudos del CSV del Conservador de Bienes Raíces (CBR)
-- ~1M registros, RM Santiago, 2013-2014
-- ============================================================
CREATE TABLE IF NOT EXISTS transactions_raw (
    id                      SERIAL PRIMARY KEY,

    -- Identificación
    project_type_name       VARCHAR(100),           -- Apartments, Residential, Retail, Land, etc.
    id_role                 VARCHAR(50),             -- Rol de la propiedad (ej: 833-75)

    -- Temporalidad
    year_building           SMALLINT,               -- Año de construcción
    inscription_date        DATE,                   -- Fecha de inscripción en CBR
    quarter                 SMALLINT,               -- Trimestre (1-4)
    year                    SMALLINT,               -- Año de transacción
    bimester                SMALLINT,               -- Bimestre (1-6)

    -- Geografía
    county_name             VARCHAR(100),           -- Comuna
    longitude               NUMERIC(12, 8),         -- Longitud decimal
    latitude                NUMERIC(12, 8),         -- Latitud decimal
    geom                    GEOMETRY(Point, 4326),  -- Punto geoespacial WGS84

    -- Valores monetarios (en UF)
    calculated_value        NUMERIC(18, 4),         -- Valor calculado/avalúo
    real_value              NUMERIC(18, 4),         -- Valor real de transacción
    uf_value                NUMERIC(10, 4),         -- Valor de la UF al momento

    -- Superficies (m²)
    surface                 NUMERIC(10, 2),         -- Superficie principal
    total_surface_building  NUMERIC(10, 2),         -- Superficie construida
    total_surface_land      NUMERIC(10, 2),         -- Superficie de terreno

    -- Precios unitarios (UF/m²)
    uf_m2_u                 NUMERIC(10, 4),         -- UF/m² construido
    uf_m2_t                 NUMERIC(10, 4),         -- UF/m² terreno

    -- Partes de la transacción
    buyer_name              TEXT,
    seller_name             TEXT,

    -- Ubicación textual
    address                 TEXT,
    apartment               VARCHAR(100),
    village                 TEXT,                   -- Condominio/conjunto

    -- Metadata de carga
    loaded_at               TIMESTAMPTZ DEFAULT NOW(),
    is_cleaned              BOOLEAN DEFAULT FALSE,
    cleaning_notes          TEXT                    -- Observaciones del proceso de limpieza
);

-- Índices principales
CREATE INDEX IF NOT EXISTS idx_tr_geom       ON transactions_raw USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_tr_county     ON transactions_raw(county_name);
CREATE INDEX IF NOT EXISTS idx_tr_type       ON transactions_raw(project_type_name);
CREATE INDEX IF NOT EXISTS idx_tr_date       ON transactions_raw(inscription_date);
CREATE INDEX IF NOT EXISTS idx_tr_year       ON transactions_raw(year);
CREATE INDEX IF NOT EXISTS idx_tr_id_role    ON transactions_raw(id_role);
CREATE INDEX IF NOT EXISTS idx_tr_address    ON transactions_raw USING GIN(address gin_trgm_ops);


-- ============================================================
-- TABLA: transactions_clean
-- Vista materializada de transacciones normalizadas y validadas
-- Se regenera después de cada corrida de clean_transactions.py
-- ============================================================
CREATE TABLE IF NOT EXISTS transactions_clean (
    id                      SERIAL PRIMARY KEY,
    raw_id                  INTEGER REFERENCES transactions_raw(id) ON DELETE CASCADE,

    -- Identificación normalizada
    project_type            VARCHAR(50),            -- Categoría estandarizada
    id_role                 VARCHAR(50),

    -- Temporalidad
    inscription_date        DATE,
    year                    SMALLINT,
    quarter                 SMALLINT,

    -- Geografía validada
    county_name             VARCHAR(100),
    geom                    GEOMETRY(Point, 4326),

    -- Valores en UF (normalizados y validados)
    calculated_value_uf     NUMERIC(14, 4),
    real_value_uf           NUMERIC(14, 4),
    uf_value                NUMERIC(10, 4),

    -- Superficies (imputadas si es necesario)
    surface_m2              NUMERIC(10, 2),
    surface_building_m2     NUMERIC(10, 2),
    surface_land_m2         NUMERIC(10, 2),
    surface_imputed         BOOLEAN DEFAULT FALSE,  -- Si fue imputada

    -- Precios unitarios calculados
    uf_m2_building          NUMERIC(10, 4),
    uf_m2_land              NUMERIC(10, 4),

    -- Flags de calidad
    has_valid_coords        BOOLEAN DEFAULT TRUE,
    has_valid_price         BOOLEAN DEFAULT TRUE,
    has_surface             BOOLEAN DEFAULT TRUE,
    is_outlier              BOOLEAN DEFAULT FALSE,
    outlier_reason          TEXT,
    data_confidence         NUMERIC(4, 3),          -- 0.0 a 1.0

    cleaned_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tc_geom       ON transactions_clean USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_tc_county     ON transactions_clean(county_name);
CREATE INDEX IF NOT EXISTS idx_tc_type       ON transactions_clean(project_type);
CREATE INDEX IF NOT EXISTS idx_tc_date       ON transactions_clean(inscription_date);
CREATE INDEX IF NOT EXISTS idx_tc_confidence ON transactions_clean(data_confidence DESC);


-- ============================================================
-- TABLA: model_scores
-- Scores calculados por el modelo de oportunidad
-- Trazabilidad completa por versión de modelo
-- ============================================================
CREATE TABLE IF NOT EXISTS model_scores (
    id                      SERIAL PRIMARY KEY,
    clean_id                INTEGER REFERENCES transactions_clean(id) ON DELETE CASCADE,
    model_version           VARCHAR(20) NOT NULL,   -- ej: "v1.0", "v1.1"

    -- Scores (0.0 a 1.0, salvo indicación)
    undervaluation_score    NUMERIC(6, 4),          -- Qué tan subvalorado está (0=justo, 1=muy subvalorado)
    data_confidence         NUMERIC(4, 3),          -- Confianza en los datos subyacentes
    opportunity_score       NUMERIC(6, 4),          -- Score final compuesto

    -- Detalles del modelo hedónico
    predicted_uf_m2         NUMERIC(10, 4),         -- Precio predicho por modelo
    actual_uf_m2            NUMERIC(10, 4),         -- Precio real observado
    gap_pct                 NUMERIC(8, 4),          -- % brecha (negativo = subvalorado)
    gap_percentile          NUMERIC(5, 2),          -- Percentil de la brecha (0-100)

    -- Explicabilidad SHAP
    shap_top_features       JSONB,                  -- [{"feature": "county_name", "shap": -0.42, "direction": "down"}, ...]
    feature_importance      JSONB,                  -- Mapa completo de features para análisis

    scored_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ms_clean      ON model_scores(clean_id);
CREATE INDEX IF NOT EXISTS idx_ms_version    ON model_scores(model_version);
CREATE INDEX IF NOT EXISTS idx_ms_opp_score  ON model_scores(opportunity_score DESC);
CREATE INDEX IF NOT EXISTS idx_ms_gap        ON model_scores(gap_pct ASC);


-- ============================================================
-- TABLA: commune_stats
-- Estadísticas agregadas por comuna (se recalcula en batch)
-- ============================================================
CREATE TABLE IF NOT EXISTS commune_stats (
    id                      SERIAL PRIMARY KEY,
    county_name             VARCHAR(100) NOT NULL,
    project_type            VARCHAR(50) NOT NULL,
    model_version           VARCHAR(20) NOT NULL,
    year                    SMALLINT,
    quarter                 SMALLINT,

    -- Volumen
    n_transactions          INTEGER,
    n_scored                INTEGER,

    -- Precios
    median_uf_m2            NUMERIC(10, 4),
    p25_uf_m2               NUMERIC(10, 4),
    p75_uf_m2               NUMERIC(10, 4),
    std_uf_m2               NUMERIC(10, 4),

    -- Scores comunales
    median_opportunity_score NUMERIC(6, 4),
    pct_undervalued         NUMERIC(5, 2),          -- % de propiedades con gap_pct < -10%
    avg_data_confidence     NUMERIC(4, 3),

    computed_at             TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(county_name, project_type, model_version, year, quarter)
);

CREATE INDEX IF NOT EXISTS idx_cs_county     ON commune_stats(county_name);
CREATE INDEX IF NOT EXISTS idx_cs_score      ON commune_stats(median_opportunity_score DESC);


-- ============================================================
-- VISTA: v_opportunities
-- Vista rápida de oportunidades activas para el dashboard
-- ============================================================
CREATE OR REPLACE VIEW v_opportunities AS
SELECT
    ms.id                   AS score_id,
    tc.raw_id,
    tc.project_type,
    tc.county_name,
    tc.inscription_date,
    tc.year,
    tc.quarter,
    tc.real_value_uf,
    tc.calculated_value_uf,
    tc.surface_m2,
    tc.surface_building_m2,
    tc.surface_land_m2,
    tc.uf_m2_building,
    tc.uf_m2_land,
    ms.opportunity_score,
    ms.undervaluation_score,
    ms.gap_pct,
    ms.gap_percentile,
    ms.predicted_uf_m2,
    ms.data_confidence,
    ms.shap_top_features,
    ms.model_version,
    tc.geom,
    ST_X(tc.geom)           AS longitude,
    ST_Y(tc.geom)           AS latitude
FROM model_scores ms
JOIN transactions_clean tc ON tc.id = ms.clean_id
LEFT JOIN commune_calibration cc
       ON cc.model_version = ms.model_version
      AND cc.county_name   = tc.county_name
      AND cc.project_type  = tc.project_type
WHERE tc.is_outlier = FALSE
  AND tc.has_valid_coords = TRUE
  AND tc.has_valid_price = TRUE
  AND (
    (tc.project_type IN ('apartments','residential','retail') AND tc.uf_m2_building >= 10.0)
    OR (tc.project_type = 'land'    AND tc.uf_m2_building >= 2.0)
    OR (tc.project_type = 'unknown' AND tc.uf_m2_building >= 8.0)
  )
  AND ms.predicted_uf_m2 > 5.0
  AND ms.gap_pct > -0.85
  AND (tc.surface_building_m2 IS NULL OR tc.surface_building_m2 >= 25.0)
  AND (tc.project_type NOT IN ('apartments','residential') OR tc.real_value_uf < 80000);

COMMENT ON VIEW v_opportunities IS
  'Vista dashboard (2026-04-21): outliers + UF/m² floor + gap cap -85% + predicted>5 '
  '+ surface>=25m² + bulk commercial excl. + commune_calibration join. ~385k propiedades limpias.';
