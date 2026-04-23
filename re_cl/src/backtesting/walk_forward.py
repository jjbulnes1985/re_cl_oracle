"""
walk_forward.py
---------------
V4.5 — Walk-forward backtesting for the RE_CL hedonic model.

Validates the XGBoost model trained on CBR 2013-2014 data via:

  1. Temporal split        — Train 2013, test 2014. Full metrics + breakdown
                            by quarter, county, and project type.
  2. Quarterly rolling     — Train on t-1 quarters, predict quarter t.
                            Detects drift (are errors improving or worsening?).
  3. Undervaluation signal — Checks whether gap_pct is a real signal by
                            comparing model errors for top vs bottom decile
                            opportunity-score properties.
  4. Commune calibration   — Per-commune predicted vs actual median UF/m².
                            Identifies where the model is systematically biased.
  5. OLS benchmark         — Simple log-linear OLS (mirrors the 2017 MIT thesis
                            methodology) for comparison with XGBoost.

Output:
  data/exports/backtesting_report.json   — Full JSON report
  data/exports/commune_calibration.csv   — Per-commune calibration table
  Stdout                                 — Markdown summary tables

CLI:
  python src/backtesting/walk_forward.py              # All backtests
  python src/backtesting/walk_forward.py --temporal-only
  python src/backtesting/walk_forward.py --commune
  python src/backtesting/walk_forward.py --ols
  python src/backtesting/walk_forward.py --rolling
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import LabelEncoder
from sqlalchemy import create_engine
import xgboost as xgb

warnings.filterwarnings("ignore", category=FutureWarning)

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent.parent          # re_cl/
EXPORTS_DIR = _ROOT / "data" / "exports"
REPORT_PATH = EXPORTS_DIR / "backtesting_report.json"
CALIBRATION_PATH = EXPORTS_DIR / "commune_calibration.csv"

# ── Model feature config (mirrors hedonic_model.py) ──────────────────────────
CAT_FEATURES = ["project_type", "county_name"]
NUM_FEATURES = [
    "year", "quarter", "season_index",
    "surface_m2", "surface_building_m2", "surface_land_m2",
    "dist_km_centroid", "cluster_id", "data_confidence",
    "price_percentile_50",
]
TARGET = "uf_m2_building"
TARGET_WINSOR = (0.01, 0.99)

# ── XGBoost hyperparameters (same as hedonic_model.py) ───────────────────────
XGB_PARAMS = dict(
    n_estimators=400,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=5,
    reg_alpha=0.1,
    reg_lambda=1.0,
    random_state=42,
    n_jobs=-1,
    tree_method="hist",
)


# ── DB helpers ─────────────────────────────────────────────────────────────────

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


def _load_data(engine) -> pd.DataFrame:
    """
    Pull the joined transactions_clean + transaction_features dataset.
    Mirrors load_training_data() from hedonic_model.py but also includes
    gap_pct for the undervaluation signal test.
    """
    logger.info("Loading data from DB...")
    query = """
        SELECT
            tc.id,
            tc.project_type,
            tc.county_name,
            tc.year,
            tc.quarter,
            tc.uf_m2_building,
            tc.surface_m2,
            tc.surface_building_m2,
            tc.surface_land_m2,
            tc.data_confidence,
            tf.gap_pct,
            tf.price_percentile_50,
            tf.dist_km_centroid,
            tf.cluster_id,
            tf.season_index
        FROM transactions_clean tc
        JOIN transaction_features tf ON tf.clean_id = tc.id
        WHERE tc.is_outlier = FALSE
          AND tc.has_valid_price = TRUE
          AND tc.uf_m2_building IS NOT NULL
          AND tc.uf_m2_building > 0
        ORDER BY tc.year, tc.quarter
    """
    df = pd.read_sql(query, engine)
    logger.info(f"  Loaded {len(df):,} rows — years: {sorted(df['year'].unique())}")
    return df


# ── Preprocessing helper ───────────────────────────────────────────────────────

def _preprocess(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Fits LabelEncoders on train, applies to test (unseen labels -> 'unknown').
    Winsorizes target on train. Imputes numeric NULLs with train medians.
    Returns (df_train_proc, df_test_proc, encoders).
    """
    df_train = df_train.copy()
    df_test  = df_test.copy()

    # Winsorize target on train
    p_low  = df_train[TARGET].quantile(TARGET_WINSOR[0])
    p_high = df_train[TARGET].quantile(TARGET_WINSOR[1])
    df_train[TARGET] = df_train[TARGET].clip(p_low, p_high)

    # Encode categoricals
    encoders = {}
    for col in CAT_FEATURES:
        le = LabelEncoder()
        df_train[col] = le.fit_transform(df_train[col].astype(str).fillna("unknown"))
        known = set(le.classes_)
        df_test[col]  = df_test[col].astype(str).fillna("unknown")
        df_test[col]  = df_test[col].apply(lambda x: x if x in known else "unknown")
        if "unknown" not in known:
            le.classes_ = np.append(le.classes_, "unknown")
        df_test[col] = le.transform(df_test[col])
        encoders[col] = le

    # Impute numerics with train medians
    for col in NUM_FEATURES:
        if col in df_train.columns:
            med = df_train[col].median()
            fill = med if not np.isnan(med) else 0.0
            df_train[col] = df_train[col].fillna(fill)
            df_test[col]  = df_test[col].fillna(fill)

    return df_train, df_test, encoders


def _feature_cols(df: pd.DataFrame) -> list[str]:
    return CAT_FEATURES + [f for f in NUM_FEATURES if f in df.columns]


