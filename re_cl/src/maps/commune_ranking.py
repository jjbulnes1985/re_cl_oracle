"""
commune_ranking.py
------------------
Computes per-commune statistics and populates commune_stats table.

Outputs:
  - commune_stats table: n_transactions, median_opportunity_score,
    pct_subvaloradas, median_uf_m2, median_gap_pct, scored_at
  - Optionally prints/exports a ranking CSV

Usage:
    python src/maps/commune_ranking.py
    python src/maps/commune_ranking.py --dry-run
    python src/maps/commune_ranking.py --output data/exports/ranking.csv
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.features.commune_context import load_crime_index, load_ine_census

EXPORTS_DIR   = Path(os.getenv("EXPORTS_DIR", "data/exports"))
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0")

UNDERVAL_THRESHOLD = float(os.getenv("UNDERVAL_THRESHOLD", "0.6"))  # score > this = subvalorada


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


def load_opportunity_data(engine) -> pd.DataFrame:
    """Load opportunity scores with commune and typology data."""
    query = f"""
        SELECT
            v.county_name,
            v.project_type,
            v.opportunity_score,
            v.undervaluation_score,
            v.gap_pct,
            v.uf_m2_building,
            v.data_confidence
        FROM v_opportunities v
        WHERE v.model_version = '{MODEL_VERSION}'
          AND v.opportunity_score IS NOT NULL
    """
    df = pd.read_sql(query, engine)
    logger.info(f"Loaded {len(df):,} scored records for commune ranking")
    return df


def compute_commune_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregates opportunity scores by commune.

    Returns DataFrame with columns:
        county_name, n_transactions, median_opportunity_score,
        pct_subvaloradas, median_uf_m2, median_gap_pct, model_version
    """
    if df.empty:
        logger.warning("Empty DataFrame passed to compute_commune_stats")
        return pd.DataFrame()

    grouped = df.groupby("county_name").agg(
        n_transactions         = ("opportunity_score", "count"),
        median_opportunity_score = ("opportunity_score", "median"),
        mean_opportunity_score   = ("opportunity_score", "mean"),
        median_uf_m2           = ("uf_m2_building",   "median"),
        median_gap_pct         = ("gap_pct",           "median"),
        mean_data_confidence   = ("data_confidence",  "mean"),
    ).reset_index()

    # Percentage of properties with score above threshold (subvaloradas)
    high_score = (
        df[df["opportunity_score"] > UNDERVAL_THRESHOLD]
        .groupby("county_name")
        .size()
        .rename("n_subvaloradas")
        .reset_index()
    )
    grouped = grouped.merge(high_score, on="county_name", how="left")
    grouped["n_subvaloradas"] = grouped["n_subvaloradas"].fillna(0).astype(int)
    grouped["pct_subvaloradas"] = (
        grouped["n_subvaloradas"] / grouped["n_transactions"] * 100
    ).round(2)

    grouped["model_version"] = MODEL_VERSION

    # Round numeric columns
    for col in ["median_opportunity_score", "mean_opportunity_score",
                "median_uf_m2", "median_gap_pct", "mean_data_confidence"]:
        grouped[col] = grouped[col].round(4)

    grouped = grouped.sort_values("median_opportunity_score", ascending=False)
    logger.info(f"Computed commune stats for {len(grouped)} communes")
    return grouped


def compute_typology_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """Returns per-commune, per-typology opportunity score summary."""
    return (
        df.groupby(["county_name", "project_type"])
        .agg(
            n              = ("opportunity_score", "count"),
            median_score   = ("opportunity_score", "median"),
            median_gap_pct = ("gap_pct",           "median"),
        )
        .reset_index()
        .sort_values(["county_name", "median_score"], ascending=[True, False])
    )


def enrich_commune_stats(stats_df: pd.DataFrame) -> pd.DataFrame:
    """
    LEFT JOIN crime index and INE census data onto commune stats.
    Adds: crime_index, crime_tier, densidad_norm, educacion_score, hacinamiento_score.
    Communes not found in reference data get NaN (DB columns are nullable).
    """
    try:
        crime_df = load_crime_index()[["county_name", "crime_index", "crime_tier"]]
        stats_df = stats_df.merge(crime_df, on="county_name", how="left")
        logger.info(f"Crime index joined: {stats_df['crime_index'].notna().sum()}/{len(stats_df)} communes matched")
    except Exception as e:
        logger.warning(f"Could not join crime index: {e}")
        stats_df["crime_index"] = None
        stats_df["crime_tier"]  = None

    try:
        ine_df = load_ine_census()[["county_name", "densidad_norm", "educacion_score", "hacinamiento_score"]]
        stats_df = stats_df.merge(ine_df, on="county_name", how="left")
        logger.info(f"INE census joined: {stats_df['educacion_score'].notna().sum()}/{len(stats_df)} communes matched")
    except Exception as e:
        logger.warning(f"Could not join INE census data: {e}")
        stats_df["densidad_norm"]      = None
        stats_df["educacion_score"]    = None
        stats_df["hacinamiento_score"] = None

    return stats_df


