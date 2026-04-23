"""
opportunity_score.py
--------------------
Computes the composite Opportunity Score and writes to model_scores table.

opportunity_score = (undervaluation_score * 0.70) + (data_confidence * 0.30)

Weights are configurable via env vars:
  WEIGHT_UNDERVALUATION (default: 0.70)
  WEIGHT_CONFIDENCE     (default: 0.30)

Output goes to model_scores table (see db/schema.sql).
Idempotent per model_version: deletes existing scores for this version before insert.

Usage:
    python src/scoring/opportunity_score.py
    python src/scoring/opportunity_score.py --dry-run
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.models.hedonic_model import load_model, load_training_data
from src.scoring import undervaluation as uv_module
from src.scoring import shap_explainer

MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0")
W_UNDERVAL    = float(os.getenv("WEIGHT_UNDERVALUATION", "0.70"))
W_CONFIDENCE  = float(os.getenv("WEIGHT_CONFIDENCE",     "0.30"))


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


def compute_opportunity_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes composite opportunity_score from undervaluation_score and data_confidence.
    Both inputs must be in [0, 1].
    """
    df = df.copy()

    has_both = df["undervaluation_score"].notna() & df["data_confidence"].notna()
    df["opportunity_score"] = np.nan

    df.loc[has_both, "opportunity_score"] = (
        df.loc[has_both, "undervaluation_score"] * W_UNDERVAL +
        df.loc[has_both, "data_confidence"]       * W_CONFIDENCE
    ).clip(0, 1).round(4)

    n_scored = df["opportunity_score"].notna().sum()
    mean_score = df["opportunity_score"].mean()
    logger.info(
        f"opportunity_score: {n_scored:,} rows scored. "
        f"Mean: {mean_score:.4f} | "
        f"Weights: underval={W_UNDERVAL}, confidence={W_CONFIDENCE}"
    )
    return df


