"""
gtfs_features.py
----------------
Computes GTFS bus stop proximity features for each property in transaction_features.

Feature produced:
  - dist_gtfs_bus_km   — km to nearest RED bus stop (from GTFS Santiago DTPM)

Strategy:
  - Downloads stops.txt from Santiago's official GTFS feed (DTPM)
  - Caches parsed stops as a pickle file (data/processed/gtfs_stops.pkl)
  - Distance: BallTree + haversine (same approach as osm_features.py)
  - Graceful fallback: if download fails, logs warning and skips DB write.

Usage:
    python src/features/gtfs_features.py              # write to DB
    python src/features/gtfs_features.py --dry-run    # stats only, no DB write
    python src/features/gtfs_features.py --force-refresh  # re-download GTFS
"""

import argparse
import io
import os
import pickle
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from loguru import logger
from sklearn.neighbors import BallTree
from sqlalchemy import create_engine, text

load_dotenv()

# ── Constants ──────────────────────────────────────────────────────────────────

GTFS_URL = "https://www.dtpm.cl/archivos/gtfs/GTFS.zip"
GTFS_CACHE_FILE = "data/processed/gtfs_stops.pkl"

EARTH_RADIUS_KM = 6371.0

# Santiago RM bounding box — tighter than the Overpass bbox
# Filters out stops outside the metropolitan region
SANTIAGO_LAT_MIN = -34.0
SANTIAGO_LAT_MAX = -33.0
SANTIAGO_LON_MIN = -71.2
SANTIAGO_LON_MAX = -70.3

DOWNLOAD_TIMEOUT_S = 60


# ── Path helpers ───────────────────────────────────────────────────────────────

def _repo_root() -> Path:
    """Returns the re_cl/ directory (three levels up from this file)."""
    return Path(__file__).resolve().parents[3]


def _cache_path() -> Path:
    return _repo_root() / GTFS_CACHE_FILE


# ── GTFS stop loading ──────────────────────────────────────────────────────────

def load_gtfs_stops(force_refresh: bool = False) -> Optional[pd.DataFrame]:
    """
    Loads RED bus stops from GTFS feed (Santiago DTPM).

    If cache exists and force_refresh is False, loads from pickle.
    Otherwise downloads the GTFS zip, extracts stops.txt, filters to Santiago RM,
    and caches the result.

    Returns DataFrame with columns: stop_id, stop_name, lat, lon
    Returns None if download fails.
    """
    cache = _cache_path()

    if cache.exists() and not force_refresh:
        logger.info(f"Loading GTFS stops from cache: {cache}")
        try:
            with open(cache, "rb") as f:
                df = pickle.load(f)
            logger.info(f"  Loaded {len(df):,} stops from cache")
            return df
        except Exception as exc:
            logger.warning(f"Cache load failed ({exc}), re-downloading...")

    logger.info(f"Downloading GTFS feed from {GTFS_URL} ...")
    try:
        resp = requests.get(
            GTFS_URL,
            timeout=DOWNLOAD_TIMEOUT_S,
            headers={"User-Agent": "RE_CL/1.0 (real-estate research, Chile)"},
            stream=True,
        )
        resp.raise_for_status()

        raw_bytes = resp.content
        logger.info(f"  Downloaded {len(raw_bytes) / 1024:.0f} KB")

        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            # Locate stops.txt (may be nested in a subdirectory)
            stops_entry = next(
                (name for name in zf.namelist() if name.endswith("stops.txt")),
                None,
            )
            if stops_entry is None:
                logger.error("stops.txt not found inside GTFS zip — aborting")
                return None

            with zf.open(stops_entry) as sf:
                stops_raw = pd.read_csv(sf, dtype=str)

        logger.info(f"  stops.txt: {len(stops_raw):,} rows, columns: {list(stops_raw.columns)}")

    except requests.exceptions.RequestException as exc:
        logger.warning(f"GTFS download failed: {exc} — dist_gtfs_bus_km will be skipped")
        return None
    except zipfile.BadZipFile as exc:
        logger.warning(f"GTFS zip is corrupt: {exc} — dist_gtfs_bus_km will be skipped")
        return None
    except Exception as exc:
        logger.warning(f"Unexpected error loading GTFS: {exc} — dist_gtfs_bus_km will be skipped")
        return None

    # ── Parse and filter ───────────────────────────────────────────────────────
    required = {"stop_id", "stop_lat", "stop_lon"}
    missing = required - set(stops_raw.columns)
    if missing:
        logger.error(f"stops.txt missing required columns: {missing}")
        return None

    df = stops_raw[["stop_id", "stop_name", "stop_lat", "stop_lon"]].copy() \
        if "stop_name" in stops_raw.columns \
        else stops_raw[["stop_id", "stop_lat", "stop_lon"]].assign(stop_name="")

    df = df.rename(columns={"stop_lat": "lat", "stop_lon": "lon"})
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna(subset=["lat", "lon"])

    # Filter to Santiago RM bounding box
    in_bbox = (
        (df["lat"] >= SANTIAGO_LAT_MIN) & (df["lat"] <= SANTIAGO_LAT_MAX) &
        (df["lon"] >= SANTIAGO_LON_MIN) & (df["lon"] <= SANTIAGO_LON_MAX)
    )
    df = df[in_bbox].reset_index(drop=True)
    logger.info(f"  After Santiago RM bbox filter: {len(df):,} stops")

    # ── Cache ──────────────────────────────────────────────────────────────────
    cache.parent.mkdir(parents=True, exist_ok=True)
    with open(cache, "wb") as f:
        pickle.dump(df, f)
    logger.info(f"  Cached to {cache}")

    return df