def _metrics(y_true: np.ndarray, y_pred: np.ndarray, label: str = "") -> dict:
    """Compute RMSE, MAE, R², and RMSE as % of median."""
    if len(y_true) < 5:
        return {"n": len(y_true), "rmse": None, "mae": None, "r2": None,
                "rmse_pct_median": None, "label": label}
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    mae  = float(mean_absolute_error(y_true, y_pred))
    r2   = float(r2_score(y_true, y_pred))
    med  = float(np.median(y_true))
    rmse_pct = round(rmse / med * 100, 2) if med > 0 else None
    return {
        "label": label,
        "n": int(len(y_true)),
        "rmse": round(rmse, 4),
        "mae":  round(mae, 4),
        "r2":   round(r2, 4),
        "rmse_pct_median": rmse_pct,
        "actual_median": round(med, 4),
    }


def _train_xgb(X_train, y_train, X_val=None, y_val=None):
    """Fit an XGBoost model. Optional eval set for early stopping info."""
    model = xgb.XGBRegressor(**XGB_PARAMS)
    eval_set = [(X_val, y_val)] if X_val is not None else None
    model.fit(X_train, y_train, eval_set=eval_set, verbose=False)
    return model


# ── 1. Temporal split ─────────────────────────────────────────────────────────

def run_temporal_split(engine) -> dict:
    """
    Train on all 2013 data. Test on all 2014 data.

    Returns a dict with:
      - overall RMSE/MAE/R²
      - by_quarter: metrics per Q1-Q4 of 2014
      - by_county:  metrics per county_name in 2014
      - by_type:    metrics per project_type in 2014
    """
    logger.info("=" * 60)
    logger.info("BACKTEST 1: Temporal split (train 2013 ->test 2014)")
    df = _load_data(engine)

    train_mask = df["year"] == 2013
    test_mask  = df["year"] == 2014

    df_train = df[train_mask].copy()
    df_test  = df[test_mask].copy()

    if df_train.empty or df_test.empty:
        logger.error("Not enough data for temporal split (need 2013 AND 2014 rows)")
        return {"error": "insufficient_data"}

    logger.info(f"  Train (2013): {len(df_train):,} | Test (2014): {len(df_test):,}")

    df_train_p, df_test_p, _ = _preprocess(df_train, df_test)
    feat_cols = _feature_cols(df_train_p)

    X_train = df_train_p[feat_cols]
    y_train = df_train_p[TARGET]
    X_test  = df_test_p[feat_cols]
    y_test  = df_test_p[TARGET].values

    model = _train_xgb(X_train, y_train, X_test, y_test)
    y_pred = model.predict(X_test)

    overall = _metrics(y_test, y_pred, "train_2013_test_2014")

    # Breakdown by quarter (2014)
    by_quarter = []
    for q in sorted(df_test["quarter"].unique()):
        mask = (df_test_p["quarter"] == q).values
        if mask.sum() < 5:
            continue
        by_quarter.append(_metrics(y_test[mask], y_pred[mask], f"Q{int(q)}"))

    # Breakdown by county_name (original, before encoding)
    by_county = []
    county_orig = df_test["county_name"].values
    for county in sorted(df_test["county_name"].unique()):
        mask = county_orig == county
        if mask.sum() < 10:
            continue
        by_county.append(_metrics(y_test[mask], y_pred[mask], county))
    by_county.sort(key=lambda x: (x["rmse"] or 99999), reverse=True)

    # Breakdown by project_type (original, before encoding)
    by_type = []
    type_orig = df_test["project_type"].values
    for pt in sorted(df_test["project_type"].unique()):
        mask = type_orig == pt
        if mask.sum() < 10:
            continue
        by_type.append(_metrics(y_test[mask], y_pred[mask], pt))

    result = {
        "overall": overall,
        "by_quarter": by_quarter,
        "by_county_top10_worst": by_county[:10],
        "by_project_type": by_type,
    }

    logger.info(f"  Overall RMSE: {overall['rmse']:.2f} UF/m² | "
                f"MAE: {overall['mae']:.2f} | R²: {overall['r2']:.4f}")
    return result


# ── 2. Quarterly rolling ──────────────────────────────────────────────────────

