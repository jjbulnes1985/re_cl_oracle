"""
ieut_spatial_features.py
------------------------
Compute distance-based spatial features from ieut-inciti shapefiles.
More precise than OSM API: local shapefiles with official RM geometry.

16 new features:
  Áreas verdes:  dist_green_area_km
  Comercio:      dist_feria_km, dist_mall_local_km, n_commercial_blocks_500m
  Conectividad:  dist_metro_local_km, dist_bus_local_km, dist_autopista_km, dist_ciclovia_km
  Equipamiento:  dist_school_local_km, dist_jardines_km, dist_health_local_km,
                 dist_cultural_km, dist_policia_km
  NIMBYs:        dist_airport_km, dist_industrial_km, dist_vertedero_km

Usage:
    py src/features/ieut_spatial_features.py
    py src/features/ieut_spatial_features.py --dry-run
    py src/features/ieut_spatial_features.py --batch-size 5000
"""

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# ── Paths ─────────────────────────────────────────────────────────────────────

IEUT_DATA_DIR = Path(
    os.getenv(
        "IEUT_DATA_DIR",
        r"C:\Users\jjbul\Dropbox\Documentos\Master\Post_llegada\ieut - inciti\Data"
    )
)

SHAPEFILE_PATHS = {
    # Áreas verdes
    "dist_green_area_km":     IEUT_DATA_DIR / "AREAS VERDES" / "Areas_Verdes_AMS.shp",

    # Comercio
    "dist_feria_km":          IEUT_DATA_DIR / "COMERCIO" / "Ferias_Libres_AMS.shp",
    "dist_mall_local_km":     IEUT_DATA_DIR / "COMERCIO" / "Malls_AMS.shp",
    "n_commercial_blocks_500m": IEUT_DATA_DIR / "COMERCIO" / "Manzanas_Comerciales_AMS.shp",

    # Conectividad
    "dist_metro_local_km":    IEUT_DATA_DIR / "CONECTIVIDAD" / "Estaciones_de_Metro_AMS.shp",
    "dist_bus_local_km":      IEUT_DATA_DIR / "CONECTIVIDAD" / "Paraderos_de_Transantiago_AMS.shp",
    "dist_autopista_km":      IEUT_DATA_DIR / "CONECTIVIDAD" / "Autopistas_AMS.shp",
    "dist_ciclovia_km":       IEUT_DATA_DIR / "CONECTIVIDAD" / "Ciclovias_AMS.shp",

    # Equipamiento
    "dist_school_local_km":   IEUT_DATA_DIR / "EQUIPAMIENTO" / "Establecimientos_Educacionales_Publicos_AMS.shp",
    "dist_jardines_km":       IEUT_DATA_DIR / "EQUIPAMIENTO" / "Jardines_infantiles_AMS.shp",
    "dist_health_local_km":   IEUT_DATA_DIR / "EQUIPAMIENTO" / "Centros_de_Salud_Publica_AMS.shp",
    "dist_cultural_km":       IEUT_DATA_DIR / "EQUIPAMIENTO" / "Equipamiento_Cultural_AMS.shp",
    "dist_policia_km":        IEUT_DATA_DIR / "EQUIPAMIENTO" / "Unidades_Policiales_AMS.shp",

    # NIMBYs
    "dist_airport_km":        IEUT_DATA_DIR / "NIMBYS" / "Aeropuertos_AMS.shp",
    "dist_industrial_km":     IEUT_DATA_DIR / "NIMBYS" / "Manzanas_Industriales_AMS.shp",
    "dist_vertedero_km":      IEUT_DATA_DIR / "NIMBYS" / "Vertederos_AMS.shp",
}

# Radius for count features (in km)
COUNT_RADIUS_KM = 0.5

# Distance features (min distance in km)
DIST_FEATURES = [k for k in SHAPEFILE_PATHS if k.startswith("dist_")]
COUNT_FEATURES = ["n_commercial_blocks_500m"]

EARTH_RADIUS_KM = 6371.0