# ── BallTree distance computation ──────────────────────────────────────────────

def compute_gtfs_features(df: pd.DataFrame, gtfs_stops: pd.DataFrame) -> pd.DataFrame:
    """
    Computes dist_gtfs_bus_km for each row in df using BallTree haversine.

    Parameters
    ----------
    df : DataFrame with at least 'latitude' and 'longitude' columns.
    gtfs_stops : DataFrame with 'lat' and 'lon' columns (GTFS stops).

    Returns
    -------
    df with 'dist_gtfs_bus_km' column added (NaN where coordinates are missing).
    """
    df = df.copy()
    df["dist_gtfs_bus_km"] = np.nan

    # Build BallTree from stop coordinates
    stop_coords_rad = np.radians(gtfs_stops[["lat", "lon"]].values)
    tree = BallTree(stop_coords_rad, metric="haversine")

    # Identify rows with valid coordinates
    has_coords = df["latitude"].notna() & df["longitude"].notna()
    n_valid = has_coords.sum()
    n_total = len(df)
    logger.info(f"  {n_valid:,} / {n_total:,} rows have valid coordinates")

    if n_valid == 0:
        logger.warning("No valid coordinates — dist_gtfs_bus_km will be all NaN")
        return df

    query_rad = np.radians(df.loc[has_coords, ["latitude", "longitude"]].values)
    dist_rad, _ = tree.query(query_rad, k=1)
    dist_km = dist_rad.flatten() * EARTH_RADIUS_KM

    df.loc[has_coords, "dist_gtfs_bus_km"] = dist_km
    logger.info(
        f"  dist_gtfs_bus_km: median={np.nanmedian(dist_km):.3f} km, "
        f"mean={np.nanmean(dist_km):.3f} km, "
        f"p95={np.nanpercentile(dist_km, 95):.3f} km"
    )
    return df


# ── Database helpers ───────────────────────────────────────────────────────────

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


# ── Main run function ──────────────────────────────────────────────────────────

