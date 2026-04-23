"""
scraped_to_scored.py
--------------------
Pipeline: scraped_listings → model_scores

Takes fresh listings from Portal Inmobiliario / Toctoc, normalizes them,
runs the hedonic model to predict fair price, computes opportunity score,
and writes to model_scores tagged as source='scraped'.

Flow:
  1. Load unscored scraped_listings (scraped since last run)
  2. Normalize: UF/m², typology, coordinates validation
  3. Predict fair UF/m² via loaded hedonic model
  4. Compute undervaluation_score (percentile within commune+type)
  5. Compute opportunity_score using active scoring profile
  6. Upsert to model_scores with source='scraped'

Usage:
    python src/scoring/scraped_to_scored.py
    python src/scoring/scraped_to_scored.py --dry-run
    python src/scoring/scraped_to_scored.py --profile location
    python src/scoring/scraped_to_scored.py --since 2024-06-01
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.models.hedonic_model import load_model, preprocess, CAT_FEATURES, NUM_FEATURES
from src.scoring.scoring_profile import ScoringProfile, compute_profile_score

MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0")


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


# ── Load scraped listings ──────────────────────────────────────────────────────

def load_unscored_scraped(engine, since: str = None) -> pd.DataFrame:
    """
    Load scraped listings that haven't been scored yet.
    Uses LEFT JOIN on model_scores to find unscored rows.
    """
    since_clause = ""
    if since:
        since_clause = f"AND sl.scraped_at >= '{since}'"

    query = f"""
        SELECT
            sl.id            AS scraped_id,
            sl.source,
            sl.external_id,
            sl.project_type  AS project_type,
            sl.county_name,
            sl.price_uf      AS real_value_uf,
            sl.surface_m2,
            sl.uf_m2         AS uf_m2_building,
            sl.latitude,
            sl.longitude,
            sl.scraped_at
        FROM scraped_listings sl
        LEFT JOIN model_scores ms
            ON ms.clean_id = sl.id
            AND ms.model_version = '{MODEL_VERSION}'
            AND ms.source = 'scraped'
        WHERE ms.id IS NULL
          AND sl.uf_m2 IS NOT NULL
          AND sl.uf_m2 > 0
          AND sl.county_name IS NOT NULL
          {since_clause}
        ORDER BY sl.scraped_at DESC
        LIMIT 10000
    """
    df = pd.read_sql(query, engine)
    logger.info(f"Loaded {len(df):,} unscored scraped listings")
    return df


# ── Normalize for model ────────────────────────────────────────────────────────

TYPOLOGY_NORM = {
    "apartments":  "apartments",
    "residential": "residential",
    "land":        "land",
    "retail":      "retail",
    "unknown":     "residential",  # fallback
}

def normalize_scraped(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare scraped listings for hedonic model inference."""
    df = df.copy()

    # Normalize typology
    df["project_type_norm"] = df["project_type"].map(TYPOLOGY_NORM).fillna("residential")

    # Surface fallback (median by type if missing)
    type_medians = df.groupby("project_type_norm")["surface_m2"].transform("median")
    df["surface_m2"] = df["surface_m2"].fillna(type_medians)

    # Year — scraped listings are current
    df["year"]    = datetime.now().year
    df["quarter"] = (datetime.now().month - 1) // 3 + 1

    # Confidence — scraped data has lower confidence than CBR (no notarial verification)
    df["data_confidence"] = 0.60  # base confidence for portal listings

    # Penalize missing surface
    df.loc[df["surface_m2"].isna(), "data_confidence"] -= 0.10
    df["data_confidence"] = df["data_confidence"].clip(0.4, 0.8)

    # Required columns with defaults
    df["calculated_value_uf"] = np.nan
    df["year_building"]       = np.nan

    # Identifier
    df["id"] = df["scraped_id"]

    return df


# ── Predict fair price ────────────────────────────────────────────────────────

