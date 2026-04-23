"""
undervaluation.py
-----------------
Computes undervaluation score from hedonic model predictions.

undervaluation_score:
  - Uses gap_pct = (real_value_uf - predicted_value_uf) / predicted_value_uf
  - Converts to percentile rank within (project_type, year) group
  - Inverts: low percentile (bought below predicted) → high score
  - Output range: [0.0, 1.0]  (1.0 = most undervalued)

gap_percentile:
  - Raw percentile rank of actual_uf_m2 vs predicted_uf_m2 in its peer group
  - 0 = cheapest relative to model, 100 = most expensive

Also computes predicted_uf_m2 for all records using the saved hedonic model.
"""

import os
import sys

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.models.hedonic_model import load_model, predict, load_training_data, preprocess, CAT_FEATURES, NUM_FEATURES


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


def compute_predictions(df: pd.DataFrame, model, encoders: dict) -> pd.DataFrame:
    """
    Adds predicted_uf_m2 column using the hedonic model.
    Rows without required features get NaN.
    """
    df = df.copy()
    df["predicted_uf_m2"] = np.nan

    # Only predict where we have enough features
    required = ["project_type", "county_name", "year", "quarter"]
    has_features = df[required].notna().all(axis=1)

    if has_features.sum() == 0:
        logger.warning("No rows have sufficient features for prediction")
        return df

    sub = df.loc[has_features].copy()
    preds = predict(sub, model, encoders)
    df.loc[has_features, "predicted_uf_m2"] = preds

    logger.info(
        f"Predictions: {has_features.sum():,}/{len(df):,} rows. "
        f"Mean predicted: {np.nanmean(preds):.2f} UF/m²"
    )
    return df


def compute_gap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes gap between actual and predicted UF/m²:
      gap_pct = (actual_uf_m2 - predicted_uf_m2) / predicted_uf_m2

    Negative gap_pct → transacted BELOW model value → potential undervaluation.
    """
    df = df.copy()
    df["actual_uf_m2"] = df["uf_m2_building"]

    valid = (
        df["actual_uf_m2"].notna() &
        df["predicted_uf_m2"].notna() &
        (df["predicted_uf_m2"] > 0)
    )
    df["gap_pct"] = np.nan
    df.loc[valid, "gap_pct"] = (
        (df.loc[valid, "actual_uf_m2"] - df.loc[valid, "predicted_uf_m2"])
        / df.loc[valid, "predicted_uf_m2"]
    )
    return df


def compute_undervaluation_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Converts gap_pct to undervaluation_score [0, 1] using peer-group percentile rank.

    Within each (project_type, year) group:
      - gap_percentile = percentile rank of gap_pct (0 = lowest gap = most undervalued)
      - undervaluation_score = 1 - (gap_percentile / 100)

    Result: score 1.0 means cheapest vs model in its peer group.
    """
    df = df.copy()
    df["gap_percentile"]       = np.nan
    df["undervaluation_score"] = np.nan

    for (ptype, year), grp in df.groupby(["project_type", "year"]):
        valid_idx = grp["gap_pct"].dropna().index
        if len(valid_idx) < 5:
            continue

        # Percentile rank: 0 = lowest gap_pct (most undervalued), 100 = highest
        pct_rank = grp.loc[valid_idx, "gap_pct"].rank(pct=True) * 100
        df.loc[valid_idx, "gap_percentile"]       = pct_rank.round(2)
        df.loc[valid_idx, "undervaluation_score"] = (1 - pct_rank / 100).round(4)

    n_scored = df["undervaluation_score"].notna().sum()
    logger.info(
        f"Undervaluation scores: {n_scored:,} rows. "
        f"Mean score: {df['undervaluation_score'].mean():.4f}"
    )
    return df


def run(engine=None) -> pd.DataFrame:
    """
    Full undervaluation pipeline:
      1. Load data from DB
      2. Predict with hedonic model
      3. Compute gap and percentile scores
    Returns DataFrame with: id, predicted_uf_m2, actual_uf_m2, gap_pct, gap_percentile, undervaluation_score
    """
    if engine is None:
        engine = create_engine(_build_db_url(), pool_pre_ping=True)

    model, encoders, _ = load_model()
    df = load_training_data(engine)

    df = compute_predictions(df, model, encoders)
    df = compute_gap(df)
    df = compute_undervaluation_score(df)

    return df[["id", "predicted_uf_m2", "actual_uf_m2",
               "gap_pct", "gap_percentile", "undervaluation_score"]]
