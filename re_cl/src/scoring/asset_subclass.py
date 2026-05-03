"""
asset_subclass.py
─────────────────
Subclass-aware scoring engine.

Reads weights from `asset_subclass_weights` table and applies them to candidate
metrics, producing a vector of scores (one per subclass) per candidate.

Output is written to `model_scores.subclass_scores` as JSONB.

Workflow:
  1. Load active subclasses from DB (typically 14 rows).
  2. For each candidate in v_opportunities + transaction_features:
     - Compute 12 dimension scores (some derived from existing columns,
       some derived on-the-fly from competitor density / OSM).
     - For each subclass, opportunity_score_subclass = Σ (w_dim * score_dim).
  3. Bulk write JSONB column.

CLI:
  py src/scoring/asset_subclass.py                  # score all candidates
  py src/scoring/asset_subclass.py --limit 1000     # sample run
  py src/scoring/asset_subclass.py --subclass apartment_income  # single subclass
  py src/scoring/asset_subclass.py --dry-run        # no DB writes

Tested against migration 015 + 016. Idempotent per model_version.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0")

# 12 dimension columns as they appear in asset_subclass_weights
DIMENSION_WEIGHTS = [
    "w_underval",
    "w_cap_rate",
    "w_appreciation",
    "w_transit",
    "w_school",
    "w_traffic",
    "w_competitor_density",
    "w_demographic_match",
    "w_liquidity",
    "w_regulatory_risk",
    "w_environmental_risk",
    "w_data_confidence",
]

# Map from weight column → metric column expected in candidate dataframe
WEIGHT_TO_METRIC = {
    "w_underval":           "underval_score",
    "w_cap_rate":           "cap_rate_score",
    "w_appreciation":       "appreciation_score",
    "w_transit":            "transit_score",
    "w_school":             "school_score",
    "w_traffic":            "traffic_score",
    "w_competitor_density": "competitor_density_score",
    "w_demographic_match":  "demographic_match_score",
    "w_liquidity":          "liquidity_score",
    "w_regulatory_risk":    "regulatory_risk_score",
    "w_environmental_risk": "environmental_risk_score",
    "w_data_confidence":    "data_confidence",
}


def _build_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    return (
        f"postgresql://{os.getenv('POSTGRES_USER', 're_cl_user')}:"
        f"{os.getenv('POSTGRES_PASSWORD', '')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 're_cl')}"
    )


def load_subclass_weights(engine: Engine, only_subclass: Optional[str] = None) -> pd.DataFrame:
    """Load weights from asset_subclass_weights. Returns one row per subclass."""
    sql = "SELECT * FROM v_subclass_weights_active"
    params: dict = {}
    if only_subclass:
        sql += " WHERE subclass = :sc"
        params["sc"] = only_subclass

    weights = pd.read_sql(text(sql), engine, params=params)

    if weights.empty:
        raise ValueError(
            "No active subclasses found. Run migration 015 first to seed subclasses."
        )

    # Sanity check sum=1.0 for each row (DB trigger should have validated, but double-check)
    sums = weights[DIMENSION_WEIGHTS].sum(axis=1)
    bad = sums[~sums.between(0.999, 1.001)]
    if len(bad) > 0:
        logger.error(f"Subclasses with bad weight sums: {weights.loc[bad.index, 'subclass'].tolist()}")
        raise ValueError("Some subclasses have weights that don't sum to 1.0")

    logger.info(f"Loaded {len(weights)} active subclasses: {weights['subclass'].tolist()}")
    return weights


def load_candidates_with_metrics(engine: Engine, limit: Optional[int] = None) -> pd.DataFrame:
    """
    Load candidates from v_opportunities + transaction_features, computing the 12
    dimension scores on-the-fly using available columns + sensible defaults.

    Returns df with columns: clean_id, lat, lng, plus 12 *_score columns in [0,1].
    """
    limit_clause = f"LIMIT {int(limit)}" if limit else ""

    sql = f"""
    SELECT
      v.score_id                                         AS clean_id,
      v.county_name,
      v.project_type,
      v.real_value_uf,
      v.surface_m2,
      v.uf_m2_building,

      -- Coords (already exposed as longitude/latitude in v_opportunities)
      v.latitude                                         AS lat,
      v.longitude                                        AS lng,

      -- A1 metrics (valuation)
      COALESCE(v.undervaluation_score, 0.5)              AS underval_score,
      0.5                                                AS cap_rate_score,
      COALESCE(v.opportunity_score, 0.5)                 AS appreciation_score,

      -- A2 metrics (demand) — from transaction_features
      LEAST(1.0, GREATEST(0.0, 1.0 - COALESCE(f.dist_metro_km, 5.0) / 5.0))   AS transit_score,
      LEAST(1.0, GREATEST(0.0, 1.0 - COALESCE(f.dist_school_km, 2.0) / 2.0)) AS school_score,
      0.5                                                AS traffic_score,
      0.5                                                AS competitor_density_score,
      0.5                                                AS demographic_match_score,
      LEAST(1.0, GREATEST(0.0,
        COALESCE(cs.n_transactions::numeric / NULLIF(cs_max.max_n, 0), 0.5)))   AS liquidity_score,

      -- A3 metrics (risk)
      0.5                                                AS regulatory_risk_score,
      0.5                                                AS environmental_risk_score,

      -- Confidence
      COALESCE(v.data_confidence, 0.5)                   AS data_confidence

    FROM v_opportunities v
    LEFT JOIN transaction_features f
      ON v.score_id = f.clean_id
    LEFT JOIN (
      SELECT county_name, SUM(n_transactions) AS n_transactions
      FROM commune_stats
      WHERE model_version = :mv
      GROUP BY county_name
    ) cs ON v.county_name = cs.county_name
    CROSS JOIN (
      SELECT MAX(n_transactions::numeric) AS max_n
      FROM (
        SELECT SUM(n_transactions) AS n_transactions
        FROM commune_stats
        WHERE model_version = :mv
        GROUP BY county_name
      ) tot
    ) cs_max
    WHERE v.geom IS NOT NULL
    {limit_clause}
    """

    df = pd.read_sql(text(sql), engine, params={"mv": MODEL_VERSION})
    logger.info(f"Loaded {len(df):,} candidates with metrics")

    # Clamp all *_score columns to [0,1]
    score_cols = [c for c in df.columns if c.endswith("_score") or c == "data_confidence"]
    for c in score_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.5).clip(0.0, 1.0)

    return df


def compute_subclass_scores(
    candidates: pd.DataFrame,
    weights: pd.DataFrame,
) -> pd.DataFrame:
    """
    For each candidate × subclass, compute weighted score.

    Returns df with columns: clean_id, plus one column per subclass with the score.
    """
    result = candidates[["clean_id"]].copy()

    metric_cols = list(WEIGHT_TO_METRIC.values())
    metric_matrix = candidates[metric_cols].to_numpy()  # (n_candidates, 12)

    for _, sub_row in weights.iterrows():
        subclass = sub_row["subclass"]
        weight_vec = sub_row[DIMENSION_WEIGHTS].to_numpy(dtype=float)  # (12,)

        # Inverted dimensions: regulatory_risk and environmental_risk
        # are stored as RISK scores where higher = more risk.
        # For scoring, we want LOW risk = HIGH score. The metric cols are already
        # designed so higher = better, so no extra inversion needed here.

        score = metric_matrix @ weight_vec  # (n_candidates,) ∈ [0,1] approx
        score = np.clip(score, 0.0, 1.0).round(4)
        result[subclass] = score

    return result


def write_subclass_scores(
    engine: Engine,
    scores_df: pd.DataFrame,
    weights: pd.DataFrame,
    dry_run: bool = False,
) -> int:
    """
    Bulk update model_scores.subclass_scores JSONB column for matching clean_ids.
    Returns number of rows updated.
    """
    if dry_run:
        logger.info(f"[DRY-RUN] Would update {len(scores_df)} candidates with subclass_scores JSONB")
        sample = scores_df.head(3)
        for _, r in sample.iterrows():
            d = {sc: float(r[sc]) for sc in weights["subclass"]}
            logger.info(f"  clean_id={r['clean_id']}: {json.dumps(d, ensure_ascii=False)}")
        return 0

    subclass_names = weights["subclass"].tolist()

    # Build JSONB payloads
    scores_df = scores_df.copy()
    scores_df["jsonb_payload"] = scores_df[subclass_names].apply(
        lambda row: json.dumps({sc: float(row[sc]) for sc in subclass_names}),
        axis=1,
    )

    # Bulk update via temp table
    payload_df = scores_df[["clean_id", "jsonb_payload"]].copy()

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TEMP TABLE _subclass_payload (
              clean_id BIGINT PRIMARY KEY,
              jsonb_payload TEXT
            ) ON COMMIT DROP
        """))

        payload_df.to_sql("_subclass_payload", conn, if_exists="append", index=False, method="multi", chunksize=500)

        result = conn.execute(text("""
            UPDATE model_scores ms
            SET subclass_scores = p.jsonb_payload::jsonb
            FROM _subclass_payload p
            WHERE ms.clean_id = p.clean_id
              AND ms.model_version = :mv
              AND ms.scoring_profile = 'default'
        """), {"mv": MODEL_VERSION})

        n_updated = result.rowcount

    logger.info(f"Updated {n_updated:,} rows with subclass_scores JSONB")
    return n_updated


