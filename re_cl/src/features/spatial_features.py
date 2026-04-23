"""
spatial_features.py
-------------------
Computes spatial features using GeoPandas + scikit-learn:
  - dist_km_centroid: distance in km from each property to its commune centroid
  - cluster_id: DBSCAN spatial cluster label (subsample + BallTree propagation)

CRS: EPSG:32719 (WGS 84 / UTM zone 19S) — correct for Santiago / RM.
"""

import os

import geopandas as gpd
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from shapely.geometry import Point
from sklearn.cluster import DBSCAN
from sklearn.neighbors import BallTree
from sqlalchemy import create_engine

load_dotenv()

# ── Constants ──────────────────────────────────────────────────────────────────
CRS_LATLON  = "EPSG:4326"
CRS_METRIC  = "EPSG:32719"   # UTM 19S — covers Santiago / RM exactly

DBSCAN_EPS_KM   = 0.5        # neighbourhood radius in km
DBSCAN_MIN_SAMP = 10         # minimum points per cluster
DBSCAN_SUBSAMPLE = 50_000    # max points for DBSCAN (memory guard)
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


def compute_centroid_distance(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds dist_km_centroid column: distance in km from each property to its commune centroid.

    - Only rows with has_valid_coords == True (or latitude/longitude not null) are computed.
    - Commune centroid = mean of all valid lat/lon points in that commune.
    - Projection: EPSG:32719 before distance computation.
    - Rows without coords get dist_km_centroid = NaN.
    """
    df = df.copy()
    df["dist_km_centroid"] = np.nan

    # Filter to valid coordinates
    has_coords = df["latitude"].notna() & df["longitude"].notna()
    if "has_valid_coords" in df.columns:
        has_coords = has_coords & df["has_valid_coords"].astype(bool)

    valid = df[has_coords].copy()
    if valid.empty:
        logger.warning("No rows with valid coordinates — dist_km_centroid all NaN")
        return df

    # Build GeoDataFrame
    geometry = [Point(lon, lat) for lon, lat in zip(valid["longitude"], valid["latitude"])]
    gdf = gpd.GeoDataFrame(valid[["id", "county_name"]], geometry=geometry, crs=CRS_LATLON)
    gdf = gdf.to_crs(CRS_METRIC)

    # Commune centroids (mean of projected coordinates)
    gdf["x"] = gdf.geometry.x
    gdf["y"] = gdf.geometry.y
    centroids = gdf.groupby("county_name")[["x", "y"]].mean().rename(
        columns={"x": "cx", "y": "cy"}
    )
    gdf = gdf.join(centroids, on="county_name")

    # Distance in metres → km
    gdf["dist_km_centroid"] = np.sqrt(
        (gdf["x"] - gdf["cx"]) ** 2 + (gdf["y"] - gdf["cy"]) ** 2
    ) / 1000.0

    # Merge back by original index
    dist_map = gdf.set_index(valid.index)["dist_km_centroid"]
    df.loc[has_coords, "dist_km_centroid"] = dist_map.values

    logger.info(
        f"dist_km_centroid: {has_coords.sum():,} rows computed, "
        f"median {df['dist_km_centroid'].median():.2f} km"
    )
    return df


def compute_dbscan_clusters(
    df: pd.DataFrame,
    min_clusters: int = 5,
    eps_km: float = DBSCAN_EPS_KM,
    min_samples: int = DBSCAN_MIN_SAMP,
) -> pd.DataFrame:
    """
    Adds cluster_id column using DBSCAN with haversine metric.

    Strategy for large datasets (> DBSCAN_SUBSAMPLE rows):
      1. Subsample up to DBSCAN_SUBSAMPLE points with valid coords
      2. Run DBSCAN on subsample (haversine, eps in radians)
      3. Propagate cluster labels to all points via BallTree nearest neighbour

    cluster_id == -1 means noise (not assigned to any cluster).

    Args:
        min_clusters: minimum number of clusters expected (assertion). Use 1 for tests.
        eps_km: neighbourhood radius in km (override for tests with sparse data).
        min_samples: minimum points per cluster (override for tests).
    """
    df = df.copy()
    df["cluster_id"] = -1

    has_coords = df["latitude"].notna() & df["longitude"].notna()
    if "has_valid_coords" in df.columns:
        has_coords = has_coords & df["has_valid_coords"].astype(bool)

    valid_idx = df.index[has_coords]
    valid     = df.loc[valid_idx, ["latitude", "longitude"]].copy()

    if len(valid) < min_samples:
        logger.warning(f"Only {len(valid)} valid points — skipping DBSCAN")
        return df

    coords_rad = np.radians(valid[["latitude", "longitude"]].values)
    eps_rad    = eps_km / EARTH_RADIUS_KM

    # Subsample if needed
    if len(valid) > DBSCAN_SUBSAMPLE:
        logger.info(f"Subsampling {len(valid):,} → {DBSCAN_SUBSAMPLE:,} points for DBSCAN")
        sample_idx = np.random.choice(len(valid), DBSCAN_SUBSAMPLE, replace=False)
        coords_sample = coords_rad[sample_idx]
    else:
        coords_sample = coords_rad
        sample_idx    = np.arange(len(valid))

    db = DBSCAN(eps=eps_rad, min_samples=min_samples, algorithm="ball_tree",
                metric="haversine", n_jobs=-1)
    sample_labels = db.fit_predict(coords_sample)

    n_clusters = len(set(sample_labels) - {-1})
    logger.info(f"DBSCAN: {n_clusters} clusters found on {len(coords_sample):,} sample points (eps={eps_km}km, min_samples={min_samples})")
    assert n_clusters >= min_clusters, (
        f"DBSCAN found only {n_clusters} clusters (expected >= {min_clusters}). "
        f"Try adjusting eps_km ({eps_km}) or min_samples ({min_samples})."
    )

    # Propagate to all valid points via BallTree k=1 nearest neighbour
    tree = BallTree(coords_sample, metric="haversine")
    _, nn_idx = tree.query(coords_rad, k=1)
    all_labels = sample_labels[nn_idx.flatten()]

    df.loc[valid_idx, "cluster_id"] = all_labels

    noise_pct = (all_labels == -1).mean() * 100
    logger.info(f"cluster_id assigned: noise = {noise_pct:.1f}%")
    return df


def run(engine=None) -> pd.DataFrame:
    """
    Reads transactions_clean from DB, computes spatial features, returns DataFrame.
    Called by build_features.py.
    """
    if engine is None:
        engine = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info("Loading transactions_clean for spatial features...")
    query = """
        SELECT id, county_name, latitude, longitude, has_valid_coords, is_outlier
        FROM transactions_clean
        WHERE is_outlier = FALSE
    """
    df = pd.read_sql(query, engine)
    logger.info(f"  {len(df):,} rows loaded")

    df = compute_centroid_distance(df)
    df = compute_dbscan_clusters(df, min_clusters=5)

    return df[["id", "dist_km_centroid", "cluster_id"]]
