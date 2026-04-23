"""
hedonic_model.py
----------------
XGBoost hedonic pricing model for Chilean real estate.

Predicts UF/m² from property attributes and location features.
Uses temporal hold-out: 2014 Q4 as test set, everything else as train.

Features used:
  - project_type (encoded)
  - county_name (encoded)
  - year, quarter, season_index
  - surface_m2, surface_building_m2, surface_land_m2
  - dist_km_centroid, cluster_id
  - data_confidence

Target: uf_m2_building (winsorized)

Usage:
    python src/models/hedonic_model.py          # Train and save model
    python src/models/hedonic_model.py --eval   # Train, eval, print metrics
"""

import argparse
import os
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import LabelEncoder
from sqlalchemy import create_engine, text
import xgboost as xgb

load_dotenv()

MODEL_DIR     = Path(__file__).parent.parent.parent / "data" / "processed"
MODEL_PATH    = MODEL_DIR / "hedonic_model_v1.pkl"
ENCODER_PATH  = MODEL_DIR / "label_encoders_v1.pkl"
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0")

# Winsorize target at 1-99% to reduce outlier influence
TARGET_WINSOR = (0.01, 0.99)

CAT_FEATURES = ["project_type", "county_name", "construction_year_bucket", "city_zone"]
NUM_FEATURES = [
    "year", "quarter", "season_index",
    "surface_m2", "surface_building_m2", "surface_land_m2",
    "dist_km_centroid", "cluster_id", "data_confidence",
    "price_percentile_50",   # median price context from features table
    # Thesis features (V4.1 — Juan Montes MIT 2017)
    "age", "age_sq", "log_surface",
    # ieut-inciti local shapefile features (Phase 8)
    "dist_green_area_km",
    "dist_feria_km", "dist_mall_local_km", "n_commercial_blocks_500m",
    "dist_metro_local_km", "dist_bus_local_km", "dist_autopista_km", "dist_ciclovia_km",
    "dist_school_local_km", "dist_jardines_km", "dist_health_local_km",
    "dist_cultural_km", "dist_policia_km",
    "dist_airport_km", "dist_industrial_km", "dist_vertedero_km",
]
TARGET = "uf_m2_building"


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


