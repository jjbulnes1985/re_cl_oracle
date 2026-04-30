-- Migration 014: Opportunity Engine v2
-- Universal property opportunity detection (residential/commercial/industrial/land)
-- Commercial use cases (gas_station, pharmacy, etc.) are overlays, not restrictions

CREATE SCHEMA IF NOT EXISTS opportunity;

-- ── Property Types Catalog ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS opportunity.property_types (
    code                    VARCHAR(50) PRIMARY KEY,
    name                    VARCHAR(100) NOT NULL,
    category                VARCHAR(20)  NOT NULL,  -- residential|commercial|industrial|land|mixed
    is_use_case             BOOLEAN DEFAULT FALSE,
    requires_zoning         JSONB,
    min_surface_land_m2     INT,
    typical_capex_uf_per_m2 NUMERIC(10,2),
    typical_cap_rate_low    NUMERIC(5,4),
    typical_cap_rate_mid    NUMERIC(5,4),
    typical_cap_rate_high   NUMERIC(5,4),
    notes                   TEXT
);

INSERT INTO opportunity.property_types VALUES
  ('apartment',   'Departamento',           'residential', FALSE, NULL, NULL,  NULL,   NULL,  NULL,  NULL,  NULL),
  ('house',       'Casa',                   'residential', FALSE, NULL, NULL,  NULL,   NULL,  NULL,  NULL,  NULL),
  ('land',        'Terreno generico',       'land',        FALSE, NULL, NULL,  NULL,   NULL,  NULL,  NULL,  NULL),
  ('retail',      'Local comercial',        'commercial',  FALSE, NULL, NULL,  NULL,   0.060, 0.075, 0.090, NULL),
  ('office',      'Oficina',                'commercial',  FALSE, NULL, NULL,  NULL,   0.054, 0.058, 0.065, 'Colliers LATAM Q2-2019'),
  ('warehouse',   'Bodega',                 'industrial',  FALSE, NULL, NULL,  NULL,   0.058, 0.062, 0.070, 'Colliers LATAM Q2-2019'),
  ('industrial',  'Industrial pesado',      'industrial',  FALSE, NULL, NULL,  NULL,   0.075, 0.085, 0.100, NULL),
  ('gas_station', 'Estacion de servicio',   'commercial',  TRUE,  '{"permitted_uses":["comercial","equipamiento"]}', 500,  35000, 0.070, 0.080, 0.095, 'INFO_NO_FIDEDIGNA::proxy USA net lease + spread Chile. B+E Q4-2024. Banda +/-150bps'),
  ('pharmacy',    'Farmacia',               'commercial',  TRUE,  '{"permitted_uses":["comercial"]}',                80,   12000, 0.065, 0.075, 0.090, 'INFO_NO_FIDEDIGNA::pendiente_validacion'),
  ('supermarket', 'Supermercado',           'commercial',  TRUE,  '{"permitted_uses":["comercial"]}',               1500,  18000, 0.060, 0.072, 0.085, 'INFO_NO_FIDEDIGNA::pendiente_validacion'),
  ('bank_branch', 'Sucursal bancaria',      'commercial',  TRUE,  '{"permitted_uses":["comercial"]}',                100,  10000, 0.055, 0.065, 0.080, 'INFO_NO_FIDEDIGNA::pendiente_validacion'),
  ('clinic',      'Clinica centro medico',  'commercial',  TRUE,  '{"permitted_uses":["equipamiento"]}',             200,  20000, 0.065, 0.075, 0.090, 'INFO_NO_FIDEDIGNA::pendiente_validacion'),
  ('restaurant',  'Restaurante',            'commercial',  TRUE,  '{"permitted_uses":["comercial"]}',                100,  15000, 0.070, 0.085, 0.100, 'INFO_NO_FIDEDIGNA::pendiente_validacion')
ON CONFLICT (code) DO NOTHING;

-- ── Investor Profiles ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS opportunity.investor_profiles (
    code        VARCHAR(50) PRIMARY KEY,
    name        VARCHAR(100),
    description TEXT,
    weights     JSONB
);