def run_quarterly_rolling(engine) -> list[dict]:
    """
    For each quarter Q in [2013-Q2, 2013-Q3, 2013-Q4, 2014-Q1, ..., 2014-Q4]:
      Train on all data before Q, predict Q.

    Detects temporal drift: does RMSE increase (model degrades) or decrease
    (data becomes more homogeneous) as we move through time?
    """
    logger.info("=" * 60)
    logger.info("BACKTEST 2: Quarterly rolling walk-forward")
    df = _load_data(engine)

    # Build sorted list of (year, quarter) pairs
    periods = sorted(df[["year", "quarter"]].drop_duplicates().itertuples(index=False))
    if len(periods) < 2:
        logger.error("Need at least 2 distinct quarters for rolling backtest")
        return [{"error": "insufficient_quarters"}]

    results = []
    for i, (yr, qt) in enumerate(periods):
        if i == 0:
            continue  # need at least one prior period to train

        # Train mask: all data strictly before current period
        train_mask = (df["year"] < yr) | ((df["year"] == yr) & (df["quarter"] < qt))
        test_mask  = (df["year"] == yr) & (df["quarter"] == qt)

        df_train = df[train_mask].copy()
        df_test  = df[test_mask].copy()

        if len(df_train) < 50 or len(df_test) < 10:
            logger.warning(f"  Skipping {yr}-Q{qt}: too few rows "
                           f"(train={len(df_train)}, test={len(df_test)})")
            continue

        df_train_p, df_test_p, _ = _preprocess(df_train, df_test)
        feat_cols = _feature_cols(df_train_p)

        X_train = df_train_p[feat_cols]
        y_train = df_train_p[TARGET]
        X_test  = df_test_p[feat_cols]
        y_test  = df_test_p[TARGET].values

        model  = _train_xgb(X_train, y_train)
        y_pred = model.predict(X_test)

        m = _metrics(y_test, y_pred, f"{yr}-Q{qt}")
        m["train_quarters"] = i         # how many quarters were available for training
        m["year"] = yr
        m["quarter"] = int(qt)
        results.append(m)
        logger.info(f"  {yr}-Q{qt}: RMSE={m['rmse']:.2f} MAE={m['mae']:.2f} R²={m['r2']:.4f} n={m['n']:,}")

    # Compute drift: slope of RMSE over rolling steps
    if len(results) >= 3:
        rmses  = [r["rmse"] for r in results if r.get("rmse") is not None]
        xs     = list(range(len(rmses)))
        slope  = float(np.polyfit(xs, rmses, 1)[0])
        drift  = "increasing" if slope > 0.01 else ("decreasing" if slope < -0.01 else "stable")
        logger.info(f"  RMSE drift slope: {slope:+.4f} ({drift})")
        for r in results:
            r["drift_slope"] = round(slope, 4)
            r["drift_direction"] = drift

    return results


# ── 3. Undervaluation signal validation ───────────────────────────────────────

def run_undervaluation_signal(engine) -> dict:
    """
    Tests whether gap_pct is a real signal:
      - Split 2014 test set into deciles by gap_pct
      - Bottom 20% (most undervalued per gap_pct) vs rest
      - If the signal is real, properties with high gap_pct should have
        larger absolute model errors (harder to price) or the model should
        predict lower prices for them.

    Also checks: for bottom 20% opportunity-score properties, is the
    actual price truly lower than predicted? (Confirms the buying opportunity.)
    """
    logger.info("=" * 60)
    logger.info("BACKTEST 3: Undervaluation signal validation")
    df = _load_data(engine)

    train_mask = df["year"] == 2013
    test_mask  = df["year"] == 2014

    df_train = df[train_mask].copy()
    df_test  = df[test_mask].copy()

    if df_train.empty or df_test.empty or "gap_pct" not in df.columns:
        return {"error": "insufficient_data_or_missing_gap_pct"}

    df_train_p, df_test_p, _ = _preprocess(df_train, df_test)
    feat_cols = _feature_cols(df_train_p)

    model  = _train_xgb(df_train_p[feat_cols], df_train_p[TARGET])
    y_pred = model.predict(df_test_p[feat_cols])
    y_true = df_test_p[TARGET].values

    # Reattach gap_pct (from unprocessed df_test)
    gap_pct = df_test["gap_pct"].values
    residual = y_true - y_pred        # positive = actual > predicted (undervalued by model)

    # Decile breakdown
    valid_gap = ~np.isnan(gap_pct)
    if valid_gap.sum() < 50:
        return {"error": "too_few_valid_gap_pct_rows"}

    decile_results = []
    deciles = np.percentile(gap_pct[valid_gap], np.arange(0, 101, 10))
    for d in range(10):
        lo, hi = deciles[d], deciles[d + 1]
        mask = valid_gap & (gap_pct >= lo) & (gap_pct <= hi)
        if mask.sum() < 5:
            continue
        decile_results.append({
            "decile": d + 1,
            "gap_pct_range": [round(lo, 4), round(hi, 4)],
            "n": int(mask.sum()),
            "mean_residual": round(float(residual[mask].mean()), 4),
            "rmse": round(float(np.sqrt(np.mean(residual[mask] ** 2))), 4),
            "mean_actual": round(float(y_true[mask].mean()), 4),
            "mean_predicted": round(float(y_pred[mask].mean()), 4),
        })

    # Bottom 20% vs top 80%
    p20 = np.percentile(gap_pct[valid_gap], 20)
    bottom20_mask = valid_gap & (gap_pct <= p20)
    top80_mask    = valid_gap & (gap_pct > p20)

    bottom20 = _metrics(y_true[bottom20_mask], y_pred[bottom20_mask], "bottom_20pct_gap")
    top80    = _metrics(y_true[top80_mask],    y_pred[top80_mask],    "top_80pct_gap")

    signal_confirmed = (
        top80["rmse"] is not None and bottom20["rmse"] is not None
        and bottom20["rmse"] > top80["rmse"]
    )
    logger.info(f"  Bottom 20% RMSE: {bottom20['rmse']:.2f} | Top 80% RMSE: {top80['rmse']:.2f}")
    logger.info(f"  Signal confirmed (bottom decile harder to price): {signal_confirmed}")

    return {
        "decile_breakdown": decile_results,
        "bottom_20pct": bottom20,
        "top_80pct": top80,
        "signal_confirmed": signal_confirmed,
        "interpretation": (
            "High gap_pct properties are harder to predict (larger RMSE), "
            "suggesting the signal captures genuine pricing anomalies."
            if signal_confirmed else
            "Bottom-decile RMSE is NOT higher than top-80%, suggesting gap_pct "
            "may not isolate true pricing difficulty (could still be a valid signal "
            "via market inefficiency rather than model noise)."
        ),
    }


