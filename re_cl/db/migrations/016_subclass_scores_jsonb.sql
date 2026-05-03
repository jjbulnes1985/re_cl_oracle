-- Migration 016: Subclass Scores JSONB column
-- ============================================
-- Adds a JSONB column to model_scores that stores per-subclass scores.
-- Schema: {"apartment_income": 0.78, "gas_station": 0.45, "pharmacy": 0.62, ...}
--
-- This is ADDITIVE — does NOT modify existing opportunity_score column.
-- Frontend can opt into using subclass_scores; legacy paths continue to work.

ALTER TABLE model_scores
  ADD COLUMN IF NOT EXISTS subclass_scores JSONB DEFAULT NULL;

-- GIN index for efficient queries like:
--   SELECT * FROM model_scores WHERE (subclass_scores->>'gas_station')::numeric > 0.7
CREATE INDEX IF NOT EXISTS idx_subclass_scores_gin
  ON model_scores
  USING GIN (subclass_scores);

-- Functional indexes for the most common subclass queries
-- (apartment_income is the most common query path: residential investors)
CREATE INDEX IF NOT EXISTS idx_score_apartment_income
  ON model_scores ((subclass_scores->>'apartment_income'))
  WHERE subclass_scores ? 'apartment_income';

CREATE INDEX IF NOT EXISTS idx_score_gas_station
  ON model_scores ((subclass_scores->>'gas_station'))
  WHERE subclass_scores ? 'gas_station';

COMMENT ON COLUMN model_scores.subclass_scores IS
  'JSONB map of asset subclass → opportunity score [0,1]. '
  'Populated by src/scoring/asset_subclass.py using weights from asset_subclass_weights table.';
