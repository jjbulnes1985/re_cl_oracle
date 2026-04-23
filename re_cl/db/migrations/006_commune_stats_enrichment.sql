-- Migration 006: Commune stats enrichment — safety net / idempotent guard
-- RE_CL platform — V4.3 INE Census + CEAD crime integration
--
-- Context:
--   Migration 005 already added crime_index, crime_tier, densidad_norm,
--   educacion_score, hacinamiento_score to commune_stats.
--   This migration is a safe no-op that guarantees those columns exist
--   regardless of whether 005 was applied (e.g. fresh installs that skip 005).
--
-- Safe to run multiple times (all statements use IF NOT EXISTS).

-- ---------------------------------------------------------------------------
-- Ensure enrichment columns exist on commune_stats
-- ---------------------------------------------------------------------------

ALTER TABLE commune_stats
    ADD COLUMN IF NOT EXISTS crime_index        FLOAT,
    ADD COLUMN IF NOT EXISTS crime_tier         VARCHAR(10),
    ADD COLUMN IF NOT EXISTS densidad_norm      FLOAT,
    ADD COLUMN IF NOT EXISTS educacion_score    FLOAT,
    ADD COLUMN IF NOT EXISTS hacinamiento_score FLOAT;

-- ---------------------------------------------------------------------------
-- Index for crime_tier filtering (idempotent)
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_commune_stats_crime_tier
    ON commune_stats (crime_tier);

-- ---------------------------------------------------------------------------
-- Verify
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    col_count INTEGER;
BEGIN
    SELECT COUNT(*)
    INTO col_count
    FROM information_schema.columns
    WHERE table_name = 'commune_stats'
      AND column_name IN ('crime_index', 'crime_tier', 'densidad_norm',
                          'educacion_score', 'hacinamiento_score');

    IF col_count < 5 THEN
        RAISE WARNING 'Migration 006: expected 5 enrichment columns, found %', col_count;
    ELSE
        RAISE NOTICE 'Migration 006 complete. All % enrichment columns present on commune_stats.', col_count;
    END IF;
END $$;
