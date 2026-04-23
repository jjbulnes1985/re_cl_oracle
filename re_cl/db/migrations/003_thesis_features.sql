-- Migration 003: thesis features (V4.1)
-- Adds columns derived from Juan Montes MIT 2017 thesis on Chilean RE price indices.
-- Idempotent: uses ADD COLUMN IF NOT EXISTS (PostgreSQL 9.6+).

ALTER TABLE transaction_features
    ADD COLUMN IF NOT EXISTS age                      INTEGER,
    ADD COLUMN IF NOT EXISTS age_sq                   FLOAT,
    ADD COLUMN IF NOT EXISTS construction_year_bucket VARCHAR(20),
    ADD COLUMN IF NOT EXISTS city_zone                VARCHAR(20),
    ADD COLUMN IF NOT EXISTS log_surface              FLOAT;

COMMENT ON COLUMN transaction_features.age IS
    '2014 - construction_year; reference year = 2014 (CBR data vintage)';
COMMENT ON COLUMN transaction_features.age_sq IS
    'age squared — captures diminishing depreciation / vintage premium effect';
COMMENT ON COLUMN transaction_features.construction_year_bucket IS
    'Era bucket: pre_1960 | 1961_1970 | 1971_1980 | 1981_1990 | 1991_2000 | 2001_2006 | 2007_2016 | unknown';
COMMENT ON COLUMN transaction_features.city_zone IS
    'RM Santiago macrozone: centro_norte | este | sur | oeste | unknown';
COMMENT ON COLUMN transaction_features.log_surface IS
    'log(surface_m2 + 1) — thesis coeff=0.928, law of diminishing returns';

CREATE INDEX IF NOT EXISTS idx_tf_city_zone   ON transaction_features(city_zone);
CREATE INDEX IF NOT EXISTS idx_tf_cy_bucket   ON transaction_features(construction_year_bucket);
