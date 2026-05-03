-- Migration 015: Asset Subclass Weights
-- =====================================
-- Adds support for asset-subclass-specific scoring weights.
-- Each subclass (apartment_income, gas_station, etc.) has its own weight vector
-- across the 12 scoring dimensions produced by agents A1-A3.
--
-- See prompts/asset_subclass_weights_engine.md for full design rationale.

CREATE TABLE IF NOT EXISTS asset_subclass_weights (
  subclass             VARCHAR(50)    PRIMARY KEY,
  description          TEXT           NOT NULL,
  parent_class         VARCHAR(20)    NOT NULL,  -- 'residential', 'commercial', 'land'

  -- 12 dimension weights — must sum to 1.0 (validated by trigger)
  w_underval           NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_cap_rate           NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_appreciation       NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_transit            NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_school             NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_traffic            NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_competitor_density NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_demographic_match  NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_liquidity          NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_regulatory_risk    NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_environmental_risk NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_data_confidence    NUMERIC(4,3)   NOT NULL DEFAULT 0.0,

  active               BOOLEAN        NOT NULL DEFAULT TRUE,
  created_at           TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

  CONSTRAINT weights_sum_one CHECK (
    ABS(w_underval + w_cap_rate + w_appreciation + w_transit + w_school +
        w_traffic + w_competitor_density + w_demographic_match + w_liquidity +
        w_regulatory_risk + w_environmental_risk + w_data_confidence - 1.0) < 0.001
  ),

  CONSTRAINT parent_class_valid CHECK (
    parent_class IN ('residential', 'commercial', 'land')
  )
);

CREATE INDEX IF NOT EXISTS idx_subclass_active
  ON asset_subclass_weights (active)
  WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_subclass_parent
  ON asset_subclass_weights (parent_class)
  WHERE active = TRUE;

-- Trigger: auto-update timestamp
CREATE OR REPLACE FUNCTION update_subclass_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_subclass_update_ts ON asset_subclass_weights;
CREATE TRIGGER trg_subclass_update_ts
  BEFORE UPDATE ON asset_subclass_weights
  FOR EACH ROW
  EXECUTE FUNCTION update_subclass_timestamp();

-- ─────────────────────────────────────────────────────────────────────────────
-- Seed data: 14 subclases iniciales
-- Pesos derivados de master_plan_geltner.md y prácticas industria (Colliers/CBRE/JLL)
-- ─────────────────────────────────────────────────────────────────────────────

INSERT INTO asset_subclass_weights
  (subclass, description, parent_class,
   w_underval, w_cap_rate, w_appreciation, w_transit, w_school,
   w_traffic, w_competitor_density, w_demographic_match, w_liquidity,
   w_regulatory_risk, w_environmental_risk, w_data_confidence)
VALUES

  -- ═══ RESIDENTIAL ═══
  ('apartment_income',  'Departamento para arriendo (cap rate enfoque)',  'residential',
   0.20, 0.30, 0.05, 0.20, 0.10, 0.0,  0.0,  0.05, 0.05, 0.0,  0.0,  0.05),

  ('apartment_flip',    'Departamento para revender 3-5 años',           'residential',
   0.30, 0.0,  0.30, 0.10, 0.05, 0.0,  0.0,  0.05, 0.10, 0.0,  0.0,  0.10),

  ('house_income',      'Casa para arriendo familiar',                   'residential',
   0.20, 0.25, 0.10, 0.10, 0.20, 0.0,  0.0,  0.05, 0.05, 0.0,  0.0,  0.05),

  ('house_flip',        'Casa para refacción + revender',                'residential',
   0.35, 0.0,  0.30, 0.05, 0.10, 0.0,  0.0,  0.05, 0.10, 0.0,  0.0,  0.05),

  -- ═══ LAND ═══
  ('land_residential_dev', 'Terreno para desarrollo residencial',         'land',
   0.30, 0.0,  0.20, 0.10, 0.10, 0.0,  0.0,  0.05, 0.0,  0.15, 0.05, 0.05),

  ('land_commercial_dev',  'Terreno para desarrollo comercial',           'land',
   0.25, 0.0,  0.15, 0.0,  0.0,  0.20, 0.10, 0.10, 0.0,  0.10, 0.05, 0.05),

  -- ═══ COMMERCIAL OPERATIONAL ═══
  ('gas_station',       'Estación de servicio (operación)',               'commercial',
   0.10, 0.20, 0.05, 0.0,  0.0,  0.30, 0.20, 0.05, 0.0,  0.05, 0.0,  0.05),

  ('pharmacy',          'Farmacia (operación)',                           'commercial',
   0.10, 0.20, 0.05, 0.10, 0.0,  0.10, 0.20, 0.15, 0.0,  0.05, 0.0,  0.05),

  ('supermarket',       'Supermercado (operación)',                       'commercial',
   0.10, 0.20, 0.05, 0.10, 0.0,  0.15, 0.15, 0.15, 0.0,  0.05, 0.0,  0.05),

  ('bank_branch',       'Sucursal bancaria',                              'commercial',
   0.10, 0.20, 0.05, 0.15, 0.0,  0.05, 0.20, 0.15, 0.0,  0.05, 0.0,  0.05),

  ('clinic',            'Clínica / centro médico',                        'commercial',
   0.10, 0.20, 0.05, 0.15, 0.05, 0.05, 0.15, 0.15, 0.0,  0.05, 0.0,  0.05),

  ('restaurant',        'Local restaurant / café',                        'commercial',
   0.10, 0.15, 0.05, 0.10, 0.0,  0.20, 0.20, 0.10, 0.0,  0.05, 0.0,  0.05),

  ('office_class_a',    'Oficina clase A+ (zona prime)',                  'commercial',
   0.20, 0.25, 0.05, 0.20, 0.0,  0.05, 0.05, 0.05, 0.10, 0.0,  0.0,  0.05),

  ('warehouse',         'Bodega / industrial logístico',                  'commercial',
   0.20, 0.20, 0.10, 0.0,  0.0,  0.25, 0.05, 0.0,  0.10, 0.05, 0.0,  0.05)

ON CONFLICT (subclass) DO NOTHING;

-- View: solo subclases activas
CREATE OR REPLACE VIEW v_subclass_weights_active AS
  SELECT *
  FROM asset_subclass_weights
  WHERE active = TRUE
  ORDER BY parent_class, subclass;

COMMENT ON TABLE asset_subclass_weights IS
  'Pesos por subclase de activo. Cada subclase tiene un vector de 12 dimensiones que suma 1.0. '
  'Usado por src/scoring/asset_subclass.py para generar subclass_scores JSONB en model_scores.';
