-- Migration 008: GTFS bus stop proximity feature
ALTER TABLE transaction_features
  ADD COLUMN IF NOT EXISTS dist_gtfs_bus_km FLOAT;

CREATE INDEX IF NOT EXISTS idx_tf_dist_gtfs
  ON transaction_features (dist_gtfs_bus_km);

COMMENT ON COLUMN transaction_features.dist_gtfs_bus_km IS
  'Distance in km to nearest RED bus stop (from GTFS Santiago)';
