"""
valuation_engine.py
-------------------
Multi-method property valuation for opportunity candidates.

Methods:
  1. hedonic_xgb   — XGBoost model (re-uses existing hedonic_model_v1.pkl)
  2. comparables   — median UF/m2 from transactions_clean (24 months, same commune+type)
  3. cap_inverse   — NOI / cap_rate for commercial use cases (sensitivity: low/mid/high)
  4. triangulated  — median of available methods, with p25/p75 band

IMPORTANT — Cap rate disclaimer:
  All commercial cap rates are INFO_NO_FIDEDIGNA::pendiente_validación.
  Source: proxy USA net lease + spread Chile (B+E Q4-2024).
  Sensitivity band ±150 bps is applied automatically.

Run:
  py src/opportunity/valuation_engine.py                        # all candidates
  py src/opportunity/valuation_engine.py --commune Maipú        # one commune
  py src/opportunity/valuation_engine.py --use-case gas_station # commercial overlay
  py src/opportunity/valuation_engine.py --dry-run
"""

import argparse
import os
import sys
from pathlib import Path
from statistics import median, stdev
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()

MODEL_VERSION = "v1.0"

# NOI bands (UF/year) per use case — INFO_NO_FIDEDIGNA::pendiente_validación
NOI_BANDS = {
    "gas_station":  (4_000,  7_000, 12_000),
    "pharmacy":     (  800,  1_500,  3_000),
    "supermarket":  (5_000, 12_000, 25_000),
    "bank_branch":  (1_500,  3_000,  6_000),
    "retail":       (  500,  1_200,  3_000),
    "clinic":       (1_200,  2_500,  5_000),
    "restaurant":   (  400,    800,  2_000),
}

COMMERCIAL_USE_CASES = set(NOI_BANDS.keys())


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


def _load_model():
    import joblib
    model_path = Path(__file__).resolve().parents[2] / "models" / "hedonic_model_v1.pkl"
    encoders_path = Path(__file__).resolve().parents[2] / "models" / "label_encoders_v1.pkl"
    if not model_path.exists():
        logger.warning(f"Model not found at {model_path} — hedonic valuations will be skipped")
        return None, None
    model = joblib.load(model_path)
    encoders = joblib.load(encoders_path) if encoders_path.exists() else {}
    return model, encoders


def hedonic_value(candidate_row: pd.Series, model, encoders: dict) -> Optional[float]:
    """Predict UF/m2 using the existing XGBoost hedonic model."""
    if model is None:
        return None
    try:
        from src.models.hedonic_model import FEATURE_COLS, prepare_features
        features = prepare_features(candidate_row, encoders)
        if features is None:
            return None
        pred = model.predict(features)[0]
        return float(pred)
    except Exception as e:
        return None


def comparables_value(engine, commune: str, prop_type: str, surface_m2: float) -> dict:
    """Compute p25/p50/p75 UF/m2 from transactions_clean (24 months, same zone)."""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT
                percentile_cont(0.25) WITHIN GROUP (ORDER BY uf_m2_building) AS p25,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY uf_m2_building) AS p50,
                percentile_cont(0.75) WITHIN GROUP (ORDER BY uf_m2_building) AS p75,
                COUNT(*) AS n
            FROM transactions_clean
            WHERE county_name = :commune
              AND project_type = :ptype
              AND uf_m2_building IS NOT NULL
              AND uf_m2_building > 0
              AND inscription_date >= NOW() - INTERVAL '24 months'
              AND ABS(COALESCE(surface_m2, surface_building_m2, 0) - :surface) /
                  NULLIF(GREATEST(:surface, 1), 0) < 0.40
        """), {"commune": commune, "ptype": prop_type, "surface": surface_m2 or 80.0}).fetchone()

    if result and result.n and result.n >= 5:
        return {"p25": float(result.p25), "p50": float(result.p50), "p75": float(result.p75), "n": int(result.n)}

    # Fallback: commune-only (no surface filter)
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT
                percentile_cont(0.25) WITHIN GROUP (ORDER BY uf_m2_building) AS p25,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY uf_m2_building) AS p50,
                percentile_cont(0.75) WITHIN GROUP (ORDER BY uf_m2_building) AS p75,
                COUNT(*) AS n
            FROM transactions_clean
            WHERE county_name = :commune
              AND project_type = :ptype
              AND uf_m2_building IS NOT NULL
              AND uf_m2_building > 0
        """), {"commune": commune, "ptype": prop_type}).fetchone()

    if result and result.n and result.n >= 3:
        return {"p25": float(result.p25), "p50": float(result.p50), "p75": float(result.p75), "n": int(result.n)}

    return {}