def write_commune_stats(stats_df: pd.DataFrame, engine, dry_run: bool = False) -> int:
    """Write commune stats to DB, replacing existing rows for this model version."""
    if dry_run:
        logger.info(f"[DRY RUN] Would write {len(stats_df)} communes to commune_stats")
        logger.info(stats_df[["county_name", "n_transactions",
                               "median_opportunity_score", "pct_subvaloradas"]].to_string(index=False))
        return 0

    cols_map = {
        "county_name":              "county_name",
        "n_transactions":           "n_transactions",
        "median_opportunity_score": "median_score",
        "pct_subvaloradas":         "pct_subvaloradas",
        "median_uf_m2":             "median_uf_m2",
        "median_gap_pct":           "median_gap_pct",
        "model_version":            "model_version",
        # Enrichment columns (present after enrich_commune_stats)
        "crime_index":              "crime_index",
        "crime_tier":               "crime_tier",
        "densidad_norm":            "densidad_norm",
        "educacion_score":          "educacion_score",
        "hacinamiento_score":       "hacinamiento_score",
    }
    # Only include columns that actually exist in the DataFrame
    present_cols = {k: v for k, v in cols_map.items() if k in stats_df.columns}
    write_df = stats_df.rename(columns=present_cols)[list(present_cols.values())]
    write_df["scored_at"] = pd.Timestamp.utcnow()
    # DB requires NOT NULL project_type; commune_ranking aggregates across all types
    if "project_type" not in write_df.columns:
        write_df["project_type"] = "all"

    with engine.begin() as conn:
        deleted = conn.execute(
            text("DELETE FROM commune_stats WHERE model_version = :v"),
            {"v": MODEL_VERSION}
        ).rowcount
        if deleted:
            logger.info(f"Deleted {deleted} existing commune_stats rows for version {MODEL_VERSION}")

    write_df.to_sql("commune_stats", engine, if_exists="append", index=False,
                    method="multi", chunksize=500)
    logger.info(f"Wrote {len(write_df)} communes to commune_stats")
    return len(write_df)


def print_top_communes(stats_df: pd.DataFrame, n: int = 20) -> None:
    """Print top communes ranked by median opportunity score."""
    top = stats_df.head(n)
    logger.info("=" * 70)
    logger.info(f"TOP {n} COMUNAS POR OPORTUNIDAD (modelo={MODEL_VERSION})")
    logger.info("=" * 70)
    logger.info(f"{'Comuna':<25} {'N':>8} {'Score Med':>10} {'%Subval':>9} {'Gap Med%':>10}")
    logger.info("-" * 70)
    for _, row in top.iterrows():
        logger.info(
            f"{row['county_name']:<25} "
            f"{row['n_transactions']:>8,} "
            f"{row['median_opportunity_score']:>10.4f} "
            f"{row['pct_subvaloradas']:>8.1f}% "
            f"{row['median_gap_pct']*100:>9.1f}%"
        )
    logger.info("=" * 70)


def main(dry_run: bool = False, output: str = None) -> None:
    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    df = load_opportunity_data(engine)
    if df.empty:
        logger.error("No scored data. Run opportunity_score.py first.")
        sys.exit(1)

    stats_df = compute_commune_stats(df)

    n_communes = len(stats_df)
    if n_communes < 10:
        logger.warning(f"Only {n_communes} communes found (expected >= 10 for RM)")

    # Enrich with crime index and INE census data
    stats_df = enrich_commune_stats(stats_df)

    print_top_communes(stats_df)

    # Typology breakdown (logged at debug level)
    breakdown = compute_typology_breakdown(df)
    logger.debug(f"Typology breakdown: {len(breakdown)} rows")

    write_commune_stats(stats_df, engine, dry_run=dry_run)

    # Export CSV
    if output:
        out_path = Path(output)
    elif not dry_run:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = EXPORTS_DIR / f"commune_ranking_{MODEL_VERSION}.csv"
    else:
        out_path = None

    if out_path:
        stats_df.to_csv(out_path, index=False)
        logger.info(f"Commune ranking exported: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()
    main(dry_run=args.dry_run, output=args.output)