def _build_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db   = os.getenv("POSTGRES_DB",   "re_cl")
    user = os.getenv("POSTGRES_USER", "re_cl_user")
    pwd  = os.getenv("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


# ── Geometry extraction ────────────────────────────────────────────────────────

def _get_layer_centroids(shp_path: Path) -> np.ndarray:
    """
    Load shapefile and return array of (lat, lon) centroids in WGS84.
    Handles Points, Lines, and Polygons.
    """
    try:
        import geopandas as gpd
    except ImportError:
        raise ImportError("geopandas required: pip install geopandas")

    gdf = gpd.read_file(shp_path)

    # Reproject to WGS84 if needed
    if gdf.crs is None:
        logger.warning(f"  No CRS for {shp_path.name} — assuming PSAD56 → reprojecting to WGS84")
        gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")

    # Get centroids (works for points, lines, polygons)
    centroids = gdf.geometry.centroid
    coords = np.column_stack([
        centroids.y.values,  # lat
        centroids.x.values,  # lon
    ])
    # Filter out invalid coordinates
    valid = (
        np.isfinite(coords[:, 0]) & np.isfinite(coords[:, 1]) &
        (coords[:, 0] != 0) & (coords[:, 1] != 0)
    )
    return coords[valid]


# ── BallTree-based distance computation ───────────────────────────────────────

def _build_ball_tree(coords_latlon: np.ndarray):
    """Build sklearn BallTree with haversine metric."""
    from sklearn.neighbors import BallTree
    coords_rad = np.radians(coords_latlon)
    return BallTree(coords_rad, metric="haversine")


def _min_dist_km(tree, query_latlon: np.ndarray) -> np.ndarray:
    """Compute minimum distance in km from each query point to nearest tree point."""
    query_rad = np.radians(query_latlon)
    dists, _ = tree.query(query_rad, k=1)
    return dists[:, 0] * EARTH_RADIUS_KM


def _count_within_radius(tree, query_latlon: np.ndarray, radius_km: float) -> np.ndarray:
    """Count tree points within radius_km of each query point."""
    query_rad = np.radians(query_latlon)
    radius_rad = radius_km / EARTH_RADIUS_KM
    counts = tree.query_radius(query_rad, r=radius_rad, count_only=True)
    return counts.astype(int)


# ── Main computation ──────────────────────────────────────────────────────────

class IeutSpatialFeatures:
    def __init__(self):
        self._trees: dict = {}       # feature_name → BallTree
        self._loaded: set = set()

    def _load_layer(self, feature_name: str) -> bool:
        if feature_name in self._loaded:
            return True
        shp_path = SHAPEFILE_PATHS[feature_name]
        if not shp_path.exists():
            logger.warning(f"  Shapefile not found: {shp_path}")
            return False
        try:
            t0 = time.time()
            coords = _get_layer_centroids(shp_path)
            tree = _build_ball_tree(coords)
            self._trees[feature_name] = tree
            self._loaded.add(feature_name)
            logger.info(f"  Loaded {shp_path.name}: {len(coords):,} points in {time.time()-t0:.1f}s")
            return True
        except Exception as e:
            logger.error(f"  Failed loading {shp_path.name}: {e}")
            return False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all ieut spatial features for rows in df.
        df must have 'Latitude' and 'Longitude' columns (WGS84 decimal degrees).
        Returns df with new feature columns added.
        """
        df = df.copy()

        # Only process rows with valid coordinates
        has_coords = (
            df["latitude"].notna() & df["longitude"].notna() &
            df["latitude"].between(-56, -17) &
            df["longitude"].between(-76, -65)
        )
        query_latlon = np.column_stack([
            df.loc[has_coords, "latitude"].values,
            df.loc[has_coords, "longitude"].values,
        ])

        n_valid = has_coords.sum()
        logger.info(f"  Computing ieut features for {n_valid:,}/{len(df):,} rows with valid coords")

        if n_valid == 0:
            for feat in list(DIST_FEATURES) + COUNT_FEATURES:
                df[feat] = np.nan
            return df

        # Distance features
        for feat in DIST_FEATURES:
            if not self._load_layer(feat):
                df[feat] = np.nan
                continue
            tree = self._trees[feat]
            dists = _min_dist_km(tree, query_latlon)
            df[feat] = np.nan
            df.loc[has_coords, feat] = dists.round(4)

        # Count features
        for feat in COUNT_FEATURES:
            feat_shp = feat  # same key as SHAPEFILE_PATHS
            if not self._load_layer(feat_shp):
                df[feat] = 0
                continue
            tree = self._trees[feat_shp]
            counts = _count_within_radius(tree, query_latlon, COUNT_RADIUS_KM)
            df[feat] = 0
            df.loc[has_coords, feat] = counts

        return df


def run(engine, batch_size: int = 10_000, dry_run: bool = False) -> None:
    t_start = time.time()
    logger.info("=" * 60)
    logger.info("IEUT SPATIAL FEATURES")
    logger.info(f"  Data dir: {IEUT_DATA_DIR}")
    logger.info("=" * 60)

    # Check which shapefiles exist
    missing = [k for k, p in SHAPEFILE_PATHS.items() if not p.exists()]
    found   = [k for k, p in SHAPEFILE_PATHS.items() if p.exists()]
    if missing:
        logger.warning(f"Missing shapefiles ({len(missing)}): {missing}")
    logger.info(f"Available layers: {len(found)}/{len(SHAPEFILE_PATHS)}")

    if not found:
        logger.error("No shapefiles found. Check IEUT_DATA_DIR env var.")
        return

    # Load transactions with coordinates that haven't been computed yet
    query = text("""
        SELECT tc.id, tc.latitude, tc.longitude
        FROM transactions_clean tc
        LEFT JOIN transaction_features tf ON tf.clean_id = tc.id
        WHERE tc.latitude IS NOT NULL
          AND tc.longitude IS NOT NULL
          AND (tf.ieut_computed_at IS NULL OR tf.id IS NULL)
        ORDER BY tc.id
    """)

    with engine.connect() as conn:
        total_pending = conn.execute(
            text('SELECT COUNT(*) FROM transactions_clean tc LEFT JOIN transaction_features tf ON tf.clean_id = tc.id WHERE tc.latitude IS NOT NULL AND tc.longitude IS NOT NULL AND (tf.ieut_computed_at IS NULL OR tf.id IS NULL)')
        ).scalar()

    logger.info(f"Pending: {total_pending:,} transactions need ieut features")

    if total_pending == 0:
        logger.info("All transactions already have ieut features. Nothing to do.")
        return

    featurizer = IeutSpatialFeatures()
    total_written = 0
    offset = 0

    batch_query = text("""
        SELECT tc.id, tc.latitude, tc.longitude
        FROM transactions_clean tc
        LEFT JOIN transaction_features tf ON tf.clean_id = tc.id
        WHERE tc.latitude IS NOT NULL
          AND tc.longitude IS NOT NULL
          AND (tf.ieut_computed_at IS NULL OR tf.id IS NULL)
        ORDER BY tc.id
        LIMIT :limit OFFSET :offset
    """)

    while offset < total_pending:
        logger.info(f"Batch {offset//batch_size + 1}: rows {offset:,}–{offset+batch_size:,}")

        with engine.connect() as conn:
            batch = pd.read_sql(batch_query, conn, params={"limit": batch_size, "offset": offset})

        if batch.empty:
            break

        batch = featurizer.compute(batch)

        if dry_run:
            logger.info(f"  [DRY RUN] Would update {len(batch):,} rows")
            offset += batch_size
            total_written += len(batch)
            continue

        # Upsert into transaction_features
        feat_cols = DIST_FEATURES + COUNT_FEATURES
        now = pd.Timestamp.utcnow()

        with engine.begin() as conn:
            for _, row in batch.iterrows():
                update_vals = {f: (None if pd.isna(row.get(f)) else float(row[f]))
                               for f in DIST_FEATURES}
                update_vals.update({f: int(row.get(f, 0)) for f in COUNT_FEATURES})
                update_vals["ieut_computed_at"] = now
                update_vals["clean_id"] = int(row["id"])

                set_clause = ", ".join(f'"{k}" = :{k}' for k in update_vals if k != "clean_id")
                conn.execute(text(f"""
                    UPDATE transaction_features
                    SET {set_clause}
                    WHERE clean_id = :clean_id
                """), update_vals)

        total_written += len(batch)
        elapsed = time.time() - t_start
        rate = total_written / max(elapsed, 1)
        eta = (total_pending - total_written) / max(rate, 1)
        logger.info(f"  Written: {total_written:,}/{total_pending:,} | rate={rate:.0f}/s | ETA={eta/60:.1f}min")

        offset += batch_size

    elapsed = time.time() - t_start
    logger.info("=" * 60)
    logger.info(f"IEUT SPATIAL FEATURES COMPLETE: {total_written:,} rows in {elapsed/60:.1f}min")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",    action="store_true")
    parser.add_argument("--batch-size", type=int, default=10_000)
    args = parser.parse_args()

    from sqlalchemy import create_engine as _ce
    engine = _ce(_build_db_url(), pool_pre_ping=True)
    run(engine, batch_size=args.batch_size, dry_run=args.dry_run)