def run(connection=None, skip_cache: bool = False) -> None:
    """
    End-to-end GTFS enrichment:
      1. Load GTFS stops (download or cache).
      2. Query transaction_features for rows with NULL dist_gtfs_bus_km.
      3. Compute distances with BallTree.
      4. Bulk UPDATE transaction_features.

    Parameters
    ----------
    connection : SQLAlchemy engine or connection (optional, creates one if None).
    skip_cache : bool — if True, force re-download of GTFS data.
    """
    # ── Load stops ─────────────────────────────────────────────────────────────
    gtfs_stops = load_gtfs_stops(force_refresh=skip_cache)
    if gtfs_stops is None or gtfs_stops.empty:
        logger.warning(
            "GTFS stops unavailable — skipping dist_gtfs_bus_km enrichment. "
            "Re-run when internet is available or use --force-refresh."
        )
        return

    logger.info(f"GTFS stops loaded: {len(gtfs_stops):,} stops in Santiago RM")

    # ── Database setup ─────────────────────────────────────────────────────────
    if connection is None:
        engine = create_engine(_build_db_url(), pool_pre_ping=True)
    else:
        engine = connection

    # ── Query rows needing enrichment ──────────────────────────────────────────
    query = text("""
        SELECT tf.id, tc.latitude, tc.longitude
        FROM transaction_features tf
        JOIN transactions_clean tc ON tc.id = tf.clean_id
        WHERE tf.dist_gtfs_bus_km IS NULL
          AND tc.latitude IS NOT NULL
          AND tc.longitude IS NOT NULL
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    n_pending = len(df)
    logger.info(f"Rows to enrich: {n_pending:,}")

    if n_pending == 0:
        logger.info("All rows already have dist_gtfs_bus_km — nothing to do")
        return

    # ── Compute distances ──────────────────────────────────────────────────────
    df = compute_gtfs_features(df, gtfs_stops)

    # Filter to rows where we got a valid distance
    to_update = df[df["dist_gtfs_bus_km"].notna()][["id", "dist_gtfs_bus_km"]]
    n_update = len(to_update)
    logger.info(f"Updating {n_update:,} rows in transaction_features...")

    # ── Bulk UPDATE ────────────────────────────────────────────────────────────
    update_sql = text("""
        UPDATE transaction_features
           SET dist_gtfs_bus_km = :dist_gtfs_bus_km
         WHERE id = :id
    """)

    records = to_update.rename(columns={"dist_gtfs_bus_km": "dist_gtfs_bus_km"}).to_dict("records")

    chunk_size = 5000
    t0 = time.perf_counter()
    with engine.begin() as conn:
        for i in range(0, len(records), chunk_size):
            chunk = records[i : i + chunk_size]
            conn.execute(update_sql, chunk)
            pct = min(i + chunk_size, n_update) / n_update * 100
            logger.info(f"  Updated {min(i + chunk_size, n_update):,} / {n_update:,} ({pct:.0f}%)")

    elapsed = time.perf_counter() - t0
    logger.info(f"dist_gtfs_bus_km enrichment complete — {n_update:,} rows in {elapsed:.1f}s")


# ── CLI entry point ────────────────────────────────────────────────────────────

def main(dry_run: bool = False, force_refresh: bool = False) -> None:
    logger.info("=" * 60)
    logger.info("GTFS FEATURES — START")
    logger.info("=" * 60)

    gtfs_stops = load_gtfs_stops(force_refresh=force_refresh)

    if gtfs_stops is None or gtfs_stops.empty:
        logger.warning("No GTFS stops available — exiting")
        return

    logger.info(f"Loaded {len(gtfs_stops):,} stops in Santiago RM")

    if dry_run:
        logger.info("[DRY RUN] Fetching sample coordinates from transaction_features...")
        engine = create_engine(_build_db_url(), pool_pre_ping=True)
        with engine.connect() as conn:
            df_sample = pd.read_sql(text("""
                SELECT tf.id, tc.latitude, tc.longitude
                FROM transaction_features tf
                JOIN transactions_clean tc ON tc.id = tf.clean_id
                WHERE tc.latitude IS NOT NULL AND tc.longitude IS NOT NULL
                LIMIT 1000
            """), conn)

        if df_sample.empty:
            logger.info("[DRY RUN] No rows found in transaction_features — cannot preview")
            return

        df_sample = compute_gtfs_features(df_sample, gtfs_stops)
        logger.info("[DRY RUN] Sample statistics:")
        logger.info(df_sample["dist_gtfs_bus_km"].describe().to_string())
        logger.info("[DRY RUN] Would update to DB — skipping")
        return

    run(skip_cache=force_refresh)

    logger.info("=" * 60)
    logger.info("GTFS FEATURES — COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute GTFS bus stop proximity features")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview stats only — do not write to DB",
    )
    parser.add_argument(
        "--force-refresh", action="store_true",
        help="Re-download GTFS feed, ignoring local cache",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run, force_refresh=args.force_refresh)
