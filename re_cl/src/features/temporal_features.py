"""
temporal_features.py
--------------------
Computes temporal features for the hedonic model:
  - quarter_q{1,2,3,4}: one-hot dummies for fiscal quarter
  - season_index: continuous [0.0, 0.333, 0.667, 1.0] for Q1-Q4

Note: Dataset covers 2013-2014 only (~2 years), so complex lag/trend features
are not reliable. Simple quarter encoding is sufficient for the MVP.
"""

import os

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine

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


def compute_temporal_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds quarter dummy columns and season_index.

    season_index formula: (quarter - 1) / 3.0
      Q1 → 0.000
      Q2 → 0.333
      Q3 → 0.667
      Q4 → 1.000
    """
    df = df.copy()

    for q in range(1, 5):
        df[f"quarter_q{q}"] = (df["quarter"] == q).astype("int8")

    df["season_index"] = ((df["quarter"] - 1) / 3.0).round(6)

    # Validate: each row sums to 1 across dummies (sanity check)
    dummy_cols = [f"quarter_q{q}" for q in range(1, 5)]
    bad_rows = (df[dummy_cols].sum(axis=1) != 1).sum()
    if bad_rows > 0:
        logger.warning(f"{bad_rows} rows have quarter dummy sum != 1 (null or out-of-range quarter)")

    logger.info(
        f"Temporal features computed: {len(df):,} rows, "
        f"season_index range [{df['season_index'].min():.3f}, {df['season_index'].max():.3f}]"
    )
    return df


def run(engine=None) -> pd.DataFrame:
    """
    Reads transactions_clean from DB, computes temporal features, returns DataFrame.
    Called by build_features.py.
    """
    if engine is None:
        engine = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info("Loading transactions_clean for temporal features...")
    query = """
        SELECT id, quarter, year
        FROM transactions_clean
        WHERE is_outlier = FALSE AND quarter BETWEEN 1 AND 4
    """
    df = pd.read_sql(query, engine)
    logger.info(f"  {len(df):,} rows loaded")

    df = compute_temporal_features(df)
    return df[["id", "quarter_q1", "quarter_q2", "quarter_q3", "quarter_q4", "season_index"]]
