-- Migration 012: CBR 2017-2018 data source tagging
-- Adds data_source column to transactions_raw for tracking origin of each record

ALTER TABLE transactions_raw
    ADD COLUMN IF NOT EXISTS data_source VARCHAR(50) DEFAULT 'cbr_v1';

-- Index for filtering by source
CREATE INDEX IF NOT EXISTS idx_transactions_raw_data_source
    ON transactions_raw (data_source);

COMMENT ON COLUMN transactions_raw.data_source IS
    'Origin dataset: cbr_v1 (original 2008-2016 CSV), cbr_2018 (transacciones27062018), cbr_actualizacion_2018 (191118 update)';
