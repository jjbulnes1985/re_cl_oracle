-- Migration 004: OSM/GTFS proximity features
-- Adds OSM-derived columns to transaction_features table.
-- Idempotent: safe to re-run (uses ADD COLUMN IF NOT EXISTS).
--
-- Run after 001_transaction_features.sql:
--   psql -U re_cl_user -d re_cl -f db/migrations/004_osm_features.sql

-- ── OSM distance features ───────────────────────────────────────────────────
ALTER TABLE transaction_features
    ADD COLUMN IF NOT EXISTS dist_metro_km      NUMERIC(8, 4),   -- km to nearest Metro Santiago station
    ADD COLUMN IF NOT EXISTS dist_bus_stop_km   NUMERIC(8, 4),   -- km to nearest RED bus stop
    ADD COLUMN IF NOT EXISTS dist_school_km     NUMERIC(8, 4),   -- km to nearest school/colegio
    ADD COLUMN IF NOT EXISTS dist_hospital_km   NUMERIC(8, 4),   -- km to nearest hospital/clinic
    ADD COLUMN IF NOT EXISTS dist_park_km       NUMERIC(8, 4),   -- km to nearest park/plaza
    ADD COLUMN IF NOT EXISTS dist_mall_km       NUMERIC(8, 4),   -- km to nearest mall/supermarket
    ADD COLUMN IF NOT EXISTS amenities_500m     SMALLINT,        -- count of amenities within 500m
    ADD COLUMN IF NOT EXISTS amenities_1km      SMALLINT;        -- count of amenities within 1km

-- ── Indexes for map/filter queries ─────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_tf_dist_metro
    ON transaction_features(dist_metro_km ASC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_tf_amenities_500m
    ON transaction_features(amenities_500m DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_tf_amenities_1km
    ON transaction_features(amenities_1km DESC NULLS LAST);

-- ── Comments ────────────────────────────────────────────────────────────────
COMMENT ON COLUMN transaction_features.dist_metro_km IS
    'Distance in km to nearest Metro Santiago station. Source: hardcoded station list (Líneas 1-6). Computed by osm_features.py.';

COMMENT ON COLUMN transaction_features.dist_bus_stop_km IS
    'Distance in km to nearest RED bus stop or bus station. Source: OpenStreetMap Overpass API. Computed by osm_features.py.';

COMMENT ON COLUMN transaction_features.dist_school_km IS
    'Distance in km to nearest school, college or university. Source: OSM Overpass API. Computed by osm_features.py.';

COMMENT ON COLUMN transaction_features.dist_hospital_km IS
    'Distance in km to nearest hospital, clinic or doctors. Source: OSM Overpass API. Computed by osm_features.py.';

COMMENT ON COLUMN transaction_features.dist_park_km IS
    'Distance in km to nearest park, garden or playground. Source: OSM Overpass API. Computed by osm_features.py.';

COMMENT ON COLUMN transaction_features.dist_mall_km IS
    'Distance in km to nearest mall, supermarket or department store. Source: OSM Overpass API. Computed by osm_features.py.';

COMMENT ON COLUMN transaction_features.amenities_500m IS
    'Count of school + hospital + park + mall POIs within 500m radius. Source: OSM Overpass API. Computed by osm_features.py.';

COMMENT ON COLUMN transaction_features.amenities_1km IS
    'Count of school + hospital + park + mall POIs within 1km radius. Source: OSM Overpass API. Computed by osm_features.py.';