def _add_model_defaults(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add default values for model features missing in scraped listings.
    XGBoost handles NaN natively for numeric features; categoricals need a
    fallback label that exists in the encoder (use 'unknown' or mode).
    """
    df = df.copy()
    # Categorical defaults — must be values seen during training
    if "construction_year_bucket" not in df.columns:
        df["construction_year_bucket"] = "2001-2010"   # most common bucket in CBR data
    if "city_zone" not in df.columns:
        df["city_zone"] = "centro_norte"               # RM default
    # Numeric defaults — NaN is fine for XGBoost
    for col in ["dist_km_centroid", "cluster_id", "dist_metro_km", "dist_school_km",
                "dist_hospital_km", "dist_park_km", "dist_mall_km",
                "dist_bus_stop_km", "dist_gtfs_bus_km",
                "amenities_500m", "amenities_1km",
                "age", "age_sq", "log_surface", "surface_land_m2", "surface_building_m2",
                "gap_pct", "price_percentile_25", "price_percentile_50", "price_percentile_75",
                "price_vs_median", "season_index",
                "quarter_q1", "quarter_q2", "quarter_q3", "quarter_q4",
                # ieut-inciti local shapefile features (Phase 8) — NaN → XGBoost handles natively
                "dist_green_area_km",
                "dist_feria_km", "dist_mall_local_km", "n_commercial_blocks_500m",
                "dist_metro_local_km", "dist_bus_local_km", "dist_autopista_km", "dist_ciclovia_km",
                "dist_school_local_km", "dist_jardines_km", "dist_health_local_km",
                "dist_cultural_km", "dist_policia_km",
                "dist_airport_km", "dist_industrial_km", "dist_vertedero_km"]:
        if col not in df.columns:
            df[col] = np.nan
    if "year_building" not in df.columns:
        df["year_building"] = np.nan
    return df


def predict_fair_price(df: pd.DataFrame, model, encoders: dict) -> pd.DataFrame:
    """Run hedonic model on scraped listings to get predicted_uf_m2."""
    df = df.copy()

    try:
        df_prep = _add_model_defaults(df)
        df_proc, _ = preprocess(df_prep, encoders=encoders, fit=False)
        feature_cols = CAT_FEATURES + [f for f in NUM_FEATURES if f in df_proc.columns]
        X = df_proc[feature_cols]
        df["predicted_uf_m2"] = model.predict(X)
        valid = df["predicted_uf_m2"].notna().sum()
        logger.info(f"Predicted fair price for {valid:,}/{len(df):,} scraped listings")
    except Exception as e:
        logger.error(f"Model prediction failed: {e}. Setting predicted_uf_m2 = uf_m2_building.")
        df["predicted_uf_m2"] = df["uf_m2_building"]

    return df


# ── Undervaluation score ──────────────────────────────────────────────────────

def compute_undervaluation(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute gap_pct and undervaluation_score for scraped listings.
    gap_pct = (actual - predicted) / predicted  →  negative = undervalued
    undervaluation_score = inverted percentile within commune+type group
    """
    df = df.copy()

    df["actual_uf_m2"] = df["uf_m2_building"]
    df["gap_pct"] = (
        (df["actual_uf_m2"] - df["predicted_uf_m2"]) / df["predicted_uf_m2"].clip(lower=0.01)
    ).clip(-1, 2)

    # Percentile rank within (project_type_norm, county_name)
    df["undervaluation_score"] = np.nan
    for (ptype, county), grp in df.groupby(["project_type_norm", "county_name"]):
        if len(grp) < 2:
            df.loc[grp.index, "undervaluation_score"] = 0.5
            continue
        # Lower gap = more undervalued = higher score
        rank = grp["gap_pct"].rank(pct=True, ascending=True)
        df.loc[grp.index, "undervaluation_score"] = (1 - rank).clip(0, 1).round(4)

    # Also use gap from historical CBR context if commune exists
    df["gap_percentile"] = df.groupby(["project_type_norm", "county_name"])["gap_pct"].rank(pct=True)

    return df


# ── Write scores ──────────────────────────────────────────────────────────────

def write_scraped_scores(df: pd.DataFrame, engine, dry_run: bool = False) -> int:
    """Upsert scored scraped listings to model_scores, tagged source='scraped'."""
    if df.empty:
        logger.info("No scraped scores to write.")
        return 0

    scores_df = pd.DataFrame({
        "clean_id":             df["scraped_id"],
        "model_version":        MODEL_VERSION,
        "source":               "scraped",
        "undervaluation_score": df["undervaluation_score"],
        "data_confidence":      df["data_confidence"],
        "opportunity_score":    df["opportunity_score"],
        "predicted_uf_m2":      df["predicted_uf_m2"],
        "actual_uf_m2":         df["actual_uf_m2"],
        "gap_pct":              df["gap_pct"],
        "gap_percentile":       df.get("gap_percentile"),
        "scoring_profile":      df.get("scoring_profile", "default"),
        "scored_at":            pd.Timestamp.utcnow(),
    })

    if dry_run:
        logger.info(f"[DRY RUN] Would write {len(scores_df):,} scraped scores")
        logger.info(scores_df[["clean_id", "opportunity_score", "gap_pct"]].describe().to_string())
        return 0

    # Add 'source' column to model_scores if not present (migration guard)
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE model_scores
            ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'cbr',
            ADD COLUMN IF NOT EXISTS scoring_profile VARCHAR(50),
            ADD COLUMN IF NOT EXISTS scored_at TIMESTAMPTZ DEFAULT NOW()
        """))

    scores_df.to_sql("model_scores", engine, if_exists="append", index=False,
                     method="multi", chunksize=1000)
    logger.info(f"Wrote {len(scores_df):,} scraped scores to model_scores")
    return len(scores_df)


def print_summary(df: pd.DataFrame) -> None:
    n     = len(df)
    high  = (df["opportunity_score"] > 0.7).sum()
    mean  = df["opportunity_score"].mean()
    top5  = df.nlargest(5, "opportunity_score")[
        ["county_name", "project_type_norm", "opportunity_score", "gap_pct", "uf_m2_building"]
    ]
    logger.info("─" * 60)
    logger.info(f"SCRAPED SCORES: {n:,} | mean={mean:.4f} | high_opp={high:,}")
    logger.info("TOP 5 OPORTUNIDADES:")
    for _, row in top5.iterrows():
        logger.info(
            f"  {row['county_name']:<20} {row['project_type_norm']:<12} "
            f"score={row['opportunity_score']:.3f}  gap={row['gap_pct']*100:+.1f}%  "
            f"UF/m²={row['uf_m2_building']:.1f}"
        )
    logger.info("─" * 60)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False, profile_name: str = None, since: str = None) -> int:
    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info("=" * 60)
    logger.info(f"SCRAPED → SCORED (version={MODEL_VERSION})")
    logger.info("=" * 60)

    # Ensure model_scores has the extra columns before querying them
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE model_scores
            ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'cbr',
            ADD COLUMN IF NOT EXISTS scoring_profile VARCHAR(50),
            ADD COLUMN IF NOT EXISTS scored_at TIMESTAMPTZ DEFAULT NOW()
        """))

    # Load scraped listings
    df = load_unscored_scraped(engine, since=since)
    if df.empty:
        logger.info("No new unscored scraped listings. Nothing to do.")
        return 0

    # Normalize
    df = normalize_scraped(df)

    # Load model
    try:
        model, encoders, meta = load_model()
        logger.info(f"Hedonic model loaded (RMSE: {meta.get('metrics', {}).get('rmse_pct_of_median', '?')}%)")
        df = predict_fair_price(df, model, encoders)
    except FileNotFoundError:
        logger.warning("Hedonic model not found — using uf_m2 as predicted. Run hedonic_model.py first.")
        df["predicted_uf_m2"] = df["uf_m2_building"]

    # Undervaluation scores
    df = compute_undervaluation(df)

    # Scoring profile
    profile = ScoringProfile.from_name(profile_name) if profile_name else ScoringProfile.from_env()
    logger.info(f"Scoring profile: {profile.name}")
    df = compute_profile_score(df, profile)

    print_summary(df)

    # Write
    n = write_scraped_scores(df, engine, dry_run=dry_run)

    logger.info(f"SCRAPED → SCORED COMPLETE: {n:,} rows")
    return n


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--profile",  type=str,  default=None)
    parser.add_argument("--since",    type=str,  default=None,
                        help="Only score listings scraped after this date (YYYY-MM-DD)")
    args = parser.parse_args()
    main(dry_run=args.dry_run, profile_name=args.profile, since=args.since)