# ── 4. Commune calibration ────────────────────────────────────────────────────

def run_commune_calibration(engine) -> pd.DataFrame:
    """
    For each commune (county_name), compare:
      - Median predicted UF/m² (from 2013 model applied to 2014 data)
      - Median actual UF/m²
      - Bias = predicted_median - actual_median
      - Bias % = bias / actual_median * 100

    Returns a DataFrame sorted by |bias_pct| descending.
    Saves to data/exports/commune_calibration.csv.
    """
    logger.info("=" * 60)
    logger.info("BACKTEST 4: Commune-level calibration")
    df = _load_data(engine)

    train_mask = df["year"] == 2013
    test_mask  = df["year"] == 2014

    df_train = df[train_mask].copy()
    df_test  = df[test_mask].copy()

    if df_train.empty or df_test.empty:
        logger.error("Need 2013 and 2014 data for commune calibration")
        return pd.DataFrame()

    # Keep county_name before encoding for grouping later
    county_names_test = df_test["county_name"].values

    df_train_p, df_test_p, _ = _preprocess(df_train, df_test)
    feat_cols = _feature_cols(df_train_p)

    model  = _train_xgb(df_train_p[feat_cols], df_train_p[TARGET])
    y_pred = model.predict(df_test_p[feat_cols])
    y_true = df_test_p[TARGET].values

    rows = []
    for county in sorted(set(county_names_test)):
        mask = county_names_test == county
        if mask.sum() < 5:
            continue
        actual_med = float(np.median(y_true[mask]))
        pred_med   = float(np.median(y_pred[mask]))
        bias       = pred_med - actual_med
        bias_pct   = (bias / actual_med * 100) if actual_med > 0 else None
        rows.append({
            "county_name":     county,
            "n_transactions":  int(mask.sum()),
            "actual_median_uf_m2":    round(actual_med, 2),
            "predicted_median_uf_m2": round(pred_med, 2),
            "bias_uf_m2":             round(bias, 2),
            "bias_pct":               round(bias_pct, 2) if bias_pct is not None else None,
            "direction":              "overestimated" if bias > 0 else "underestimated",
        })

    calib_df = pd.DataFrame(rows)
    if calib_df.empty:
        return calib_df

    calib_df = calib_df.sort_values("bias_pct", key=abs, ascending=False).reset_index(drop=True)

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    calib_df.to_csv(CALIBRATION_PATH, index=False)
    logger.info(f"  Commune calibration saved: {CALIBRATION_PATH}")
    logger.info(f"  {len(calib_df)} communes | max |bias|: "
                f"{calib_df['bias_pct'].abs().max():.1f}%")

    return calib_df


# ── 5. OLS benchmark (thesis comparison) ──────────────────────────────────────