def load_training_data(engine) -> pd.DataFrame:
    """
    Joins transactions_clean + transaction_features for model training.
    Excludes outliers and rows without valid price/coords.
    """
    logger.info("Loading training data...")
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
            tf.season_index,
            -- Thesis features (V4.1)
            tf.age,
            tf.age_sq,
            tf.construction_year_bucket,
            tf.city_zone,
            tf.log_surface,
            -- ieut-inciti local shapefile features (Phase 8)
            tf.dist_green_area_km,
            tf.dist_feria_km,
            tf.dist_mall_local_km,
            tf.n_commercial_blocks_500m,
            tf.dist_metro_local_km,
            tf.dist_bus_local_km,
            tf.dist_autopista_km,
            tf.dist_ciclovia_km,
            tf.dist_school_local_km,
            tf.dist_jardines_km,
            tf.dist_health_local_km,
            tf.dist_cultural_km,
            tf.dist_policia_km,
            tf.dist_airport_km,
            tf.dist_industrial_km,
            tf.dist_vertedero_km
        FROM transactions_clean tc
        JOIN transaction_features tf ON tf.clean_id = tc.id
        WHERE tc.is_outlier = FALSE
          AND tc.has_valid_price = TRUE
          AND tc.uf_m2_building IS NOT NULL
          AND tc.uf_m2_building > 0
    """
    df = pd.read_sql(query, engine)
    logger.info(f"  {len(df):,} rows loaded for training")

    # Ensure ieut columns are float (they're all-NULL before ieut_spatial_features runs)
    IEUT_COLS = [
        "dist_green_area_km", "dist_feria_km", "dist_mall_local_km",
        "n_commercial_blocks_500m", "dist_metro_local_km", "dist_bus_local_km",
        "dist_autopista_km", "dist_ciclovia_km", "dist_school_local_km",
        "dist_jardines_km", "dist_health_local_km", "dist_cultural_km",
        "dist_policia_km", "dist_airport_km", "dist_industrial_km", "dist_vertedero_km",
    ]
    for col in IEUT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def preprocess(df: pd.DataFrame, encoders: dict = None, fit: bool = True):
    """
    Encodes categorical features and imputes nulls.
    If fit=True, fits new LabelEncoders and returns them.
    If fit=False, uses provided encoders (inference mode).
    """
    df = df.copy()

    # Winsorize target (only during training)
    if fit and TARGET in df.columns:
        p_low  = df[TARGET].quantile(TARGET_WINSOR[0])
        p_high = df[TARGET].quantile(TARGET_WINSOR[1])
        df[TARGET] = df[TARGET].clip(p_low, p_high)
        logger.info(f"Target winsorized: [{p_low:.2f}, {p_high:.2f}] UF/m²")

    # Encode categoricals
    if fit:
        encoders = {}
        for col in CAT_FEATURES:
            le = LabelEncoder()
            df[col] = le.fit_transform(df[col].astype(str).fillna("unknown"))
            encoders[col] = le
    else:
        for col in CAT_FEATURES:
            le = encoders[col]
            known = set(le.classes_)
            df[col] = df[col].astype(str).fillna("unknown")
            df[col] = df[col].apply(lambda x: x if x in known else "unknown")
            # Handle unseen labels
            if "unknown" not in known:
                le.classes_ = np.append(le.classes_, "unknown")
            df[col] = le.transform(df[col])

    # Impute numerics with median
    for col in NUM_FEATURES:
        if col in df.columns:
            median = df[col].median()
            df[col] = df[col].fillna(median if not np.isnan(median) else 0)

    return df, encoders


def train(df: pd.DataFrame):
    """
    Trains XGBoost hedonic model with temporal hold-out (2014 Q4 = test).
    Returns (model, encoders, metrics_dict).
    """
    # Temporal split: 2014 Q4 as test set
    test_mask  = (df["year"] == 2014) & (df["quarter"] == 4)
    train_mask = ~test_mask

    n_test  = test_mask.sum()
    n_train = train_mask.sum()
    logger.info(f"Split — train: {n_train:,} | test: {n_test:,} (2014 Q4)")

    if n_test < 100:
        logger.warning(f"Only {n_test} test rows — metrics may be unreliable")

    df_proc, encoders = preprocess(df, fit=True)

    feature_cols = CAT_FEATURES + [f for f in NUM_FEATURES if f in df_proc.columns]
    X_train = df_proc.loc[train_mask, feature_cols]
    y_train = df_proc.loc[train_mask, TARGET]
    X_test  = df_proc.loc[test_mask,  feature_cols]
    y_test  = df_proc.loc[test_mask,  TARGET]

    model = xgb.XGBRegressor(
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

    logger.info("Training XGBoost...")
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=50,
    )

    # Evaluate
    y_pred  = model.predict(X_test)
    median_price = y_test.median()
    rmse    = np.sqrt(mean_squared_error(y_test, y_pred))
    mae     = mean_absolute_error(y_test, y_pred)
    r2      = r2_score(y_test, y_pred)
    rmse_pct = (rmse / median_price * 100) if median_price > 0 else float("nan")

    metrics = {
        "rmse": round(rmse, 4),
        "mae":  round(mae, 4),
        "r2":   round(r2, 4),
        "rmse_pct_of_median": round(rmse_pct, 2),
        "median_price": round(median_price, 4),
        "n_train": int(n_train),
        "n_test":  int(n_test),
    }

    logger.info(f"RMSE: {rmse:.2f} UF/m² ({rmse_pct:.1f}% of median {median_price:.2f})")
    logger.info(f"MAE:  {mae:.2f} | R²: {r2:.4f}")

    threshold = 30.0
    if rmse_pct > threshold:
        logger.warning(
            f"RMSE {rmse_pct:.1f}% exceeds target {threshold}%. "
            "Consider more features or data cleaning before Phase 4 scoring."
        )
    else:
        logger.info(f"✓ RMSE {rmse_pct:.1f}% is within target {threshold}%")

    return model, encoders, metrics


def save_model(model, encoders: dict, metrics: dict) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({"model": model, "metrics": metrics,
                     "version": MODEL_VERSION, "feature_cols": CAT_FEATURES + NUM_FEATURES}, f)
    with open(ENCODER_PATH, "wb") as f:
        pickle.dump(encoders, f)
    logger.info(f"Model saved: {MODEL_PATH}")
    logger.info(f"Encoders saved: {ENCODER_PATH}")


def load_model():
    """Load saved model and encoders. Returns (model, encoders, metadata)."""
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model not found: {MODEL_PATH}\n"
            "Run: python src/models/hedonic_model.py"
        )
    with open(MODEL_PATH, "rb") as f:
        data = pickle.load(f)
    with open(ENCODER_PATH, "rb") as f:
        encoders = pickle.load(f)
    return data["model"], encoders, data


def predict(df: pd.DataFrame, model, encoders: dict) -> np.ndarray:
    """Generate predictions for a DataFrame. Returns array of predicted UF/m²."""
    df_proc, _ = preprocess(df, encoders=encoders, fit=False)
    feature_cols = CAT_FEATURES + [f for f in NUM_FEATURES if f in df_proc.columns]
    return model.predict(df_proc[feature_cols])


def main(eval_only: bool = False) -> None:
    engine = create_engine(_build_db_url(), pool_pre_ping=True)
    df     = load_training_data(engine)

    if df.empty:
        logger.error("No training data. Run Phase 2 (ingestion) and Phase 3 (features) first.")
        sys.exit(1)

    model, encoders, metrics = train(df)
    save_model(model, encoders, metrics)

    logger.info("Training complete. Metrics:")
    for k, v in metrics.items():
        logger.info(f"  {k}: {v}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", action="store_true")
    args = parser.parse_args()
    main(eval_only=args.eval)
