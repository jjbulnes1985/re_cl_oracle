-- =============================================================================
-- Migration 010: Commune-level bias correction table
-- =============================================================================
-- Purpose: Post-hoc calibration of the global XGBoost hedonic model.
-- The single global model underpredicts premium communes (LC, Vitacura,
-- Providencia) by 20-40% and slightly overpredicts some mid-tier communes.
-- This table stores median residuals per (county_name, project_type) so
-- calibrated_predicted = predicted + median_residual, giving commune-specific
-- price estimates without retraining the model.
-- =============================================================================

CREATE TABLE IF NOT EXISTS commune_calibration (
    id              SERIAL PRIMARY KEY,
    model_version   VARCHAR(20)    NOT NULL,
    county_name     VARCHAR(100)   NOT NULL,
    project_type    VARCHAR(50)    NOT NULL,
    n_records       INTEGER,
    median_residual NUMERIC(10, 4),  -- actual_uf_m2 - predicted_uf_m2 (positive = underprediction)
    mean_residual   NUMERIC(10, 4),
    std_residual    NUMERIC(10, 4),
    p25_residual    NUMERIC(10, 4),
    p75_residual    NUMERIC(10, 4),
    pct_error       NUMERIC(8, 4),  -- median_residual / median_predicted × 100
    computed_at     TIMESTAMP DEFAULT NOW(),
    UNIQUE (model_version, county_name, project_type)
);

CREATE INDEX IF NOT EXISTS idx_cc_lookup
    ON commune_calibration (model_version, county_name, project_type);

-- Populate from existing model_scores (idempotent: delete + reinsert)
DELETE FROM commune_calibration WHERE model_version = 'v1.0';

INSERT INTO commune_calibration
    (model_version, county_name, project_type, n_records,
     median_residual, mean_residual, std_residual, p25_residual, p75_residual, pct_error)
SELECT
    ms.model_version,
    tc.county_name,
    tc.project_type,
    COUNT(*)                                                                           AS n_records,
    PERCENTILE_CONT(0.5)   WITHIN GROUP (ORDER BY tc.uf_m2_building - ms.predicted_uf_m2) AS median_residual,
    AVG(tc.uf_m2_building - ms.predicted_uf_m2)                                       AS mean_residual,
    STDDEV(tc.uf_m2_building - ms.predicted_uf_m2)                                    AS std_residual,
    PERCENTILE_CONT(0.25)  WITHIN GROUP (ORDER BY tc.uf_m2_building - ms.predicted_uf_m2) AS p25_residual,
    PERCENTILE_CONT(0.75)  WITHIN GROUP (ORDER BY tc.uf_m2_building - ms.predicted_uf_m2) AS p75_residual,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY tc.uf_m2_building - ms.predicted_uf_m2)
        / NULLIF(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ms.predicted_uf_m2), 0) * 100,
    2)                                                                                 AS pct_error
FROM model_scores ms
JOIN transactions_clean tc ON tc.id = ms.clean_id
WHERE ms.model_version    = 'v1.0'
  AND tc.is_outlier       = FALSE
  AND tc.has_valid_price  = TRUE
  AND ms.predicted_uf_m2  > 5.0
  AND ms.gap_pct          > -0.85
  AND tc.uf_m2_building   >= 10.0
  AND (tc.surface_building_m2 IS NULL OR tc.surface_building_m2 >= 25.0)
GROUP BY ms.model_version, tc.county_name, tc.project_type
HAVING COUNT(*) >= 20;  -- min 20 records for a stable estimate

COMMENT ON TABLE commune_calibration IS
  'Median residuals (actual - predicted UF/m²) per (model_version, county_name, project_type). '
  'Used to calibrate v_opportunities.calibrated_predicted_uf_m2 and calibrated_gap_pct. '
  'Refresh by re-running this migration after each model retraining.';