def run_ols_benchmark(engine) -> dict:
    """
    Fits a simple log-linear OLS hedonic regression mirroring the 2017 MIT
    thesis methodology:

        log(uf_m2) ~ log(surface_m2) + age_proxy + C(county_name)
                   + C(project_type) + C(year) + C(quarter)

    Note: The CBR dataset does not include construction year directly.
    We use surface_building_m2 / surface_m2 as an imperfect age proxy
    (floor area ratio). The thesis used explicit vintage dummies.

    Compares OLS vs XGBoost on 2014 hold-out:
      - R², RMSE, MAE
      - Thesis benchmark: surface coeff ~0.928, Q4 premium ~1.2%

    Requires: statsmodels
    """
    logger.info("=" * 60)
    logger.info("BACKTEST 5: OLS log-linear benchmark (thesis comparison)")

    try:
        import statsmodels.formula.api as smf
    except ImportError:
        logger.error("statsmodels not installed. Run: pip install statsmodels")
        return {"error": "statsmodels_not_installed"}

    df = _load_data(engine)

    # Keep only positive surface for log transform
    df = df[(df["surface_m2"] > 0) & (df[TARGET] > 0)].copy()

    # Derived features for OLS
    df["log_uf_m2"]   = np.log(df[TARGET])
    df["log_surface"]  = np.log(df["surface_m2"])
    # Floor area ratio as vintage proxy (higher FAR ~ denser / newer urban build)
    df["far_ratio"] = np.where(
        df["surface_m2"] > 0,
        df["surface_building_m2"].fillna(0) / df["surface_m2"],
        0.0,
    )
    df["year"]    = df["year"].astype(str)
    df["quarter"] = df["quarter"].astype(str)

    # Temporal train/test split
    train_mask = df["year"] == "2013"
    test_mask  = df["year"] == "2014"

    df_train = df[train_mask].copy()
    df_test  = df[test_mask].copy()

    if df_train.empty or df_test.empty:
        return {"error": "insufficient_data"}

    # Ensure county/type present in both splits (drop unseen test categories)
    known_counties = set(df_train["county_name"].unique())
    known_types    = set(df_train["project_type"].unique())
    df_test = df_test[
        df_test["county_name"].isin(known_counties)
        & df_test["project_type"].isin(known_types)
    ].copy()

    formula = (
        "log_uf_m2 ~ log_surface + far_ratio "
        "+ C(county_name) + C(project_type) + C(year) + C(quarter)"
    )

    logger.info(f"  Fitting OLS on {len(df_train):,} train rows...")
    try:
        ols_result = smf.ols(formula, data=df_train).fit()
    except Exception as exc:
        logger.error(f"OLS fit failed: {exc}")
        return {"error": str(exc)}

    # Predict on test (in log space, then exponentiate)
    try:
        log_pred = ols_result.predict(df_test)
    except Exception as exc:
        logger.error(f"OLS predict failed: {exc}")
        return {"error": str(exc)}

    y_pred_ols  = np.exp(log_pred)
    y_true_test = df_test[TARGET].values

    ols_metrics = _metrics(y_true_test, y_pred_ols, "OLS_log_linear")

    # Extract key thesis-comparable coefficients
    params = ols_result.params
    log_surface_coef = float(params.get("log_surface", np.nan))
    # Q4 dummy (relative to Q1 which is baseline)
    q4_key = next((k for k in params.index if "quarter" in k.lower() and "4" in k), None)
    q4_coef = float(params[q4_key]) if q4_key else None
    q4_pct_premium = round((np.exp(q4_coef) - 1) * 100, 3) if q4_coef is not None else None

    # Also run XGBoost on same train/test split for fair head-to-head
    df["year"]    = df["year"].astype(int)
    df["quarter"] = df["quarter"].astype(int)
    df_xgb_train = df[df["year"] == 2013].copy()
    df_xgb_test  = df[df["year"] == 2014].copy()

    df_xgb_train_p, df_xgb_test_p, _ = _preprocess(df_xgb_train, df_xgb_test)
    feat_cols = _feature_cols(df_xgb_train_p)

    xgb_model  = _train_xgb(df_xgb_train_p[feat_cols], df_xgb_train_p[TARGET])
    y_pred_xgb = xgb_model.predict(df_xgb_test_p[feat_cols])
    xgb_metrics = _metrics(df_xgb_test_p[TARGET].values, y_pred_xgb, "XGBoost")

    logger.info(f"  OLS  — R²: {ols_metrics['r2']:.4f} RMSE: {ols_metrics['rmse']:.2f}")
    logger.info(f"  XGB  — R²: {xgb_metrics['r2']:.4f} RMSE: {xgb_metrics['rmse']:.2f}")
    logger.info(f"  OLS surface coeff: {log_surface_coef:.3f} "
                f"(thesis benchmark: 0.928)")
    if q4_pct_premium is not None:
        logger.info(f"  Q4 premium: {q4_pct_premium:+.2f}% "
                    f"(thesis benchmark: +1.2%)")

    return {
        "ols": ols_metrics,
        "xgboost": xgb_metrics,
        "ols_surface_coeff": round(log_surface_coef, 4),
        "ols_surface_coeff_thesis_benchmark": 0.928,
        "ols_q4_pct_premium": q4_pct_premium,
        "ols_q4_thesis_benchmark_pct": 1.2,
        "ols_r2_adj": round(float(ols_result.rsquared_adj), 4),
        "ols_n_obs": int(ols_result.nobs),
        "improvement_xgb_vs_ols": {
            "rmse_reduction_pct": round(
                (ols_metrics["rmse"] - xgb_metrics["rmse"]) / ols_metrics["rmse"] * 100, 2
            ) if ols_metrics["rmse"] and xgb_metrics["rmse"] else None,
            "r2_gain": round(
                xgb_metrics["r2"] - ols_metrics["r2"], 4
            ) if ols_metrics["r2"] is not None else None,
        },
    }


# ── 6. Evaluate commune calibration (migration 010) ──────────────────────────