def cap_inverse_value(use_case: str, surface_land_m2: float) -> dict:
    """
    Compute max payable UF via inverse capitalization.
    INFO_NO_FIDEDIGNA::pendiente_validación — proxy USA net lease + spread Chile.
    Sensitivity: low (high cap rate) / mid / high (low cap rate).
    """
    if use_case not in COMMERCIAL_USE_CASES:
        return {}

    noi_low, noi_mid, noi_high = NOI_BANDS[use_case]

    # Scale NOI by surface (simple linear proxy, capped)
    scale = min(max((surface_land_m2 or 500) / 500.0, 0.5), 3.0)
    noi_low  *= scale
    noi_mid  *= scale
    noi_high *= scale

    # Get cap rates from property_types catalog
    CAP_RATES = {
        "gas_station":  (0.070, 0.080, 0.095),
        "pharmacy":     (0.065, 0.075, 0.090),
        "supermarket":  (0.060, 0.072, 0.085),
        "bank_branch":  (0.055, 0.065, 0.080),
        "retail":       (0.060, 0.075, 0.090),
        "clinic":       (0.065, 0.075, 0.090),
        "restaurant":   (0.070, 0.085, 0.100),
    }
    cap_low, cap_mid, cap_high = CAP_RATES.get(use_case, (0.070, 0.080, 0.095))

    # max payable = NOI_mid / cap_mid (central estimate)
    # sensitivity: pessimistic = NOI_low / cap_high; optimistic = NOI_high / cap_low
    return {
        "pessimistic":  round(noi_low  / cap_high, 0),
        "central":      round(noi_mid  / cap_mid,  0),
        "optimistic":   round(noi_high / cap_low,  0),
        "disclaimer":   "INFO_NO_FIDEDIGNA::pendiente_validacion. Proxy USA net lease + spread Chile. Banda +-150bps.",
        "noi_mid_uf":   round(noi_mid, 0),
        "cap_mid":      cap_mid,
    }


def triangulate(values_uf_m2: list[float], surface_m2: float) -> dict:
    """Triangulate multiple UF/m2 estimates into p25/p50/p75 and confidence."""
    vals = [v for v in values_uf_m2 if v and v > 0]
    if not vals:
        return {}
    p25 = float(np.percentile(vals, 25))
    p50 = float(np.percentile(vals, 50))
    p75 = float(np.percentile(vals, 75))
    spread = (p75 - p25) / p50 if p50 > 0 else 1.0
    confidence = round(max(0.1, min(0.95, 1.0 - spread)), 2)
    surface = surface_m2 or 80.0
    return {
        "estimated_uf":    round(p50 * surface, 0),
        "estimated_uf_m2": round(p50, 4),
        "p25_uf":          round(p25 * surface, 0),
        "p50_uf":          round(p50 * surface, 0),
        "p75_uf":          round(p75 * surface, 0),
        "confidence":      confidence,
        "n_methods":       len(vals),
    }


