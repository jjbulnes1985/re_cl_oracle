-- RE_CL Migration 007: Spatial indexes and performance indexes
-- Run after data is loaded

-- Spatial index on transactions_clean geometry (PostGIS GiST)
CREATE INDEX IF NOT EXISTS idx_transactions_clean_geom
    ON transactions_clean USING GIST (geom);

-- Regular B-tree indexes for common filter patterns
CREATE INDEX IF NOT EXISTS idx_transactions_clean_county_type
    ON transactions_clean (county_name, project_type);

CREATE INDEX IF NOT EXISTS idx_transactions_clean_year_quarter
    ON transactions_clean (year, quarter);

CREATE INDEX IF NOT EXISTS idx_transactions_clean_price
    ON transactions_clean (uf_m2_building)
    WHERE uf_m2_building IS NOT NULL AND is_outlier = FALSE;

-- model_scores indexes
CREATE INDEX IF NOT EXISTS idx_model_scores_opportunity
    ON model_scores (opportunity_score DESC)
    WHERE opportunity_score IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_model_scores_clean_id
    ON model_scores (clean_id);

CREATE INDEX IF NOT EXISTS idx_model_scores_version_score
    ON model_scores (model_version, opportunity_score DESC);

-- transaction_features indexes
CREATE INDEX IF NOT EXISTS idx_tf_clean_id
    ON transaction_features (clean_id);

CREATE INDEX IF NOT EXISTS idx_tf_dist_metro
    ON transaction_features (dist_metro_km ASC NULLS LAST)
    WHERE dist_metro_km IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tf_city_zone
    ON transaction_features (city_zone)
    WHERE city_zone IS NOT NULL;

-- scraped_listings spatial index
CREATE INDEX IF NOT EXISTS idx_scraped_listings_location
    ON scraped_listings (latitude, longitude)
    WHERE latitude IS NOT NULL;

-- ANALYZE to update statistics after index creation
ANALYZE transactions_clean;
ANALYZE model_scores;
ANALYZE transaction_features;