def evaluate_commune_calibration(engine, model_version: str = "v1.0") -> dict | None:
    """
    Evaluates the impact of commune-level post-hoc calibration (migration 010)
    on prediction accuracy.

    Computes for each row:
      raw_error        = actual_uf_m2 - predicted_uf_m2
      cal_error        = actual_uf_m2 - calibrated_predicted

    Reports per-commune and overall:
      MAE / RMSE / Median absolute error — before and after calibration
      % improvement per commune
      Top-5 communes with biggest RMSE improvement
      Top-5 communes where calibration made things worse (if any)

    Saves: data/exports/calibration_eval_{model_version}.json

    Returns dict with keys: summary, per_commune, top_improved, top_worsened
    Returns None if commune_calibration table doesn't exist or is empty.
    """
    logger.info("=" * 60)
    logger.info(f"BACKTEST 6: Commune calibration evaluation (model_version={model_version})")

    # ── Check that the table exists ───────────────────────────────────────────
    try:
        check_sql = """
            SELECT COUNT(*) AS n
            FROM commune_calibration
            WHERE model_version = :mv
        """
        with engine.connect() as conn:
            row = conn.execute(
                __import__("sqlalchemy").text(check_sql),
                {"mv": model_version},
            ).fetchone()
        n_calib = row[0] if row else 0
    except Exception as exc:
        logger.warning(f"  commune_calibration table not accessible: {exc} — skipping")
        return None

    if n_calib == 0:
        logger.warning(
            f"  commune_calibration has 0 rows for model_version='{model_version}' — skipping"
        )
        return None

    logger.info(f"  commune_calibration has {n_calib} rows for model_version='{model_version}'")

    # ── Pull the joined dataset ───────────────────────────────────────────────
    query = """
        SELECT
            tc.county_name,
            tc.project_type,
            ms.predicted_uf_m2,
            ms.gap_pct,
            tc.uf_m2_building                                         AS actual_uf_m2,
            cc.median_residual,
            ms.predicted_uf_m2 + COALESCE(cc.median_residual, 0)     AS calibrated_predicted
        FROM model_scores ms
        JOIN transactions_clean tc ON tc.id = ms.clean_id
        LEFT JOIN commune_calibration cc
            ON  cc.model_version = ms.model_version
            AND cc.county_name   = tc.county_name
            AND cc.project_type  = tc.project_type
        WHERE ms.model_version     = :mv
          AND tc.is_outlier        = FALSE
          AND tc.has_valid_price   = TRUE
          AND ms.predicted_uf_m2  > 5
          AND tc.uf_m2_building   >= 10
    """
    try:
        df = pd.read_sql(
            __import__("sqlalchemy").text(query),
            engine,
            params={"mv": model_version},
        )
    except Exception as exc:
        logger.error(f"  Query failed: {exc}")
        return None

    if df.empty:
        logger.warning("  Query returned 0 rows — skipping")
        return None

    logger.info(f"  Loaded {len(df):,} rows for calibration evaluation")

    # ── Row-level errors ──────────────────────────────────────────────────────
    df["raw_error"] = df["actual_uf_m2"] - df["predicted_uf_m2"]
    df["cal_error"] = df["actual_uf_m2"] - df["calibrated_predicted"]
    df["abs_raw"]   = df["raw_error"].abs()
    df["abs_cal"]   = df["cal_error"].abs()
    df["sq_raw"]    = df["raw_error"] ** 2
    df["sq_cal"]    = df["cal_error"] ** 2

    # ── Overall metrics ───────────────────────────────────────────────────────
    def _overall(label_raw, label_cal):
        mae_raw  = float(df["abs_raw"].mean())
        mae_cal  = float(df["abs_cal"].mean())
        rmse_raw = float(np.sqrt(df["sq_raw"].mean()))
        rmse_cal = float(np.sqrt(df["sq_cal"].mean()))
        med_raw  = float(df["abs_raw"].median())
        med_cal  = float(df["abs_cal"].median())

        def _pct(before, after):
            return round((before - after) / before * 100, 2) if before > 0 else None

        return {
            "n":                    int(len(df)),
            "mae_raw":              round(mae_raw,  4),
            "mae_calibrated":       round(mae_cal,  4),
            "mae_improvement_pct":  _pct(mae_raw, mae_cal),
            "rmse_raw":             round(rmse_raw, 4),
            "rmse_calibrated":      round(rmse_cal, 4),
            "rmse_improvement_pct": _pct(rmse_raw, rmse_cal),
            "median_ae_raw":        round(med_raw,  4),
            "median_ae_calibrated": round(med_cal,  4),
            "median_ae_improvement_pct": _pct(med_raw, med_cal),
            "calibration_rows_pct": round(
                df["median_residual"].notna().sum() / len(df) * 100, 1
            ),
        }

    summary = _overall("raw", "calibrated")

    logger.info(
        f"  Overall MAE:  {summary['mae_raw']:.4f} ->{summary['mae_calibrated']:.4f}"
        f"  ({summary['mae_improvement_pct']:+.1f}%)"
    )
    logger.info(
        f"  Overall RMSE: {summary['rmse_raw']:.4f} ->{summary['rmse_calibrated']:.4f}"
        f"  ({summary['rmse_improvement_pct']:+.1f}%)"
    )

    # ── Per-commune metrics ───────────────────────────────────────────────────
    commune_rows = []
    for county, grp in df.groupby("county_name"):
        if len(grp) < 5:
            continue
        mae_raw  = float(grp["abs_raw"].mean())
        mae_cal  = float(grp["abs_cal"].mean())
        rmse_raw = float(np.sqrt(grp["sq_raw"].mean()))
        rmse_cal = float(np.sqrt(grp["sq_cal"].mean()))

        rmse_improvement_pct = (
            round((rmse_raw - rmse_cal) / rmse_raw * 100, 2) if rmse_raw > 0 else None
        )
        mae_improvement_pct = (
            round((mae_raw - mae_cal) / mae_raw * 100, 2) if mae_raw > 0 else None
        )

        commune_rows.append({
            "county_name":           county,
            "n":                     int(len(grp)),
            "mae_raw":               round(mae_raw,  4),
            "mae_calibrated":        round(mae_cal,  4),
            "mae_improvement_pct":   mae_improvement_pct,
            "rmse_raw":              round(rmse_raw, 4),
            "rmse_calibrated":       round(rmse_cal, 4),
            "rmse_improvement_pct":  rmse_improvement_pct,
            "median_ae_raw":         round(float(grp["abs_raw"].median()), 4),
            "median_ae_calibrated":  round(float(grp["abs_cal"].median()), 4),
            "has_calibration":       bool(grp["median_residual"].notna().any()),
            "median_residual":       (
                round(float(grp["median_residual"].dropna().iloc[0]), 4)
                if grp["median_residual"].notna().any() else None
            ),
        })

    commune_rows.sort(key=lambda r: r["rmse_improvement_pct"] or -9999, reverse=True)

    # Top 5 improved / top 5 worsened
    improved = [r for r in commune_rows if (r["rmse_improvement_pct"] or 0) > 0]
    worsened = [r for r in commune_rows if (r["rmse_improvement_pct"] or 0) < 0]
    worsened.sort(key=lambda r: r["rmse_improvement_pct"] or 0)   # most negative first

    top_improved = improved[:5]
    top_worsened = worsened[:5]

    if top_improved:
        logger.info("  Top 5 most improved communes (RMSE):")
        for r in top_improved:
            logger.info(
                f"    {r['county_name']}: {r['rmse_raw']:.3f} ->{r['rmse_calibrated']:.3f}"
                f"  ({r['rmse_improvement_pct']:+.1f}%)"
            )
    if top_worsened:
        logger.warning("  Communes where calibration WORSENED predictions:")
        for r in top_worsened:
            logger.warning(
                f"    {r['county_name']}: {r['rmse_raw']:.3f} ->{r['rmse_calibrated']:.3f}"
                f"  ({r['rmse_improvement_pct']:+.1f}%)"
            )

    # ── Assemble result ───────────────────────────────────────────────────────
    result = {
        "model_version":  model_version,
        "generated_at":   datetime.now().isoformat(),
        "summary":        summary,
        "per_commune":    commune_rows,
        "top_improved":   top_improved,
        "top_worsened":   top_worsened,
    }

    # ── Save JSON report ──────────────────────────────────────────────────────
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    eval_path = EXPORTS_DIR / f"calibration_eval_{model_version}.json"
    with open(eval_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, default=str)
    logger.info(f"  Calibration evaluation saved: {eval_path}")

    return result


