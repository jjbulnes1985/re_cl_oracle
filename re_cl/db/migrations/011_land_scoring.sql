-- =============================================================================
-- Migration 011: Land scoring view and classification
-- =============================================================================
-- Purpose: The CBR dataset has no explicit 'land' project_type — all potential
-- land transactions fall into 'unknown'. This migration:
--   1. Creates land_comparable_stats: commune-level land price benchmarks
--   2. Creates v_land_opportunities: identifies land-heavy transactions,
--      prices them using comparable-based pricing (not hedonic model),
--      and scores them by deviation from the commune land median.
-- =============================================================================

-- ── Land comparable stats (commune-level land price benchmarks) ──────────────
CREATE TABLE IF NOT EXISTS land_comparable_stats (
    id              SERIAL PRIMARY KEY,
    model_version   VARCHAR(20)  NOT NULL,
    county_name     VARCHAR(100) NOT NULL,
    year            INTEGER,
    n_records       INTEGER,
    median_uf_m2    NUMERIC(10, 4),
    p25_uf_m2       NUMERIC(10, 4),
    p75_uf_m2       NUMERIC(10, 4),
    std_uf_m2       NUMERIC(10, 4),
    computed_at     TIMESTAMP DEFAULT NOW(),
    UNIQUE (model_version, county_name, year)
);

CREATE INDEX IF NOT EXISTS idx_lcs_lookup
    ON land_comparable_stats (model_version, county_name, year);

-- Populate from 'unknown' records that are land-dominant
-- Land-dominant: large site, small or null building, and has uf_m2_land data
DELETE FROM land_comparable_stats WHERE model_version = 'v1.0';

INSERT INTO land_comparable_stats
    (model_version, county_name, year, n_records, median_uf_m2, p25_uf_m2, p75_uf_m2, std_uf_m2)
SELECT
    'v1.0'                 AS model_version,
    tc.county_name,
    tc.year,
    COUNT(*)               AS n_records,
    PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY tc.uf_m2_land) AS median_uf_m2,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY tc.uf_m2_land) AS p25_uf_m2,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY tc.uf_m2_land) AS p75_uf_m2,
    STDDEV(tc.uf_m2_land)  AS std_uf_m2
FROM transactions_clean tc
WHERE tc.is_outlier        = FALSE
  AND tc.has_valid_price   = TRUE
  AND tc.uf_m2_land        BETWEEN 1.0 AND 150.0  -- plausible land range for RM
  AND tc.surface_land_m2   >= 100                  -- meaningful plot size
  AND (
    -- Land-dominant: site area significantly larger than built area
    tc.surface_land_m2 > COALESCE(tc.surface_building_m2, 0) * 2
    OR tc.surface_building_m2 IS NULL
  )
GROUP BY tc.county_name, tc.year
HAVING COUNT(*) >= 10;

-- ── Land opportunities view ───────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_land_opportunities AS
WITH land_candidates AS (
    -- Identify land-dominant transactions from 'unknown' type
    SELECT
        tc.id             AS clean_id,
        tc.raw_id,
        tc.county_name,
        tc.year,
        tc.real_value_uf,
        tc.surface_land_m2,
        tc.surface_building_m2,
        tc.uf_m2_land,
        tc.uf_m2_building,
        tc.data_confidence,
        tc.geom,
        ST_X(tc.geom)     AS longitude,
        ST_Y(tc.geom)     AS latitude,
        -- Land dominance ratio: how much bigger the site is vs the building
        CASE
            WHEN tc.surface_building_m2 > 0
            THEN tc.surface_land_m2 / tc.surface_building_m2
            ELSE 10.0  -- null building → strongly land
        END               AS land_ratio
    FROM transactions_clean tc
    WHERE tc.is_outlier       = FALSE
      AND tc.has_valid_price  = TRUE
      AND tc.has_valid_coords = TRUE
      AND tc.uf_m2_land       BETWEEN 2.0 AND 150.0  -- raised from 1.0: sub-2 UF/m² are floor-clamped data errors
      AND tc.surface_land_m2  >= 100
      AND tc.latitude         IS NOT NULL
      AND (
        tc.surface_land_m2 > COALESCE(tc.surface_building_m2, 0) * 2
        OR tc.surface_building_m2 IS NULL
      )
),
land_scored AS (
    SELECT
        lc.*,
        lcs.median_uf_m2     AS commune_median_uf_m2,
        lcs.p25_uf_m2        AS commune_p25_uf_m2,
        lcs.p75_uf_m2        AS commune_p75_uf_m2,
        lcs.n_records        AS comparable_count,
        -- Gap vs commune median: negative = below median (potential opportunity)
        CASE WHEN lcs.median_uf_m2 > 0
             THEN (lc.uf_m2_land - lcs.median_uf_m2) / lcs.median_uf_m2
             ELSE NULL END    AS land_gap_pct,
        -- Land opportunity score: 0-1, higher = more undervalued vs commune median
        CASE WHEN lcs.median_uf_m2 > 0
             THEN GREATEST(0, LEAST(1,
                  0.5 - (lc.uf_m2_land - lcs.median_uf_m2) / (2 * NULLIF(lcs.median_uf_m2, 0))
             ))
             ELSE NULL END    AS land_opportunity_score
    FROM land_candidates lc
    LEFT JOIN land_comparable_stats lcs
           ON lcs.model_version = 'v1.0'
          AND lcs.county_name   = lc.county_name
          AND lcs.year          = lc.year
    WHERE lcs.median_uf_m2 IS NOT NULL  -- only score where we have comparables
)
SELECT *
FROM land_scored
WHERE land_opportunity_score >= 0.55  -- only surface genuine below-median land
ORDER BY land_opportunity_score DESC;

COMMENT ON VIEW v_land_opportunities IS
  'Land-dominant transactions scored vs commune comparable medians. '
  'Uses uf_m2_land as price metric + comparable-based pricing (not hedonic model). '
  'Sourced from unknown-type records with surface_land > 2× surface_building.';
