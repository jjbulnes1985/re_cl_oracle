-- Migration 002: scraped_listings table for V2 scraping module
-- Stores fresh listings from Portal Inmobiliario, Toctoc, etc.

CREATE TABLE IF NOT EXISTS scraped_listings (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(50)  NOT NULL,          -- 'portal_inmobiliario', 'toctoc', etc.
    external_id     VARCHAR(100) NOT NULL,           -- portal's own ID/slug
    url             TEXT,
    project_type    VARCHAR(50),                     -- apartments, residential, land, retail
    county_name     VARCHAR(100),
    address         TEXT,
    price_uf        NUMERIC(12, 2),
    surface_m2      NUMERIC(10, 2),
    uf_m2           NUMERIC(10, 4),                  -- price_uf / surface_m2
    bedrooms        SMALLINT,
    bathrooms       SMALLINT,
    latitude        NUMERIC(12, 8),
    longitude       NUMERIC(12, 8),
    geom            GEOMETRY(Point, 4326),
    description     TEXT,
    scraped_at      TIMESTAMPTZ DEFAULT NOW(),
    raw_json        TEXT,                            -- raw extracted JSON for debugging

    CONSTRAINT uq_scraped_source_id UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_scraped_geom    ON scraped_listings USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_scraped_county  ON scraped_listings(county_name);
CREATE INDEX IF NOT EXISTS idx_scraped_type    ON scraped_listings(project_type);
CREATE INDEX IF NOT EXISTS idx_scraped_source  ON scraped_listings(source);
CREATE INDEX IF NOT EXISTS idx_scraped_at      ON scraped_listings(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_scraped_uf_m2   ON scraped_listings(uf_m2);

-- Auto-populate geom from lat/lon on insert/update
CREATE OR REPLACE FUNCTION update_scraped_geom()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL THEN
        NEW.geom := ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_scraped_geom ON scraped_listings;
CREATE TRIGGER trg_scraped_geom
    BEFORE INSERT OR UPDATE OF latitude, longitude
    ON scraped_listings
    FOR EACH ROW
    EXECUTE FUNCTION update_scraped_geom();

-- Summary view: scraped listings with price stats by commune
CREATE OR REPLACE VIEW v_scraped_market AS
SELECT
    source,
    county_name,
    project_type,
    COUNT(*)                                AS n_listings,
    ROUND(MEDIAN(price_uf)::numeric, 0)     AS median_price_uf,
    ROUND(MEDIAN(uf_m2)::numeric, 2)        AS median_uf_m2,
    ROUND(AVG(uf_m2)::numeric, 2)           AS mean_uf_m2,
    ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY uf_m2)::numeric, 2) AS p25_uf_m2,
    ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY uf_m2)::numeric, 2) AS p75_uf_m2,
    MAX(scraped_at)                         AS last_scraped
FROM scraped_listings
WHERE uf_m2 > 0
  AND uf_m2 < 500          -- filter extreme outliers
  AND county_name IS NOT NULL
GROUP BY source, county_name, project_type;