def build_model_scores_df(
    uv_df: pd.DataFrame,
    shap_df: pd.DataFrame,
    base_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merges undervaluation scores, SHAP explanations, and base data
    into the shape expected by model_scores table.

    Passes through any commune-context columns present in base_df
    (e.g. crime_index, growth_score, census_score added by enrich_with_commune_context)
    so that scoring profiles can use them.
    """
    # Always include data_confidence; also carry through commune-context enrichment columns
    _context_cols = ["crime_index", "growth_score", "census_score",
                     "location_score", "county_name", "crime_tier"]
    base_cols = ["id", "data_confidence"] + [
        c for c in _context_cols if c in base_df.columns
    ]
    merged = uv_df.merge(base_df[base_cols], on="id", how="left")
    merged = compute_opportunity_score(merged)
    merged = merged.merge(shap_df.rename(columns={"id": "clean_id_shap"}),
                          left_on="id", right_on="clean_id_shap", how="left")

    scores_df = pd.DataFrame({
        "clean_id":            merged["id"],
        "model_version":       MODEL_VERSION,
        "undervaluation_score": merged["undervaluation_score"],
        "data_confidence":     merged["data_confidence"],
        "opportunity_score":   merged["opportunity_score"],
        "predicted_uf_m2":     merged["predicted_uf_m2"],
        "actual_uf_m2":        merged["actual_uf_m2"],
        "gap_pct":             merged["gap_pct"],
        "gap_percentile":      merged["gap_percentile"],
        "shap_top_features":   merged.get("shap_top_features", None),
        "feature_importance":  merged.get("feature_importance", None),
    })

    return scores_df


def write_scores(df: pd.DataFrame, engine, dry_run: bool = False) -> int:
    """
    Writes scores to model_scores table.
    Deletes existing rows for this model_version first (idempotent).
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would write {len(df):,} rows to model_scores (version={MODEL_VERSION})")
        logger.info(df[["clean_id", "opportunity_score", "gap_pct"]].describe().to_string())
        return 0

    with engine.begin() as conn:
        deleted = conn.execute(
            text("DELETE FROM model_scores WHERE model_version = :v"),
            {"v": MODEL_VERSION}
        ).rowcount
        if deleted > 0:
            logger.info(f"Deleted {deleted:,} existing scores for version {MODEL_VERSION}")

    df.to_sql("model_scores", engine, if_exists="append", index=False,
              method="multi", chunksize=2000)
    logger.info(f"Wrote {len(df):,} rows to model_scores (version={MODEL_VERSION})")
    return len(df)


def print_summary(engine) -> None:
    """Print a quick summary of scores written."""
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT
                COUNT(*)                                    AS total,
                ROUND(AVG(opportunity_score)::numeric, 4)  AS mean_score,
                ROUND(MIN(opportunity_score)::numeric, 4)  AS min_score,
                ROUND(MAX(opportunity_score)::numeric, 4)  AS max_score,
                COUNT(*) FILTER (WHERE opportunity_score > 0.7) AS high_opportunity
            FROM model_scores
            WHERE model_version = :v
        """), {"v": MODEL_VERSION}).fetchone()

    logger.info("─" * 50)
    logger.info(f"MODEL SCORES SUMMARY (version={MODEL_VERSION})")
    logger.info(f"  Total scored:      {row[0]:,}")
    logger.info(f"  Mean opp. score:   {row[1]}")
    logger.info(f"  Score range:       [{row[2]}, {row[3]}]")
    logger.info(f"  High opp (>0.7):   {row[4]:,}")
    logger.info("─" * 50)


def main(dry_run: bool = False, profile_name: str = None) -> None:
    from src.scoring.scoring_profile import ScoringProfile, compute_profile_score

    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info("=" * 60)
    logger.info(f"OPPORTUNITY SCORE — START (version={MODEL_VERSION})")
    logger.info("=" * 60)

    # Load scoring profile
    profile = ScoringProfile.from_env() if not profile_name else ScoringProfile.from_name(profile_name)
    logger.info(f"\n{profile.summary()}")

    # Load model
    model, encoders, meta = load_model()
    logger.info(f"Model loaded. RMSE: {meta.get('metrics', {}).get('rmse_pct_of_median', 'N/A')}%")

    # Load base data
    base_df = load_training_data(engine)
    if base_df.empty:
        logger.error("No data. Run ingestion and feature engineering first.")
        sys.exit(1)

    # Enrich with commune context (crime_index, census, growth) if profile needs it
    _commune_dims = {"crime_index", "census_score", "growth_score", "location_score"}
    if _commune_dims & set(profile.weights.keys()):
        try:
            from src.features.commune_context import enrich_with_commune_context
            logger.info("Enriching base data with commune context (crime, INE census)...")
            base_df = enrich_with_commune_context(base_df)
        except Exception as e:
            logger.warning(f"Could not enrich with commune context: {e}. Continuing without enrichment.")

    # Undervaluation scores
    logger.info("Computing undervaluation scores...")
    uv_df = uv_module.run(engine=engine)

    # SHAP explanations
    logger.info("Computing SHAP explanations...")
    shap_df = shap_explainer.run(base_df, model=model, encoders=encoders)

    # Build final scores DataFrame (uses profile for opportunity_score)
    scores_df = build_model_scores_df(uv_df, shap_df, base_df)

    # Apply scoring profile (replaces simple weighted formula)
    scores_df = compute_profile_score(scores_df, profile)

    # Write to DB
    n = write_scores(scores_df, engine, dry_run=dry_run)

    if not dry_run:
        print_summary(engine)

    logger.info("=" * 60)
    logger.info(f"OPPORTUNITY SCORE — COMPLETE ({n:,} rows | profile={profile.name})")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--profile",  type=str, default=None,
                        help="Scoring profile: default, location, growth, liquidity, safety")
    args = parser.parse_args()
    main(dry_run=args.dry_run, profile_name=args.profile)
