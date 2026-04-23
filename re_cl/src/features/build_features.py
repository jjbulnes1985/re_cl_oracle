"""
build_features.py
-----------------
Orchestrator for all feature engineering pipelines.

Runs in order:
  1. price_features   — gap_pct, percentiles
  2. spatial_features — distances, DBSCAN clusters
  3. temporal_features — quarter dummies, season_index
  4. osm_features     — Metro/bus/school/hospital/park/mall distances + amenity counts
                        (optional: skip with --skip-osm if Overpass API is unavailable)
  5. gtfs_features    — dist_gtfs_bus_km: distance to nearest RED bus stop (DTPM GTFS)
                        (optional: skip with --skip-gtfs if offline or feed unavailable)
  6. ieut_spatial_features — 16 distance features from local ieut-inciti shapefiles
                        (optional: skip with --skip-ieut if shapefiles unavailable)

Merges all into a single DataFrame and writes to `transaction_features` table.
Idempotent: TRUNCATE + reload on each run.  # NEEDS APPROVAL for production DB

Usage:
    python src/features/build_features.py
    python src/features/build_features.py --dry-run      # Preview only, no DB write
    python src/features/build_features.py --skip-osm     # Skip OSM/Overpass step
    python src/features/build_features.py --skip-gtfs    # Skip GTFS bus stop step
    python src/features/build_features.py --skip-ieut    # Skip ieut-inciti shapefiles
"""

import argparse
import os
import time
import sys

import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.features import price_features, spatial_features, temporal_features, osm_features, gtfs_features
try:
    from src.features import ieut_spatial_features as _ieut_mod
    _IEUT_AVAILABLE = True
except ImportError:
    _IEUT_AVAILABLE = False

load_dotenv()


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


def merge_feature_dfs(
    price_df:    pd.DataFrame,
    spatial_df:  pd.DataFrame,
    temporal_df: pd.DataFrame,
    osm_df:      pd.DataFrame = None,
    gtfs_df:     pd.DataFrame = None,
) -> pd.DataFrame:
    """
    Merges price, spatial, temporal (and optionally OSM + GTFS) feature DataFrames on clean_id.
    Renames 'id' → 'clean_id' for the transaction_features schema.
    Uses outer join so rows present in only one module get NULLs elsewhere.
    osm_df and gtfs_df are optional — pass None to skip those columns.
    """
    merged = price_df.rename(columns={"id": "clean_id"})
    merged = merged.merge(
        spatial_df.rename(columns={"id": "clean_id"}),
        on="clean_id", how="outer"
    )
    merged = merged.merge(
        temporal_df.rename(columns={"id": "clean_id"}),
        on="clean_id", how="outer"
    )
    if osm_df is not None:
        # osm_df already uses clean_id (run() renames it)
        merged = merged.merge(osm_df, on="clean_id", how="left")
    if gtfs_df is not None:
        # gtfs_df uses clean_id (run() renames it)
        merged = merged.merge(gtfs_df, on="clean_id", how="left")
    return merged


def write_features(df: pd.DataFrame, engine) -> int:
    """
    Writes features to transaction_features table.
    TRUNCATE + reload pattern (idempotent).

    NEEDS APPROVAL: This truncates transaction_features — safe to re-run,
    the table is fully derived from transactions_clean.
    """
    # Ensure migration DDL exists
    with engine.connect() as conn:
        exists = conn.execute(text(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = 'transaction_features')"
        )).scalar()

    if not exists:
        logger.error(
            "Table 'transaction_features' does not exist. "
            "Run: psql ... -f re_cl/db/migrations/001_transaction_features.sql"
        )
        sys.exit(1)

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE transaction_features RESTART IDENTITY"))

    df.to_sql(
        "transaction_features",
        engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=5000,
    )
    return len(df)