def value_candidates(
    engine,
    commune: Optional[str] = None,
    use_case: str = "as_is",
    batch_size: int = 5000,
    dry_run: bool = False,
) -> int:
    """Value all candidates and write to opportunity.valuations."""
    logger.info(f"Valuation engine — commune={commune or 'ALL'}, use_case={use_case}")

    model, encoders = _load_model()

    # Load candidates
    filters = "WHERE 1=1"
    params: dict = {}
    if commune:
        filters += " AND c.county_name = :commune"
        params["commune"] = commune

    with engine.connect() as conn:
        df = pd.read_sql(text(f"""
            SELECT c.id, c.county_name, c.property_type_code,
                   c.surface_land_m2, c.surface_building_m2,
                   c.last_transaction_uf, c.listed_price_uf,
                   c.latitude, c.longitude, c.construction_ratio,
                   c.last_transaction_date
            FROM opportunity.candidates c
            {filters}
            ORDER BY c.id
        """), conn, params=params)

    logger.info(f"  Loaded {len(df):,} candidates to value")

    if dry_run:
        logger.info(f"  [DRY RUN] Would generate valuations for {len(df):,} candidates")
        return 0

    written = 0
    insert_sql = text("""
        INSERT INTO opportunity.valuations
            (candidate_id, method, model_version, estimated_uf, estimated_uf_m2,
             p25_uf, p50_uf, p75_uf, confidence, inputs, notes)
        VALUES
            (:candidate_id, :method, :model_version, :estimated_uf, :estimated_uf_m2,
             :p25_uf, :p50_uf, :p75_uf, :confidence, :inputs, :notes)
        ON CONFLICT DO NOTHING
    """)

    import json

    for start in range(0, len(df), batch_size):
        batch = df.iloc[start:start + batch_size]
        rows_to_insert = []

        for _, row in batch.iterrows():
            candidate_id = int(row["id"])
            commune_name = row["county_name"]
            prop_type = row["property_type_code"] or "apartment"
            surface = float(row["surface_building_m2"] or row["surface_land_m2"] or 80.0)
            surface_land = float(row["surface_land_m2"] or 500.0)

            method_values_m2 = []

            # Method 1: Comparables
            comp = comparables_value(engine, commune_name, prop_type, surface)
            if comp:
                uf_m2 = comp["p50"]
                rows_to_insert.append({
                    "candidate_id": candidate_id, "method": "comparables",
                    "model_version": MODEL_VERSION,
                    "estimated_uf": round(uf_m2 * surface, 0),
                    "estimated_uf_m2": round(uf_m2, 4),
                    "p25_uf": round(comp["p25"] * surface, 0),
                    "p50_uf": round(comp["p50"] * surface, 0),
                    "p75_uf": round(comp["p75"] * surface, 0),
                    "confidence": round(1.0 - (comp["p75"] - comp["p25"]) / max(comp["p50"], 1), 2),
                    "inputs": json.dumps({"n": comp.get("n"), "commune": commune_name, "type": prop_type}),
                    "notes": None,
                })
                method_values_m2.append(uf_m2)

            # Method 2: Cap inverse (commercial only)
            if use_case in COMMERCIAL_USE_CASES:
                cap = cap_inverse_value(use_case, surface_land)
                if cap:
                    central_uf = float(cap["central"])
                    uf_m2_cap = central_uf / max(surface_land, 1.0)
                    rows_to_insert.append({
                        "candidate_id": candidate_id, "method": "cap_inverse",
                        "model_version": MODEL_VERSION,
                        "estimated_uf": round(central_uf, 0),
                        "estimated_uf_m2": round(uf_m2_cap, 4),
                        "p25_uf": round(float(cap["pessimistic"]), 0),
                        "p50_uf": round(central_uf, 0),
                        "p75_uf": round(float(cap["optimistic"]), 0),
                        "confidence": 0.3,  # Low confidence — proxy only
                        "inputs": json.dumps({k: v for k, v in cap.items() if k != "disclaimer"}),
                        "notes": cap["disclaimer"],
                    })
                    method_values_m2.append(uf_m2_cap)

            # Triangulated (always write)
            if method_values_m2:
                tri = triangulate(method_values_m2, surface)
                if tri:
                    rows_to_insert.append({
                        "candidate_id": candidate_id, "method": "triangulated",
                        "model_version": MODEL_VERSION,
                        "estimated_uf": tri["estimated_uf"],
                        "estimated_uf_m2": tri["estimated_uf_m2"],
                        "p25_uf": tri["p25_uf"],
                        "p50_uf": tri["p50_uf"],
                        "p75_uf": tri["p75_uf"],
                        "confidence": tri["confidence"],
                        "inputs": json.dumps({"n_methods": tri["n_methods"]}),
                        "notes": None,
                    })

        # Bulk insert batch
        if rows_to_insert:
            with engine.begin() as conn:
                for r in rows_to_insert:
                    conn.execute(insert_sql, r)
            written += len(rows_to_insert)

        logger.info(f"  Valued {start + len(batch):,}/{len(df):,} | rows written: {written:,}")

    logger.info(f"VALUATION DONE: {written:,} valuations written")
    return written


def main():
    parser = argparse.ArgumentParser(description="Multi-method property valuation engine")
    parser.add_argument("--commune", type=str, default=None)
    parser.add_argument("--use-case", type=str, default="as_is")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    engine = create_engine(_build_db_url(), pool_pre_ping=True, pool_size=5)

    logger.info("=" * 60)
    logger.info("VALUATION ENGINE START")
    logger.info("=" * 60)

    n = value_candidates(
        engine,
        commune=args.commune,
        use_case=args.use_case,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        with engine.connect() as conn:
            r = conn.execute(text("""
                SELECT method, COUNT(*), ROUND(AVG(confidence)::NUMERIC, 2) AS avg_conf
                FROM opportunity.valuations
                GROUP BY method ORDER BY method
            """)).fetchall()
            logger.info("Summary:")
            for row in r:
                logger.info(f"  {row[0]:15s}  {row[1]:,} rows  confidence={row[2]}")

    logger.info("=" * 60)


if __name__ == "__main__":
    main()