# ── Reporting helpers ─────────────────────────────────────────────────────────

def _md_table(rows: list[dict], cols: list[str]) -> str:
    """Render a simple Markdown table from a list of dicts."""
    if not rows:
        return "_No data_\n"
    header = " | ".join(cols)
    sep    = " | ".join(["---"] * len(cols))
    lines  = [f"| {header} |", f"| {sep} |"]
    for row in rows:
        line = " | ".join(str(row.get(c, "")) for c in cols)
        lines.append(f"| {line} |")
    return "\n".join(lines)


def _print_report(report: dict) -> None:
    """Print a Markdown summary of all backtest results to stdout."""
    ts = report.get("generated_at", "")
    print(f"\n# RE_CL Backtesting Report — {ts}\n")

    # ── Temporal split
    ts_data = report.get("temporal_split", {})
    if ts_data and "overall" in ts_data:
        ov = ts_data["overall"]
        print("## 1. Temporal Split (Train 2013 ->Test 2014)\n")
        print(f"| Metric | Value |")
        print(f"|--------|-------|")
        print(f"| N train | {ov.get('n', '?'):,} |")
        print(f"| RMSE (UF/m²) | {ov.get('rmse', '?')} |")
        print(f"| MAE (UF/m²)  | {ov.get('mae', '?')} |")
        print(f"| R²           | {ov.get('r2', '?')} |")
        print(f"| RMSE % median | {ov.get('rmse_pct_median', '?')}% |")
        print()

        bq = ts_data.get("by_quarter", [])
        if bq:
            print("### By Quarter\n")
            print(_md_table(bq, ["label", "n", "rmse", "mae", "r2", "rmse_pct_median"]))
            print()

        bp = ts_data.get("by_project_type", [])
        if bp:
            print("### By Project Type\n")
            print(_md_table(bp, ["label", "n", "rmse", "mae", "r2"]))
            print()

    # ── Quarterly rolling
    qr = report.get("quarterly_rolling", [])
    valid_qr = [r for r in qr if isinstance(r, dict) and "rmse" in r]
    if valid_qr:
        print("## 2. Quarterly Rolling Walk-Forward\n")
        drift = valid_qr[0].get("drift_direction", "unknown") if valid_qr else "?"
        print(f"RMSE drift: **{drift}**\n")
        print(_md_table(valid_qr, ["label", "n", "rmse", "mae", "r2", "train_quarters"]))
        print()

    # ── Undervaluation signal
    uv = report.get("undervaluation_signal", {})
    if uv and "signal_confirmed" in uv:
        print("## 3. Undervaluation Signal Validation\n")
        print(f"**Signal confirmed:** {uv['signal_confirmed']}\n")
        print(f"_{uv.get('interpretation', '')}_\n")
        bottom = uv.get("bottom_20pct", {})
        top    = uv.get("top_80pct", {})
        print(f"| Segment | n | RMSE | MAE | R² |")
        print(f"|---------|---|------|-----|-----|")
        print(f"| Bottom 20% gap_pct | {bottom.get('n','')} | "
              f"{bottom.get('rmse','')} | {bottom.get('mae','')} | {bottom.get('r2','')} |")
        print(f"| Top 80% gap_pct    | {top.get('n','')} | "
              f"{top.get('rmse','')} | {top.get('mae','')} | {top.get('r2','')} |")
        print()

    # ── OLS benchmark
    ols = report.get("ols_benchmark", {})
    if ols and "ols" in ols and "xgboost" in ols:
        print("## 5. OLS Benchmark vs XGBoost\n")
        print(f"| Model | R² | RMSE | MAE |")
        print(f"|-------|----|------|-----|")
        ols_m = ols["ols"]
        xgb_m = ols["xgboost"]
        print(f"| OLS log-linear | {ols_m.get('r2','')} | {ols_m.get('rmse','')} | {ols_m.get('mae','')} |")
        print(f"| XGBoost        | {xgb_m.get('r2','')} | {xgb_m.get('rmse','')} | {xgb_m.get('mae','')} |")
        print()
        print(f"| Thesis benchmark | Model result |")
        print(f"|-----------------|--------------|")
        print(f"| Surface coeff 0.928 | {ols.get('ols_surface_coeff', '?')} |")
        print(f"| Q4 premium +1.2% | {ols.get('ols_q4_pct_premium', '?')}% |")
        imp = ols.get("improvement_xgb_vs_ols", {})
        print(f"| XGBoost RMSE reduction vs OLS | {imp.get('rmse_reduction_pct','?')}% |")
        print(f"| XGBoost R² gain vs OLS | {imp.get('r2_gain','?')} |")
        print()

    # ── Commune calibration (top 10 most biased)
    cc = report.get("commune_calibration_top10", [])
    if cc:
        print("## 4. Commune Calibration (top 10 most biased)\n")
        print(_md_table(cc, [
            "county_name", "n_transactions",
            "actual_median_uf_m2", "predicted_median_uf_m2",
            "bias_pct", "direction",
        ]))
        print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="RE_CL V4.5 — Walk-forward backtesting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--temporal-only", action="store_true",
                        help="Run only temporal split backtest")
    parser.add_argument("--rolling",       action="store_true",
                        help="Run only quarterly rolling backtest")
    parser.add_argument("--commune",       action="store_true",
                        help="Run only commune calibration")
    parser.add_argument("--ols",           action="store_true",
                        help="Run only OLS benchmark")
    parser.add_argument("--signal",        action="store_true",
                        help="Run only undervaluation signal test")
    parser.add_argument("--calib-eval",    action="store_true",
                        help="Evaluate commune calibration (migration 010) improvement")
    parser.add_argument("--model-version", default="v1.0",
                        help="Model version tag for calib-eval (default: v1.0)")
    args = parser.parse_args()

    # Default: run all unless a specific flag is set
    run_all = not any([
        args.temporal_only, args.rolling,
        args.commune, args.ols, args.signal,
        args.calib_eval,
    ])

    engine = create_engine(_build_db_url(), pool_pre_ping=True)
    report: dict = {"generated_at": datetime.now().isoformat()}

    try:
        if run_all or args.temporal_only:
            report["temporal_split"] = run_temporal_split(engine)

        if run_all or args.rolling:
            report["quarterly_rolling"] = run_quarterly_rolling(engine)

        if run_all or args.signal:
            report["undervaluation_signal"] = run_undervaluation_signal(engine)

        if run_all or args.commune:
            calib_df = run_commune_calibration(engine)
            if not calib_df.empty:
                report["commune_calibration_top10"] = calib_df.head(10).to_dict(orient="records")

        if run_all or args.ols:
            report["ols_benchmark"] = run_ols_benchmark(engine)

        if run_all or args.calib_eval:
            calib_eval = evaluate_commune_calibration(engine, args.model_version)
            if calib_eval is not None:
                report["commune_calibration_eval"] = calib_eval

    except Exception as exc:
        logger.exception(f"Backtesting failed: {exc}")
        report["error"] = str(exc)
        _print_report(report)
        sys.exit(1)

    # Save JSON report
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info(f"Report saved: {REPORT_PATH}")

    # Print Markdown summary
    _print_report(report)

    logger.info("Backtesting complete.")


