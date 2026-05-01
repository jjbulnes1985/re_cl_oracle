"""
add_hedonic_valuations.py
--------------------------
Adds XGBoost hedonic model predictions to opportunity.valuations for CBR candidates
that have transaction_features available.

Updates triangulated valuations by triangulating comparables + hedonic.

Run:
  py src/opportunity/add_hedonic_valuations.py
  py src/opportunity/add_hedonic_valuations.py --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()

MODEL_VERSION = "v1.0"
MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "hedonic_model_v1.pkl"


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


def load_model():
    bundle = joblib.load(MODEL_PATH)
    return bundle["model"], bundle["feature_cols"], bundle.get("metrics", {})


def predict_hedonic(engine, model, feature_cols: list[str], batch_size: int = 10000) -> int:
    """
    Load candidate features from transaction_features, run XGBoost predictions,
    write hedonic_xgb valuations.
    """
    logger.info("Loading candidates with transaction_features...")

    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT
                oc.id AS candidate_id,
                oc.surface_land_m2,
                oc.surface_building_m2,
                -- From transaction_features via CBR link
                tf.gap_pct,
                tf.price_percentile_50,
                tf.dist_km_centroid,
                tf.cluster_id,
                tf.season_index,
                tf.age,
                tf.age_sq,
                tf.log_surface,
                tf.construction_year_bucket,
                tf.city_zone,
                -- From transactions_clean
                tc.project_type,
                tc.county_name,
                tc.year,
                tc.quarter,
                tc.surface_m2,
                tc.surface_building_m2 AS tc_surf_build,
                tc.surface_land_m2 AS tc_surf_land,
                tc.data_confidence
            FROM opportunity.candidates oc
            JOIN transactions_clean tc
                ON oc.source = 'cbr_transaction' AND oc.source_id = tc.id::TEXT
            JOIN transaction_features tf ON tf.clean_id = tc.id
            WHERE NOT EXISTS (
                SELECT 1 FROM opportunity.valuations v
                WHERE v.candidate_id = oc.id AND v.method = 'hedonic_xgb'
            )
            ORDER BY oc.id
        """), conn)

    logger.info(f"  {len(df):,} candidates eligible for hedonic valuation")
    if df.empty:
        return 0

    # Load label encoders
    enc_path = MODEL_PATH.parent / "label_encoders_v1.pkl"
    encoders = joblib.load(enc_path) if enc_path.exists() else {}

    # Prepare features
    df["surface_m2"] = df["surface_m2"].fillna(df["surface_building_m2"].fillna(df["surface_land_m2"].fillna(80)))
    df["surface_building_m2"] = df["tc_surf_build"].fillna(df["surface_building_m2"].fillna(0))
    df["surface_land_m2_feat"] = df["tc_surf_land"].fillna(df["surface_land_m2"].fillna(0))

    # Encode categoricals
    for col in ["project_type", "county_name", "construction_year_bucket", "city_zone"]:
        if col in encoders and col in df.columns:
            le = encoders[col]
            df[col] = df[col].fillna("unknown")
            known = set(le.classes_)
            df[col] = df[col].apply(lambda x: x if x in known else "unknown")
            try:
                df[col] = le.transform(df[col])
            except Exception:
                df[col] = 0
        else:
            df[col] = df[col].fillna(0).astype(float) if col in df.columns else 0

    # Fill numeric features
    for col in ["year", "quarter", "season_index", "dist_km_centroid", "cluster_id",
                "price_percentile_50", "age", "age_sq", "log_surface"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Build feature matrix
    feat_map = {
        "surface_m2":                 "surface_m2",
        "surface_building_m2":        "surface_building_m2",
        "surface_land_m2":            "surface_land_m2_feat",
    }
    X = pd.DataFrame()
    for col in feature_cols:
        mapped = feat_map.get(col, col)
        if mapped in df.columns:
            X[col] = df[mapped].values
        else:
            X[col] = 0.0

    X = X.fillna(0).astype(float)

    logger.info(f"  Predicting {len(X):,} rows...")
    preds = model.predict(X.values)  # UF/m2

    # Compute UF total
    surface = df["surface_m2"].values.clip(1)
    pred_uf = preds * surface

    # Write to DB in batches
    insert_sql = text("""
        INSERT INTO opportunity.valuations
            (candidate_id, method, model_version, estimated_uf, estimated_uf_m2,
             p25_uf, p50_uf, p75_uf, confidence, inputs)
        VALUES
            (:cid, 'hedonic_xgb', :ver, :uf, :uf_m2,
             :p25, :p50, :p75, :conf, :inputs)
        ON CONFLICT DO NOTHING
    """)

    # RMSE pct ~40% → use as confidence proxy
    written = 0
    for start in range(0, len(df), batch_size):
        batch_cids = df["candidate_id"].values[start:start + batch_size]
        batch_preds = preds[start:start + batch_size]
        batch_uf = pred_uf[start:start + batch_size]
        batch_conf = df["data_confidence"].values[start:start + batch_size]

        with engine.begin() as conn:
            for i, (cid, pred_m2, uf, conf) in enumerate(
                zip(batch_cids, batch_preds, batch_uf, batch_conf)
            ):
                # p25/p75 using RMSE ±40% as uncertainty band
                rmse_band = float(uf) * 0.40
                conn.execute(insert_sql, {
                    "cid": int(cid),
                    "ver": MODEL_VERSION,
                    "uf": round(float(uf), 0),
                    "uf_m2": round(float(pred_m2), 4),
                    "p25": round(float(uf) - rmse_band, 0),
                    "p50": round(float(uf), 0),
                    "p75": round(float(uf) + rmse_band, 0),
                    "conf": round(float(conf) if conf == conf else 0.5, 2),
                    "inputs": json.dumps({"model": "xgboost_v1.0", "rmse_pct": 40.0}),
                })
        written += len(batch_cids)
        logger.info(f"  {written:,}/{len(df):,} hedonic valuations written")

    return written


def update_triangulated(engine) -> int:
    """Re-triangulate using both comparables + hedonic where available."""
    logger.info("Re-triangulating valuations (comparables + hedonic)...")
    import psycopg2
    conn_pg = psycopg2.connect(_build_db_url())
    conn_pg.autocommit = False
    cur = conn_pg.cursor()

    cur.execute("""
        UPDATE opportunity.valuations t
        SET
            estimated_uf    = sub.new_mid,
            estimated_uf_m2 = sub.new_mid / NULLIF(sub.surface, 1),
            p25_uf          = sub.new_p25,
            p50_uf          = sub.new_mid,
            p75_uf          = sub.new_p75,
            confidence      = sub.new_conf,
            inputs          = json_build_object('n_methods', sub.n_methods, 'methods', sub.methods)
        FROM (
            SELECT
                c.candidate_id,
                GREATEST(COALESCE(oc.surface_building_m2, oc.surface_land_m2, 80), 1) AS surface,
                ROUND(((COALESCE(comp.estimated_uf, 0) + COALESCE(hed.estimated_uf, 0)) /
                    NULLIF(
                        (CASE WHEN comp.estimated_uf IS NOT NULL THEN 1 ELSE 0 END +
                         CASE WHEN hed.estimated_uf IS NOT NULL THEN 1 ELSE 0 END), 0
                    ))::NUMERIC, 0) AS new_mid,
                ROUND(LEAST(
                    COALESCE(comp.p25_uf, comp.estimated_uf * 0.75),
                    COALESCE(hed.p25_uf,  hed.estimated_uf * 0.60)
                )::NUMERIC, 0) AS new_p25,
                ROUND(GREATEST(
                    COALESCE(comp.p75_uf, comp.estimated_uf * 1.25),
                    COALESCE(hed.p75_uf,  hed.estimated_uf * 1.40)
                )::NUMERIC, 0) AS new_p75,
                ROUND((
                    COALESCE(comp.confidence, 0) * 0.5 +
                    COALESCE(hed.confidence, 0) * 0.5
                )::NUMERIC, 2) AS new_conf,
                (CASE WHEN comp.estimated_uf IS NOT NULL THEN 1 ELSE 0 END +
                 CASE WHEN hed.estimated_uf IS NOT NULL THEN 1 ELSE 0 END) AS n_methods,
                ARRAY_REMOVE(ARRAY[
                    CASE WHEN comp.estimated_uf IS NOT NULL THEN 'comparables' END,
                    CASE WHEN hed.estimated_uf IS NOT NULL THEN 'hedonic_xgb' END
                ], NULL) AS methods
            FROM (SELECT DISTINCT candidate_id FROM opportunity.valuations WHERE method='hedonic_xgb') c
            JOIN opportunity.candidates oc ON oc.id = c.candidate_id
            LEFT JOIN opportunity.valuations comp
                ON comp.candidate_id = c.candidate_id AND comp.method = 'comparables'
            LEFT JOIN opportunity.valuations hed
                ON hed.candidate_id  = c.candidate_id AND hed.method  = 'hedonic_xgb'
        ) sub
        WHERE t.candidate_id = sub.candidate_id
          AND t.method = 'triangulated'
          AND sub.n_methods > 1
          AND sub.new_mid IS NOT NULL
    """)
    n = cur.rowcount
    conn_pg.commit()
    cur.close()
    conn_pg.close()
    logger.info(f"  Re-triangulated {n:,} valuations (2-method average)")
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=10000)
    args = parser.parse_args()

    engine = create_engine(_build_db_url(), pool_pre_ping=True, pool_size=5)
    model, feature_cols, metrics = load_model()
    logger.info(f"Model loaded: R²={metrics.get('r2', '?')}, RMSE={metrics.get('rmse_pct_of_median', '?')}%")

    logger.info("=" * 60)
    logger.info("HEDONIC XGBoost VALUATIONS")
    logger.info("=" * 60)

    if args.dry_run:
        with engine.connect() as conn:
            n = conn.execute(text("""
                SELECT COUNT(DISTINCT oc.id)
                FROM opportunity.candidates oc
                JOIN transactions_clean tc ON oc.source='cbr_transaction' AND oc.source_id=tc.id::TEXT
                JOIN transaction_features tf ON tf.clean_id=tc.id
                WHERE NOT EXISTS (
                    SELECT 1 FROM opportunity.valuations v WHERE v.candidate_id=oc.id AND v.method='hedonic_xgb'
                )
            """)).scalar()
        logger.info(f"[DRY RUN] Would predict {n:,} candidates")
        return

    n_pred = predict_hedonic(engine, model, feature_cols, args.batch_size)
    logger.info(f"Hedonic predictions: {n_pred:,}")

    n_tri = update_triangulated(engine)
    logger.info(f"Triangulated updated: {n_tri:,}")

    with engine.connect() as conn:
        r = conn.execute(text("""
            SELECT method, COUNT(*), ROUND(AVG(confidence)::NUMERIC,2)
            FROM opportunity.valuations GROUP BY method ORDER BY method
        """)).fetchall()
        for row in r:
            logger.info(f"  {row[0]:15s}  {row[1]:,} rows  conf={row[2]}")

    logger.info("=" * 60)


if __name__ == "__main__":
    main()
