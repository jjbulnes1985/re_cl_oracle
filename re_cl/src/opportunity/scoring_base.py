"""
scoring_base.py
---------------
Base opportunity scoring for all property types (use_case='as_is').

Computes undervaluation_score, location_score, growth_score, confidence
and combines them per investor_profile weights.

Reuses transaction_features and commune context already in the DB.

Run:
  py src/opportunity/scoring_base.py
  py src/opportunity/scoring_base.py --profile value
  py src/opportunity/scoring_base.py --commune Maipu --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()

MODEL_VERSION = "v1.0"

INVESTOR_PROFILES = {
    "value": {
        "undervaluation": 0.65,
        "confidence": 0.20,
        "location": 0.15,
        "growth": 0.00,
        "yield": 0.00,
        "redevelopment": 0.00,
    },
    "growth": {
        "undervaluation": 0.40,
        "growth": 0.40,
        "confidence": 0.20,
        "location": 0.00,
        "yield": 0.00,
        "redevelopment": 0.00,
    },
    "redevelopment": {
        "undervaluation": 0.30,
        "redevelopment": 0.50,
        "confidence": 0.20,
        "location": 0.00,
        "growth": 0.00,
        "yield": 0.00,
    },
    "income": {
        "undervaluation": 0.30,
        "yield": 0.50,
        "confidence": 0.20,
        "location": 0.00,
        "growth": 0.00,
        "redevelopment": 0.00,
    },
}


def _build_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    return "postgresql://{user}:{pwd}@{host}:{port}/{db}".format(
        user=os.getenv("POSTGRES_USER", "re_cl_user"),
        pwd=os.getenv("POSTGRES_PASSWORD", ""),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        db=os.getenv("POSTGRES_DB", "re_cl"),
    )


def load_candidate_features(engine, commune: Optional[str] = None) -> pd.DataFrame:
    """Join opportunity.candidates with transaction_features and commune context."""
    filters = ""
    params: dict = {}
    if commune:
        filters = "AND oc.county_name = :commune"
        params["commune"] = commune

    query = text(f"""
        SELECT
            oc.id                    AS candidate_id,
            oc.county_name,
            oc.property_type_code,
            oc.surface_land_m2,
            oc.surface_building_m2,
            oc.construction_ratio,
            oc.is_eriazo,
            oc.last_transaction_uf,
            -- From transaction_features (joined via source_id)
            tf.gap_pct,
            tf.data_confidence,
            tf.dist_km_centroid,
            tf.cluster_id,
            -- From valuation (triangulated estimate)
            v.estimated_uf,
            v.p25_uf,
            v.p75_uf,
            v.confidence             AS valuation_confidence,
            -- Commune context
            cs.growth_index,
            cs.crime_index,
            cs.densidad_pob
        FROM opportunity.candidates oc
        -- Join to transactions_clean via source_id for CBR rows
        LEFT JOIN transactions_clean tc
            ON oc.source = 'cbr_transaction' AND oc.source_id = tc.id::TEXT
        -- Join to transaction_features
        LEFT JOIN transaction_features tf ON tf.clean_id = tc.id
        -- Join to triangulated valuation
        LEFT JOIN opportunity.valuations v
            ON v.candidate_id = oc.id AND v.method = 'triangulated'
        -- Commune stats
        LEFT JOIN commune_stats cs ON cs.county_name = oc.county_name
        WHERE 1=1 {filters}
        ORDER BY oc.id
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params=params)

    logger.info(f"  Loaded {len(df):,} candidates with features")
    return df


def compute_undervaluation_score(df: pd.DataFrame) -> pd.Series:
    """Score based on gap_pct: how much below market is this property?"""
    gap = df["gap_pct"].copy()

    # Fill missing gap_pct with valuation-based gap
    mask_no_gap = gap.isna() & df["last_transaction_uf"].notna() & df["estimated_uf"].notna()
    surface = df["surface_building_m2"].fillna(df["surface_land_m2"]).fillna(80.0)
    if mask_no_gap.any():
        actual_uf_m2 = df["last_transaction_uf"] / surface.clip(lower=1)
        est_uf_m2 = df["estimated_uf"] / surface.clip(lower=1)
        gap.loc[mask_no_gap] = (actual_uf_m2 - est_uf_m2) / est_uf_m2.clip(lower=1)

    # Winsorize extremes
    gap = gap.clip(lower=-1.0, upper=0.5)

    # Score: negative gap (undervalued) → high score
    # gap=-1.0 → score=1.0; gap=0.0 → score=0.5; gap=0.5 → score=0.0
    score = 0.5 - gap / 2.0
    score = score.fillna(0.5)
    return score.clip(0, 1).rename("undervaluation_score")


def compute_location_score(df: pd.DataFrame) -> pd.Series:
    """Score based on distance to centroid (accessibility)."""
    dist = df["dist_km_centroid"].copy().fillna(df["dist_km_centroid"].median())
    # Normalize: 0km → 1.0; 20km → 0.0
    score = 1.0 - (dist / 20.0).clip(0, 1)
    return score.fillna(0.5).rename("location_score")


def compute_growth_score(df: pd.DataFrame) -> pd.Series:
    """Score based on commune growth index."""
    growth = df["growth_index"].copy()
    if growth.isna().all():
        return pd.Series(0.5, index=df.index, name="growth_score")
    gmin, gmax = growth.quantile(0.05), growth.quantile(0.95)
    score = (growth - gmin) / max(gmax - gmin, 0.01)
    return score.fillna(0.5).clip(0, 1).rename("growth_score")