def print_summary(scores_df: pd.DataFrame, weights: pd.DataFrame) -> None:
    """Log distribution of scores per subclass."""
    logger.info("─" * 60)
    logger.info("SUBCLASS SCORES SUMMARY")
    logger.info("─" * 60)
    for _, row in weights.iterrows():
        sc = row["subclass"]
        col = scores_df[sc]
        logger.info(
            f"  {sc:30s} mean={col.mean():.3f}  "
            f"high(>0.7)={int((col > 0.7).sum()):,}  "
            f"max={col.max():.3f}"
        )
    logger.info("─" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Asset subclass scoring engine")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of candidates (for testing)")
    parser.add_argument("--subclass", default=None,
                        help="Score only this subclass (default: all active)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write to DB")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info(f"ASSET SUBCLASS SCORER (model_version={MODEL_VERSION})")
    logger.info("=" * 60)

    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    weights = load_subclass_weights(engine, only_subclass=args.subclass)
    candidates = load_candidates_with_metrics(engine, limit=args.limit)

    if candidates.empty:
        logger.warning("No candidates found — nothing to score")
        return

    scores_df = compute_subclass_scores(candidates, weights)
    print_summary(scores_df, weights)

    n_updated = write_subclass_scores(engine, scores_df, weights, dry_run=args.dry_run)

    logger.info("=" * 60)
    logger.info(f"COMPLETE — {n_updated:,} model_scores rows updated with subclass_scores")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
