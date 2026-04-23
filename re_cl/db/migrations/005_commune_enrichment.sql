-- Migration 005: Commune enrichment columns (INE Census 2017 + CEAD crime index)
-- V5.2 / V5.3 — RE_CL platform
--
-- Adds to commune_stats:
--   densidad_norm       NUMERIC(6,4)  — population density normalized (0–1, log-scaled)
--   educacion_score     NUMERIC(6,4)  — % higher education normalized (0–1)
--   hacinamiento_score  NUMERIC(6,4)  — overcrowding inverted (0=worst, 1=best)
--   crime_index         NUMERIC(6,4)  — CEAD crime index inverted (0=highest, 1=safest)
--   crime_tier          VARCHAR(10)   — alto / medio / bajo
--
-- Source estimates: INE Censo 2017 + CEAD Chile 2013-2016 reports (RM Santiago)
-- Safe to run multiple times (idempotent via IF NOT EXISTS / DO NOTHING).

-- ---------------------------------------------------------------------------
-- commune_stats enrichment columns
-- ---------------------------------------------------------------------------

ALTER TABLE commune_stats
    ADD COLUMN IF NOT EXISTS densidad_norm      NUMERIC(6,4) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS educacion_score    NUMERIC(6,4) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS hacinamiento_score NUMERIC(6,4) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS crime_index        NUMERIC(6,4) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS crime_tier         VARCHAR(10)  DEFAULT NULL;

COMMENT ON COLUMN commune_stats.densidad_norm      IS 'Population density per km2, log-scaled 0–1. Source: INE Censo 2017 estimates.';
COMMENT ON COLUMN commune_stats.educacion_score    IS '% population with higher education, normalized 0–1. Source: INE Censo 2017 estimates.';
COMMENT ON COLUMN commune_stats.hacinamiento_score IS 'Overcrowding index inverted: 1=best (low overcrowding), 0=worst. Source: INE Censo 2017 estimates.';
COMMENT ON COLUMN commune_stats.crime_index        IS 'CEAD crime index inverted: 1=safest, 0=highest crime. Source: CEAD Chile 2013-2016 estimates.';
COMMENT ON COLUMN commune_stats.crime_tier         IS 'Crime tier classification: alto / medio / bajo. Source: CEAD Chile estimates.';

-- ---------------------------------------------------------------------------
-- Seed enrichment values from static reference data
-- (run after Python pipeline has populated commune_stats via commune_ranking.py)
-- Update query uses a VALUES CTE to avoid a separate table dependency.
-- ---------------------------------------------------------------------------