def compute_redevelopment_score(df: pd.DataFrame) -> pd.Series:
    """Score for redesarrollo potential: eriazo + low construction ratio + good location."""
    eriazo = df["is_eriazo"].fillna(False).astype(float)
    ratio = df["construction_ratio"].fillna(0.5).clip(0, 1)
    low_build = 1.0 - ratio  # low construction → high redevelopment potential
    score = eriazo * 0.5 + low_build * 0.3 + 0.2
    return score.clip(0, 1).rename("redevelopment_score")


def compute_opportunity_score(df: pd.DataFrame, profile: str) -> pd.DataFrame:
    """Compute all component scores and weighted opportunity_score."""
    weights = INVESTOR_PROFILES.get(profile, INVESTOR_PROFILES["value"])

    df = df.copy()
    df["undervaluation_score"] = compute_undervaluation_score(df)
    df["location_score"]       = compute_location_score(df)
    df["growth_score"]         = compute_growth_score(df)
    df["redevelopment_score"]  = compute_redevelopment_score(df)
    df["confidence"]           = df["data_confidence"].fillna(df["valuation_confidence"]).fillna(0.5).clip(0, 1)
    df["yield_score"]          = 0.5  # placeholder — requires NOI data
    df["liquidity_score"]      = 0.5  # placeholder

    df["opportunity_score"] = (
        df["undervaluation_score"] * weights["undervaluation"] +
        df["location_score"]       * weights["location"] +
        df["growth_score"]         * weights["growth"] +
        df["redevelopment_score"]  * weights["redevelopment"] +
        df["confidence"]           * weights["confidence"] +
        df["yield_score"]          * weights["yield"]
    ).clip(0, 1)

    # Top drivers (top 3 contributing components)
    component_cols = [
        ("undervaluation_score", weights["undervaluation"]),
        ("location_score",       weights["location"]),
        ("growth_score",         weights["growth"]),
        ("redevelopment_score",  weights["redevelopment"]),
        ("confidence",           weights["confidence"]),
    ]

    def top_drivers(row):
        contributions = [
            {"factor": col, "score": round(float(row[col]), 3), "weight": w, "contribution": round(float(row[col]) * w, 3)}
            for col, w in component_cols if w > 0
        ]
        contributions.sort(key=lambda x: x["contribution"], reverse=True)
        return json.dumps(contributions[:3])

    df["drivers"] = df.apply(top_drivers, axis=1)

    return df


def write_scores(engine, df: pd.DataFrame, profile: str, dry_run: bool = False) -> int:
    """Write scores to opportunity.scores."""
    if dry_run:
        logger.info(f"  [DRY RUN] Would write {len(df):,} scores (profile={profile})")
        return 0

    # Delete existing scores for this profile/version before re-insert
    with engine.begin() as conn:
        deleted = conn.execute(text("""
            DELETE FROM opportunity.scores
            WHERE use_case = 'as_is' AND investor_profile = :profile AND model_version = :ver
        """), {"profile": profile, "ver": MODEL_VERSION}).rowcount
    if deleted:
        logger.info(f"  Deleted {deleted:,} existing scores for profile={profile}")

    insert_sql = text("""
        INSERT INTO opportunity.scores
            (candidate_id, use_case, investor_profile, model_version,
             undervaluation_score, location_score, growth_score, redevelopment_score,
             liquidity_score, confidence, opportunity_score, drivers)
        VALUES
            (:candidate_id, 'as_is', :investor_profile, :model_version,
             :undervaluation_score, :location_score, :growth_score, :redevelopment_score,
             :liquidity_score, :confidence, :opportunity_score, :drivers::jsonb)
        ON CONFLICT (candidate_id, use_case, investor_profile, model_version) DO UPDATE SET
            opportunity_score = EXCLUDED.opportunity_score,
            undervaluation_score = EXCLUDED.undervaluation_score,
            drivers = EXCLUDED.drivers
    """)

    rows = df[[
        "candidate_id", "undervaluation_score", "location_score", "growth_score",
        "redevelopment_score", "confidence", "opportunity_score", "drivers"
    ]].copy()
    rows["investor_profile"] = profile
    rows["model_version"]    = MODEL_VERSION
    rows["liquidity_score"]  = 0.5

    written = 0
    batch_size = 5000
    for start in range(0, len(rows), batch_size):
        batch = rows.iloc[start:start + batch_size]
        with engine.begin() as conn:
            for _, r in batch.iterrows():
                conn.execute(insert_sql, r.to_dict())
        written += len(batch)

    return written


def main():
    parser = argparse.ArgumentParser(description="Base opportunity scoring for all property types")
    parser.add_argument("--profile", default="value", choices=list(INVESTOR_PROFILES.keys()))
    parser.add_argument("--commune", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    engine = create_engine(_build_db_url(), pool_pre_ping=True, pool_size=5)

    logger.info("=" * 60)
    logger.info(f"SCORING BASE — profile={args.profile}")
    logger.info("=" * 60)

    df = load_candidate_features(engine, commune=args.commune)
    df_scored = compute_opportunity_score(df, args.profile)

    logger.info(f"  Score distribution:")
    logger.info(f"    score>=0.8: {(df_scored['opportunity_score']>=0.8).sum():,}")
    logger.info(f"    score>=0.7: {(df_scored['opportunity_score']>=0.7).sum():,}")
    logger.info(f"    score>=0.5: {(df_scored['opportunity_score']>=0.5).sum():,}")
    logger.info(f"    mean: {df_scored['opportunity_score'].mean():.3f}")

    n = write_scores(engine, df_scored, args.profile, dry_run=args.dry_run)

    logger.info(f"DONE: {n:,} scores written (profile={args.profile})")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