INSERT INTO opportunity.investor_profiles VALUES
  ('value',         'Valor (descuento puro)',         'Descuento vs valor justo',
   '{"undervaluation":0.65,"confidence":0.20,"location":0.15}'),
  ('growth',        'Crecimiento comunal',            'Plusvalia por dinamica zonal',
   '{"undervaluation":0.40,"growth":0.40,"confidence":0.20}'),
  ('income',        'Renta (yield)',                  'NOI proyectado',
   '{"undervaluation":0.30,"yield":0.50,"confidence":0.20}'),
  ('redevelopment', 'Redesarrollo (cambio de uso)',   'Subutilizacion + zonificacion favorable',
   '{"undervaluation":0.30,"redevelopment_potential":0.50,"confidence":0.20}'),
  ('flipper',       'Reventa rapida (12-24 meses)',   'Liquidez + descuento',
   '{"undervaluation":0.50,"liquidity":0.30,"confidence":0.20}'),
  ('operator',      'Operador comercial (uso final)', 'Score especifico por uso',
   '{"use_specific":0.60,"undervaluation":0.25,"confidence":0.15}')
ON CONFLICT (code) DO NOTHING;

-- ── Candidates ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS opportunity.candidates (
    id                      BIGSERIAL PRIMARY KEY,
    source                  VARCHAR(30)  NOT NULL,  -- cbr_transaction|scraped_listing|catastro_sii|satellite
    source_id               VARCHAR(100),
    detected_at             TIMESTAMPTZ  DEFAULT NOW(),

    -- Identification
    rol_sii                 VARCHAR(50),
    address                 TEXT,
    county_name             VARCHAR(100),
    latitude                DOUBLE PRECISION,
    longitude               DOUBLE PRECISION,
    geom                    geometry(Point, 4326),

    -- Physical
    property_type_code      VARCHAR(50) REFERENCES opportunity.property_types(code),
    surface_land_m2         NUMERIC(12,2),
    surface_building_m2     NUMERIC(12,2),
    construction_year       INT,

    -- Market state
    last_transaction_uf     NUMERIC(15,2),
    last_transaction_date   DATE,
    listed_price_uf         NUMERIC(15,2),
    listed_at               TIMESTAMPTZ,
    avaluo_fiscal_uf        NUMERIC(15,2),
    avaluo_to_market_ratio  NUMERIC(5,4),

    -- Underutilization signals
    construction_ratio      NUMERIC(5,4),
    is_eriazo               BOOLEAN      DEFAULT FALSE,
    is_below_zoning_density BOOLEAN      DEFAULT FALSE,
    zoning_max_far          NUMERIC(5,2),
    zoning_realized_far     NUMERIC(5,2),

    UNIQUE(source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_opp_candidates_geom   ON opportunity.candidates USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_opp_candidates_county ON opportunity.candidates(county_name);
CREATE INDEX IF NOT EXISTS idx_opp_candidates_type   ON opportunity.candidates(property_type_code);
CREATE INDEX IF NOT EXISTS idx_opp_candidates_eriazo ON opportunity.candidates(is_eriazo) WHERE is_eriazo = TRUE;
CREATE INDEX IF NOT EXISTS idx_opp_candidates_score  ON opportunity.candidates(county_name, property_type_code);

-- ── Valuations ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS opportunity.valuations (
    id              BIGSERIAL PRIMARY KEY,
    candidate_id    BIGINT       NOT NULL REFERENCES opportunity.candidates(id) ON DELETE CASCADE,
    method          VARCHAR(30)  NOT NULL,  -- hedonic_xgb|comparables|dcf|cap_inverse|cap_inverse_low|cap_inverse_high|triangulated
    model_version   VARCHAR(20)  NOT NULL,
    valued_at       TIMESTAMPTZ  DEFAULT NOW(),

    estimated_uf    NUMERIC(15,2),
    estimated_uf_m2 NUMERIC(12,4),
    p25_uf          NUMERIC(15,2),
    p50_uf          NUMERIC(15,2),
    p75_uf          NUMERIC(15,2),
    confidence      NUMERIC(3,2),

    inputs          JSONB,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_opp_valuations_candidate ON opportunity.valuations(candidate_id);
CREATE INDEX IF NOT EXISTS idx_opp_valuations_method    ON opportunity.valuations(method);

-- ── Scores ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS opportunity.scores (
    id                   BIGSERIAL PRIMARY KEY,
    candidate_id         BIGINT      NOT NULL REFERENCES opportunity.candidates(id) ON DELETE CASCADE,
    use_case             VARCHAR(50) NOT NULL DEFAULT 'as_is',
    investor_profile     VARCHAR(50) REFERENCES opportunity.investor_profiles(code),
    model_version        VARCHAR(20),
    scored_at            TIMESTAMPTZ DEFAULT NOW(),

    -- Score components (all 0-1)
    undervaluation_score NUMERIC(5,4),
    location_score       NUMERIC(5,4),
    growth_score         NUMERIC(5,4),
    yield_score          NUMERIC(5,4),
    redevelopment_score  NUMERIC(5,4),
    liquidity_score      NUMERIC(5,4),
    use_specific_score   NUMERIC(5,4),
    confidence           NUMERIC(5,4),

    -- Output
    opportunity_score    NUMERIC(5,4),
    max_payable_uf       NUMERIC(15,2),

    drivers              JSONB,
    risk_summary         JSONB,

    UNIQUE(candidate_id, use_case, investor_profile, model_version)
);

CREATE INDEX IF NOT EXISTS idx_opp_scores_candidate ON opportunity.scores(candidate_id);
CREATE INDEX IF NOT EXISTS idx_opp_scores_score     ON opportunity.scores(opportunity_score DESC);
CREATE INDEX IF NOT EXISTS idx_opp_scores_use       ON opportunity.scores(use_case);
CREATE INDEX IF NOT EXISTS idx_opp_scores_county    ON opportunity.scores(candidate_id) INCLUDE (opportunity_score, use_case);

-- ── Risks ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS opportunity.risks (
    id              BIGSERIAL PRIMARY KEY,
    candidate_id    BIGINT      NOT NULL REFERENCES opportunity.candidates(id) ON DELETE CASCADE,
    category        VARCHAR(30),  -- regulatory|demand|competition|liquidity|model|environmental|legal
    severity        VARCHAR(20),  -- low|medium|high|critical
    description     TEXT,
    flagged_at      TIMESTAMPTZ DEFAULT NOW(),
    source_agent    VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_opp_risks_candidate ON opportunity.risks(candidate_id);
CREATE INDEX IF NOT EXISTS idx_opp_risks_severity  ON opportunity.risks(severity);

-- ── Competitors ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS opportunity.competitors (
    id                  BIGSERIAL PRIMARY KEY,
    use_case            VARCHAR(50),
    operator            VARCHAR(100),
    name                VARCHAR(200),
    address             TEXT,
    county_name         VARCHAR(100),
    latitude            DOUBLE PRECISION,
    longitude           DOUBLE PRECISION,
    geom                geometry(Point, 4326),
    operational_status  VARCHAR(20) DEFAULT 'active',
    source              VARCHAR(50),
    source_id           VARCHAR(100),
    fetched_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_opp_competitors_geom   ON opportunity.competitors USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_opp_competitors_use    ON opportunity.competitors(use_case);
CREATE INDEX IF NOT EXISTS idx_opp_competitors_county ON opportunity.competitors(county_name);

-- ── Model Versions Changelog ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS opportunity.model_versions (
    version            VARCHAR(20) PRIMARY KEY,
    model_type         VARCHAR(50),
    trained_at         TIMESTAMPTZ,
    n_train            INT,
    n_test             INT,
    metrics            JSONB,
    feature_importance JSONB,
    notes              TEXT
);

-- ── Unified View for Frontend ─────────────────────────────────────────
CREATE OR REPLACE VIEW opportunity.v_top_opportunities AS
SELECT
    c.id,
    c.address,
    c.county_name,
    c.latitude,
    c.longitude,
    c.property_type_code,
    c.surface_land_m2,
    c.surface_building_m2,
    c.is_eriazo,
    c.construction_ratio,
    c.last_transaction_uf,
    c.last_transaction_date,
    c.listed_price_uf,
    c.rol_sii,
    s.use_case,
    s.investor_profile,
    s.opportunity_score,
    s.undervaluation_score,
    s.location_score,
    s.use_specific_score,
    s.max_payable_uf,
    s.drivers,
    s.risk_summary,
    v.estimated_uf,
    v.p25_uf,
    v.p50_uf,
    v.p75_uf,
    v.confidence AS valuation_confidence,
    s.scored_at
FROM opportunity.candidates c
JOIN opportunity.scores s ON s.candidate_id = c.id
LEFT JOIN opportunity.valuations v
    ON v.candidate_id = c.id AND v.method = 'triangulated'
WHERE s.opportunity_score >= 0.5
ORDER BY s.opportunity_score DESC;

-- Seed initial model version record
INSERT INTO opportunity.model_versions VALUES
  ('v1.0', 'valuation_hedonic', NOW(), NULL, NULL,
   '{"r2": 0.685, "rmse_pct": 39.91, "note": "XGBoost hedonic, trained on 519920 transactions"}',
   NULL,
   'Base model inherited from main RE_CL pipeline (hedonic_model_v1.pkl)')
ON CONFLICT (version) DO NOTHING;