WITH ine_data (county_name, densidad_norm, educacion_score, hacinamiento_score) AS (
    VALUES
    ('Las Condes',          0.8168, 0.7576, 0.8947),
    ('Vitacura',            0.8372, 1.0000, 1.0000),
    ('Lo Barnechea',        0.5393, 0.5152, 0.8421),
    ('La Reina',            0.8265, 0.7273, 0.8947),
    ('Providencia',         0.9444, 0.8182, 0.9474),
    ('Ñuñoa',               0.9564, 0.7273, 0.8947),
    ('Santiago',            0.9498, 0.4242, 0.6316),
    ('La Florida',          0.9241, 0.3636, 0.6842),
    ('Peñalolén',           0.8580, 0.2909, 0.5263),
    ('Maipú',               0.8683, 0.2909, 0.6316),
    ('Pudahuel',            0.8168, 0.1455, 0.3684),
    ('La Pintana',          0.9036, 0.0000, 0.0000),
    ('Puente Alto',         0.8831, 0.1818, 0.3158),
    ('Quilicura',           0.8476, 0.2182, 0.3684),
    ('San Bernardo',        0.8219, 0.1273, 0.3684),
    ('El Bosque',           0.9619, 0.0545, 0.2105),
    ('La Cisterna',         0.9845, 0.2727, 0.5789),
    ('San Miguel',          0.9712, 0.4242, 0.7368),
    ('Macul',               0.9381, 0.3939, 0.6842),
    ('Recoleta',            0.9759, 0.2909, 0.4211),
    ('Independencia',       0.9930, 0.3333, 0.5263),
    ('Conchalí',            0.9712, 0.1091, 0.2632),
    ('Huechuraba',          0.8067, 0.2424, 0.5263),
    ('Renca',               0.9332, 0.0727, 0.2105),
    ('Cerro Navia',         0.9498, 0.0182, 0.0000),
    ('Lo Prado',            0.9619, 0.0727, 0.2105),
    ('Quinta Normal',       0.9607, 0.1273, 0.3684),
    ('Estación Central',    0.9712, 0.2182, 0.4211),
    ('San Ramón',           0.9564, 0.0182, 0.1053),
    ('La Granja',           0.9498, 0.0364, 0.1579),
    ('Lo Espejo',           0.9845, 0.0000, 0.0000),
    ('Pedro Aguirre Cerda', 1.0000, 0.0545, 0.1053),
    ('Colina',              0.4362, 0.1818, 0.6316),
    ('Lampa',               0.3968, 0.1455, 0.5789)
),
crime_data (county_name, crime_index, crime_tier) AS (
    VALUES
    ('Vitacura',            0.92, 'bajo'),
    ('Las Condes',          0.82, 'bajo'),
    ('Lo Barnechea',        0.80, 'bajo'),
    ('La Reina',            0.83, 'bajo'),
    ('Providencia',         0.65, 'medio'),
    ('Ñuñoa',               0.72, 'medio'),
    ('Santiago',            0.42, 'alto'),
    ('La Florida',          0.68, 'medio'),
    ('Maipú',               0.65, 'medio'),
    ('Puente Alto',         0.58, 'medio'),
    ('San Bernardo',        0.52, 'medio'),
    ('Quilicura',           0.60, 'medio'),
    ('La Pintana',          0.28, 'alto'),
    ('El Bosque',           0.30, 'alto'),
    ('Cerro Navia',         0.32, 'alto'),
    ('Lo Espejo',           0.28, 'alto'),
    ('Pedro Aguirre Cerda', 0.30, 'alto'),
    ('San Ramón',           0.32, 'alto'),
    ('La Granja',           0.33, 'alto'),
    ('Renca',               0.38, 'alto'),
    ('Conchalí',            0.40, 'alto'),
    ('Peñalolén',           0.52, 'medio'),
    ('Recoleta',            0.45, 'alto'),
    ('Independencia',       0.50, 'medio'),
    ('Huechuraba',          0.55, 'medio'),
    ('Lo Prado',            0.40, 'alto'),
    ('Quinta Normal',       0.48, 'medio'),
    ('Estación Central',    0.45, 'alto'),
    ('La Cisterna',         0.55, 'medio'),
    ('San Miguel',          0.60, 'medio'),
    ('Macul',               0.60, 'medio'),
    ('Pudahuel',            0.45, 'alto'),
    ('Colina',              0.70, 'bajo'),
    ('Lampa',               0.68, 'bajo')
)
UPDATE commune_stats cs
SET
    densidad_norm      = i.densidad_norm,
    educacion_score    = i.educacion_score,
    hacinamiento_score = i.hacinamiento_score,
    crime_index        = c.crime_index,
    crime_tier         = c.crime_tier
FROM ine_data i
JOIN crime_data c ON i.county_name = c.county_name
WHERE cs.county_name = i.county_name;

-- ---------------------------------------------------------------------------
-- Index for crime_tier filtering (optional, used by API)
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_commune_stats_crime_tier
    ON commune_stats (crime_tier);

-- ---------------------------------------------------------------------------
-- Verify
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    updated_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO updated_count
    FROM commune_stats
    WHERE crime_index IS NOT NULL;

    RAISE NOTICE 'Migration 005 complete. commune_stats rows with crime_index: %', updated_count;
END $$;