if __name__ == "__main__":
    # Allow import resolution when running from re_cl/ directory
    _src = str(Path(__file__).parent.parent.parent)
    if _src not in sys.path:
        sys.path.insert(0, _src)

    # Standalone mode: if called with --calib-eval-only, skip the full backtest
    # suite and only run the calibration evaluation, then print the summary.
    #
    # Usage:
    #   python src/backtesting/walk_forward.py --calib-eval-only
    #   python src/backtesting/walk_forward.py --calib-eval-only --model-version v1.0
    #
    # For the full suite (including calib-eval):
    #   python src/backtesting/walk_forward.py --calib-eval
    if "--calib-eval-only" in sys.argv:
        load_dotenv()
        _mv = "v1.0"
        for _i, _arg in enumerate(sys.argv):
            if _arg == "--model-version" and _i + 1 < len(sys.argv):
                _mv = sys.argv[_i + 1]
        _engine = create_engine(_build_db_url(), pool_pre_ping=True)
        _results = evaluate_commune_calibration(_engine, model_version=_mv)
        if _results is None:
            logger.error("Calibration evaluation returned None — check warnings above.")
            sys.exit(1)
        s = _results["summary"]
        print("\n## Commune Calibration Evaluation\n")
        print(f"Model version : {_results['model_version']}")
        print(f"Rows evaluated: {s['n']:,}  ({s['calibration_rows_pct']}% have a calibration row)\n")
        print(f"{'Metric':<28} {'Before':>12} {'After':>12} {'Improvement':>14}")
        print("-" * 70)
        print(f"{'MAE (UF/m²)':<28} {s['mae_raw']:>12.4f} {s['mae_calibrated']:>12.4f} "
              f"{s['mae_improvement_pct']:>+13.2f}%")
        print(f"{'RMSE (UF/m²)':<28} {s['rmse_raw']:>12.4f} {s['rmse_calibrated']:>12.4f} "
              f"{s['rmse_improvement_pct']:>+13.2f}%")
        print(f"{'Median AE (UF/m²)':<28} {s['median_ae_raw']:>12.4f} {s['median_ae_calibrated']:>12.4f} "
              f"{s['median_ae_improvement_pct']:>+13.2f}%")
        if _results["top_improved"]:
            print("\n### Top 5 communes — biggest RMSE improvement")
            for r in _results["top_improved"]:
                print(f"  {r['county_name']:<22}  {r['rmse_raw']:.3f} ->{r['rmse_calibrated']:.3f}"
                      f"  ({r['rmse_improvement_pct']:+.1f}%)")
        if _results["top_worsened"]:
            print("\n### Communes where calibration WORSENED accuracy")
            for r in _results["top_worsened"]:
                print(f"  {r['county_name']:<22}  {r['rmse_raw']:.3f} ->{r['rmse_calibrated']:.3f}"
                      f"  ({r['rmse_improvement_pct']:+.1f}%)")
        sys.exit(0)

    main()
