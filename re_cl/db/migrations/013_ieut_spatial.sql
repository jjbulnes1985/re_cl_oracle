-- Migration 013: ieut-inciti spatial features
-- 16 new distance-based features from local shapefiles (more precise than OSM API)

ALTER TABLE transaction_features
    -- Áreas verdes
    ADD COLUMN IF NOT EXISTS dist_green_area_km     FLOAT,

    -- Comercio
    ADD COLUMN IF NOT EXISTS dist_feria_km           FLOAT,
    ADD COLUMN IF NOT EXISTS dist_mall_local_km      FLOAT,
    ADD COLUMN IF NOT EXISTS n_commercial_blocks_500m INT,

    -- Conectividad
    ADD COLUMN IF NOT EXISTS dist_metro_local_km     FLOAT,
    ADD COLUMN IF NOT EXISTS dist_bus_local_km       FLOAT,
    ADD COLUMN IF NOT EXISTS dist_autopista_km       FLOAT,
    ADD COLUMN IF NOT EXISTS dist_ciclovia_km        FLOAT,

    -- Equipamiento
    ADD COLUMN IF NOT EXISTS dist_school_local_km    FLOAT,
    ADD COLUMN IF NOT EXISTS dist_jardines_km        FLOAT,
    ADD COLUMN IF NOT EXISTS dist_health_local_km    FLOAT,
    ADD COLUMN IF NOT EXISTS dist_cultural_km        FLOAT,
    ADD COLUMN IF NOT EXISTS dist_policia_km         FLOAT,

    -- NIMBYs (negative amenities — higher distance = better)
    ADD COLUMN IF NOT EXISTS dist_airport_km         FLOAT,
    ADD COLUMN IF NOT EXISTS dist_industrial_km      FLOAT,
    ADD COLUMN IF NOT EXISTS dist_vertedero_km       FLOAT,

    -- Tracking
    ADD COLUMN IF NOT EXISTS ieut_computed_at        TIMESTAMPTZ;

COMMENT ON COLUMN transaction_features.dist_green_area_km     IS 'Distance to nearest green area (Areas_Verdes_AMS.shp)';
COMMENT ON COLUMN transaction_features.dist_feria_km          IS 'Distance to nearest feria libre (Ferias_Libres_AMS.shp)';
COMMENT ON COLUMN transaction_features.dist_mall_local_km     IS 'Distance to nearest mall (Malls_AMS.shp)';
COMMENT ON COLUMN transaction_features.n_commercial_blocks_500m IS 'Count of commercial blocks within 500m (Manzanas_Comerciales_AMS.shp)';
COMMENT ON COLUMN transaction_features.dist_metro_local_km    IS 'Distance to nearest metro station (Estaciones_de_Metro_AMS.shp)';
COMMENT ON COLUMN transaction_features.dist_bus_local_km      IS 'Distance to nearest Transantiago stop (Paraderos_de_Transantiago_AMS.shp)';
COMMENT ON COLUMN transaction_features.dist_autopista_km      IS 'Distance to nearest highway (Autopistas_AMS.shp)';
COMMENT ON COLUMN transaction_features.dist_ciclovia_km       IS 'Distance to nearest bike lane (Ciclovias_AMS.shp)';
COMMENT ON COLUMN transaction_features.dist_school_local_km   IS 'Distance to nearest public school (Establecimientos_Educacionales_Publicos_AMS.shp)';
COMMENT ON COLUMN transaction_features.dist_jardines_km       IS 'Distance to nearest jardín infantil (Jardines_infantiles_AMS.shp)';
COMMENT ON COLUMN transaction_features.dist_health_local_km   IS 'Distance to nearest public health center (Centros_de_Salud_Publica_AMS.shp)';
COMMENT ON COLUMN transaction_features.dist_cultural_km       IS 'Distance to nearest cultural facility (Equipamiento_Cultural_AMS.shp)';
COMMENT ON COLUMN transaction_features.dist_policia_km        IS 'Distance to nearest police unit (Unidades_Policiales_AMS.shp)';
COMMENT ON COLUMN transaction_features.dist_airport_km        IS 'Distance to nearest airport — NIMBY (Aeropuertos_AMS.shp)';
COMMENT ON COLUMN transaction_features.dist_industrial_km     IS 'Distance to nearest industrial block — NIMBY (Manzanas_Industriales_AMS.shp)';
COMMENT ON COLUMN transaction_features.dist_vertedero_km      IS 'Distance to nearest waste dump — NIMBY (Vertederos_AMS.shp)';
