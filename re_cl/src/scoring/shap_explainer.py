"""
shap_explainer.py
-----------------
Generates SHAP values for XGBoost hedonic model predictions.
Extracts top-3 features per row and formats for JSONB storage.

Output format (stored in model_scores.shap_top_features):
  [
    {"feature": "county_name", "shap": -0.42, "direction": "down"},
    {"feature": "dist_km_centroid", "shap": 0.18, "direction": "up"},
    {"feature": "surface_m2", "shap": -0.11, "direction": "down"}
  ]

direction: "down" = lowers predicted price (supports undervaluation finding)
           "up"   = raises predicted price
"""

import json
import os
import sys

import numpy as np
import pandas as pd
import shap
from loguru import logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.models.hedonic_model import (
    load_model, preprocess, CAT_FEATURES, NUM_FEATURES
)

TOP_N = 3   # Number of top SHAP features to store per row


def compute_shap_values(df: pd.DataFrame, model, encoders: dict) -> np.ndarray:
    """
    Computes SHAP values matrix for the given DataFrame.
    Returns array of shape (n_rows, n_features).
    """
    df_proc, _ = preprocess(df, encoders=encoders, fit=False)
    feature_cols = CAT_FEATURES + [f for f in NUM_FEATURES if f in df_proc.columns]
    X = df_proc[feature_cols]

    logger.info(f"Computing SHAP values for {len(X):,} rows...")
    explainer   = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)
    logger.info("SHAP values computed.")
    return shap_values, feature_cols


def top_shap_features(shap_row: np.ndarray, feature_names: list, n: int = TOP_N) -> list:
    """
    Returns top-N features by absolute SHAP value for a single row.
    """
    abs_shap = np.abs(shap_row)
    top_idx  = np.argsort(abs_shap)[::-1][:n]
    return [
        {
            "feature":   feature_names[i],
            "shap":      round(float(shap_row[i]), 4),
            "direction": "up" if shap_row[i] > 0 else "down",
        }
        for i in top_idx
    ]


def run(df: pd.DataFrame, model=None, encoders: dict = None) -> pd.DataFrame:
    """
    Generates SHAP explanations for all rows in df.
    Returns DataFrame with columns: id, shap_top_features (JSON string), feature_importance (JSON)

    If model/encoders not provided, loads from disk.
    """
    if model is None or encoders is None:
        model, encoders, _ = load_model()

    shap_values, feature_cols = compute_shap_values(df, model, encoders)

    records = []
    for i, (idx, row) in enumerate(df.iterrows()):
        top = top_shap_features(shap_values[i], feature_cols)
        full = {
            feat: round(float(val), 6)
            for feat, val in zip(feature_cols, shap_values[i])
        }
        records.append({
            "id":                row["id"],
            "shap_top_features": json.dumps(top),
            "feature_importance": json.dumps(full),
        })

    result = pd.DataFrame(records)
    logger.info(f"SHAP explanations generated: {len(result):,} rows")
    return result