def main(dry_run: bool = False, skip_osm: bool = False, skip_gtfs: bool = False,
         skip_ieut: bool = False, engine=None) -> None:
    if engine is None:
        engine = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info("=" * 60)
    logger.info("BUILD FEATURES — START")
    logger.info("=" * 60)

    total_start = time.perf_counter()
    results = {}

    # ── Price features ─────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    logger.info("Running price_features...")
    price_df = price_features.run(engine=engine)
    results["price"] = {"rows": len(price_df), "secs": time.perf_counter() - t0}
    logger.info(f"  price_features: {results['price']['rows']:,} rows in {results['price']['secs']:.1f}s")

    # ── Spatial features ───────────────────────────────────────────────────────
    t0 = time.perf_counter()
    logger.info("Running spatial_features...")
    spatial_df = spatial_features.run(engine=engine)
    results["spatial"] = {"rows": len(spatial_df), "secs": time.perf_counter() - t0}
    logger.info(f"  spatial_features: {results['spatial']['rows']:,} rows in {results['spatial']['secs']:.1f}s")

    # ── Temporal features ──────────────────────────────────────────────────────
    t0 = time.perf_counter()
    logger.info("Running temporal_features...")
    temporal_df = temporal_features.run(engine=engine)
    results["temporal"] = {"rows": len(temporal_df), "secs": time.perf_counter() - t0}
    logger.info(f"  temporal_features: {results['temporal']['rows']:,} rows in {results['temporal']['secs']:.1f}s")

    # ── OSM features (optional) ────────────────────────────────────────────────
    osm_df = None
    if skip_osm:
        logger.info("Skipping osm_features (--skip-osm flag set)")
    else:
        t0 = time.perf_counter()
        logger.info("Running osm_features...")
        try:
            osm_df = osm_features.run(engine=engine)
            results["osm"] = {"rows": len(osm_df), "secs": time.perf_counter() - t0}
            logger.info(
                f"  osm_features: {results['osm']['rows']:,} rows in {results['osm']['secs']:.1f}s"
            )
        except Exception as exc:
            logger.warning(
                f"osm_features failed ({exc}) — continuing without OSM columns. "
                "Use --skip-osm to suppress this warning."
            )
            osm_df = None

    # ── GTFS bus stop features (optional) ─────────────────────────────────────
    gtfs_df = None
    if skip_gtfs:
        logger.info("Skipping gtfs_features (--skip-gtfs flag set)")
    else:
        t0 = time.perf_counter()
        logger.info("Running gtfs_features (GTFS bus stop enrichment)...")
        try:
            stops = gtfs_features.load_gtfs_stops()
            if stops is not None and not stops.empty:
                # Load coordinates for all valid properties
                import pandas as _pd
                with engine.connect() as conn:
                    coords_df = _pd.read_sql(
                        "SELECT id AS clean_id, latitude, longitude "
                        "FROM transactions_clean WHERE is_outlier = FALSE",
                        conn,
                    )
                gtfs_enriched = gtfs_features.compute_gtfs_features(coords_df, stops)
                gtfs_df = gtfs_enriched[["clean_id", "dist_gtfs_bus_km"]]
                results["gtfs"] = {"rows": len(gtfs_df), "secs": time.perf_counter() - t0}
                logger.info(
                    f"  gtfs_features: {results['gtfs']['rows']:,} rows in {results['gtfs']['secs']:.1f}s"
                )
            else:
                logger.warning(
                    "gtfs_features: GTFS stops unavailable — continuing without dist_gtfs_bus_km. "
                    "Use --skip-gtfs to suppress this warning."
                )
        except Exception as exc:
            logger.warning(
                f"gtfs_features failed ({exc}) — continuing without GTFS columns. "
                "Use --skip-gtfs to suppress this warning."
            )
            gtfs_df = None

    # ── Merge ──────────────────────────────────────────────────────────────────
    logger.info("Merging feature DataFrames...")
    merged = merge_feature_dfs(price_df, spatial_df, temporal_df, osm_df=osm_df, gtfs_df=gtfs_df)
    logger.info(f"  Merged: {len(merged):,} rows, {len(merged.columns)} columns")

    if dry_run:
        logger.info("[DRY RUN] Would write to transaction_features — skipping")
        logger.info(merged.describe().to_string())
        return

    # ── Write to DB ────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    n = write_features(merged, engine)
    write_secs = time.perf_counter() - t0

    # ── ieut-inciti spatial features (step 6, post-write UPDATE) ──────────────
    # These are computed as UPDATEs against transaction_features rows already in DB
    if skip_ieut:
        logger.info("Skipping ieut_spatial_features (--skip-ieut flag set)")
    elif not _IEUT_AVAILABLE:
        logger.warning("ieut_spatial_features module not found — skipping")
    else:
        t0_ieut = time.perf_counter()
        logger.info("Running ieut_spatial_features (16 local shapefile distances)...")
        try:
            _ieut_mod.run(engine, batch_size=10_000, dry_run=False)
            results["ieut"] = {"secs": time.perf_counter() - t0_ieut}
            logger.info(f"  ieut_spatial_features: done in {results['ieut']['secs']:.1f}s")
        except Exception as exc:
            logger.warning(
                f"ieut_spatial_features failed ({exc}) — continuing without ieut columns. "
                "Use --skip-ieut to suppress this warning."
            )

    total_secs = time.perf_counter() - total_start
    logger.info("=" * 60)
    logger.info(f"BUILD FEATURES — COMPLETE")
    logger.info(f"  Rows written: {n:,}")
    logger.info(f"  Write time:  {write_secs:.1f}s")
    logger.info(f"  Total time:  {total_secs:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only — do not write to DB")
    parser.add_argument("--skip-osm", action="store_true",
                        help="Skip OSM/Overpass step (useful if API is unavailable)")
    parser.add_argument("--skip-gtfs", action="store_true",
                        help="Skip GTFS bus stop step (useful if offline or feed unavailable)")
    parser.add_argument("--skip-ieut", action="store_true",
                        help="Skip ieut-inciti shapefile distances (use if IEUT_DATA_DIR unavailable)")
    args = parser.parse_args()
    main(dry_run=args.dry_run, skip_osm=args.skip_osm, skip_gtfs=args.skip_gtfs,
         skip_ieut=args.skip_ieut)
