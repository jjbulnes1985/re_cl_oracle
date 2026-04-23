"""
predict.py
----------
FastAPI route for property price prediction.

POST /predict — given property attributes, predicts expected UF/m² using the
hedonic XGBoost model. Fully independent of the database.

Model features mirror those in src/models/hedonic_model.py and the V4.1
thesis feature set (age, age_sq, log_surface, construction_year_bucket, city_zone).
"""

import pickle
from functools import lru_cache
from math import log
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# ── Paths ─────────────────────────────────────────────────────────────────────
# Support both the repo-root "models/" dir and "data/processed/" (training output)
_REPO_ROOT = Path(__file__).parent.parent.parent.parent  # re_cl/

_MODEL_CANDIDATES = [
    _REPO_ROOT / "models" / "hedonic_model_v1.pkl",
    _REPO_ROOT / "data" / "processed" / "hedonic_model_v1.pkl",
]
_ENCODER_CANDIDATES = [
    _REPO_ROOT / "models" / "label_encoders_v1.pkl",
    _REPO_ROOT / "data" / "processed" / "label_encoders_v1.pkl",
]

# ── Categorical/numeric features — must match hedonic_model.py ────────────────
CAT_FEATURES = ["project_type", "county_name", "construction_year_bucket", "city_zone"]
NUM_FEATURES = [
    "year", "quarter", "season_index",
    "surface_m2", "surface_building_m2", "surface_land_m2",
    "dist_km_centroid", "cluster_id", "data_confidence",
    "price_percentile_50",
    "age", "age_sq", "log_surface",
]

# Communes seen during training (RM Santiago CBR data 2013-2014)
_KNOWN_COMMUNES = {
    "Santiago", "Providencia", "Ñuñoa", "Macul", "San Joaquín", "Recoleta",
    "Independencia", "Conchalí", "Huechuraba", "Renca", "Cerro Navia",
    "Lo Prado", "Quinta Normal", "Estación Central",
    "Las Condes", "Vitacura", "Lo Barnechea", "La Reina", "Peñalolén", "La Florida",
    "La Pintana", "San Ramón", "La Granja", "San Miguel", "Lo Espejo",
    "Pedro Aguirre Cerda", "El Bosque", "La Cisterna", "San Bernardo",
    "Puente Alto", "Pirque", "San José De Maipo", "Colina", "Lampa",
    "Tiltil", "Quilicura",
    "Maipú", "Cerrillos", "Padre Hurtado", "Peñaflor", "El Monte",
    "Isla De Maipo", "Melipilla", "Curacaví", "Alhué", "San Pedro", "Pudahuel",
}

_CITY_ZONE_MAP = {
    "Santiago": "centro_norte", "Providencia": "centro_norte",
    "Ñuñoa": "centro_norte", "Macul": "centro_norte",
    "San Joaquín": "centro_norte", "Recoleta": "centro_norte",
    "Independencia": "centro_norte", "Conchalí": "centro_norte",
    "Huechuraba": "centro_norte", "Renca": "centro_norte",
    "Cerro Navia": "centro_norte", "Lo Prado": "centro_norte",
    "Quinta Normal": "centro_norte", "Estación Central": "centro_norte",
    "Las Condes": "este", "Vitacura": "este", "Lo Barnechea": "este",
    "La Reina": "este", "Peñalolén": "este", "La Florida": "este",
    "La Pintana": "sur", "San Ramón": "sur", "La Granja": "sur",
    "San Miguel": "sur", "Lo Espejo": "sur", "Pedro Aguirre Cerda": "sur",
    "El Bosque": "sur", "La Cisterna": "sur", "San Bernardo": "sur",
    "Puente Alto": "sur", "Pirque": "sur", "San José De Maipo": "sur",
    "Colina": "sur", "Lampa": "sur", "Tiltil": "sur", "Quilicura": "sur",
    "Maipú": "oeste", "Cerrillos": "oeste", "Padre Hurtado": "oeste",
    "Peñaflor": "oeste", "El Monte": "oeste", "Isla De Maipo": "oeste",
    "Melipilla": "oeste", "Curacaví": "oeste", "Alhué": "oeste",
    "San Pedro": "oeste", "Pudahuel": "oeste",
}


def _construction_year_to_bucket(year: Optional[int]) -> str:
    """Map a construction year to the same era bucket used during training."""
    if year is None:
        return "unknown"
    if year <= 1960:
        return "pre_1960"
    elif year <= 1970:
        return "1961_1970"
    elif year <= 1980:
        return "1971_1980"
    elif year <= 1990:
        return "1981_1990"
    elif year <= 2000:
        return "1991_2000"
    elif year <= 2006:
        return "2001_2006"
    else:
        return "2007_2016"


def _find_file(candidates: list) -> Optional[Path]:
    for p in candidates:
        if p.exists():
            return p
    return None


@lru_cache(maxsize=1)
def get_model():
    """
    Load hedonic model and label encoders from disk (cached for process lifetime).
    Returns (model, encoders) tuple. Returns (None, None) if files are not found.
    """
    model_path = _find_file(_MODEL_CANDIDATES)
    encoder_path = _find_file(_ENCODER_CANDIDATES)

    if model_path is None or encoder_path is None:
        return None, None

    try:
        with open(model_path, "rb") as f:
            data = pickle.load(f)
        with open(encoder_path, "rb") as f:
            encoders = pickle.load(f)
        # hedonic_model.py wraps the model in a dict; unwrap if needed
        model = data["model"] if isinstance(data, dict) else data
        return model, encoders
    except Exception:
        return None, None


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class PredictRequest(BaseModel):
    project_type: str                          # e.g. "Departamento"
    county_name: str                           # e.g. "Las Condes"
    surface_m2: float                          # total surface in m²
    surface_building_m2: Optional[float] = None  # defaults to surface_m2
    construction_year: Optional[int] = None    # e.g. 1995; if None, age defaults to 10
    year: int = 2014                           # transaction year (model trained on 2013-2014)
    quarter: int = 4                           # quarter 1-4
    city_zone: Optional[str] = None            # centro_norte/este/oeste/sur (auto-detected if None)
    dist_metro_km: float = 2.0
    dist_school_km: float = 1.5
    amenities_500m: int = 5


class PredictResponse(BaseModel):
    predicted_uf_m2: float
    predicted_uf_total: float                  # predicted_uf_m2 × surface_building_m2
    gap_pct_vs_median: Optional[float] = None  # None if no commune median available
    confidence: str                            # "high" / "medium" / "low"
    note: str                                  # explanation


# ── Router ────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/predict", tags=["predict"])


def _encode_categorical(encoders: dict, feature: str, value: str) -> int:
    """Apply label encoder to a single value, falling back to 0 on unseen label."""
    if feature not in encoders:
        return 0
    le = encoders[feature]
    try:
        return int(le.transform([value])[0])
    except (ValueError, KeyError):
        # Unseen label — try encoding as "unknown" if the encoder knows it,
        # otherwise default to 0
        try:
            return int(le.transform(["unknown"])[0])
        except Exception:
            return 0


@router.post("", response_model=PredictResponse)
def predict_price(req: PredictRequest):
    """
    Predict the expected UF/m² for a property given its attributes.

    The model (XGBoost hedonic, V4.1) was trained on CBR RM Santiago data
    2013-2014. Predictions are most reliable for properties matching that
    distribution. Confidence reflects data completeness and commune coverage.
    """
    model, encoders = get_model()

    if model is None or encoders is None:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Run the training pipeline first.",
        )

    # ── Derived scalars ───────────────────────────────────────────────────────
    surface_building = req.surface_building_m2 if req.surface_building_m2 is not None else req.surface_m2

    age = (2014 - req.construction_year) if req.construction_year is not None else 10
    age = max(0, age)  # clip negative ages
    age_sq = age ** 2

    log_surface = log(surface_building + 1)  # log1p

    season_index = 0.6 if req.quarter == 4 else 0.4

    construction_year_bucket = _construction_year_to_bucket(req.construction_year)

    # city_zone: use explicit value or auto-detect from county_name
    city_zone = req.city_zone if req.city_zone else _CITY_ZONE_MAP.get(req.county_name, "unknown")

    # ── Build feature row ─────────────────────────────────────────────────────
    row: dict = {
        # Categorical (will be label-encoded below)
        "project_type":             req.project_type,
        "county_name":              req.county_name,
        "construction_year_bucket": construction_year_bucket,
        "city_zone":                city_zone,
        # Numeric — temporal
        "year":                     req.year,
        "quarter":                  req.quarter,
        "season_index":             season_index,
        # Numeric — surfaces
        "surface_m2":               req.surface_m2,
        "surface_building_m2":      surface_building,
        "surface_land_m2":          0.0,
        # Numeric — spatial defaults
        "dist_km_centroid":         5.0,
        "cluster_id":               -1,
        # Numeric — quality/confidence
        "data_confidence":          0.8,
        # Numeric — price context defaults (not available at inference time)
        "price_percentile_50":      50.0,
        # Numeric — thesis features (V4.1)
        "age":                      float(age),
        "age_sq":                   float(age_sq),
        "log_surface":              log_surface,
    }

    # ── Apply label encoders to categoricals ──────────────────────────────────
    for cat in CAT_FEATURES:
        row[cat] = _encode_categorical(encoders, cat, str(row[cat]))

    # ── Assemble DataFrame in the exact column order the model expects ─────────
    all_features = CAT_FEATURES + NUM_FEATURES
    # Fill any feature that may have been added in a future model version with 0
    for col in all_features:
        if col not in row:
            row[col] = 0.0

    df_input = pd.DataFrame([row])[all_features]

    # ── Predict ───────────────────────────────────────────────────────────────
    predicted_uf_m2 = float(model.predict(df_input)[0])
    predicted_uf_total = round(predicted_uf_m2 * surface_building, 2)
    predicted_uf_m2 = round(predicted_uf_m2, 4)

    # ── Confidence ───────────────────────────────────────────────────────────
    county_known = req.county_name in _KNOWN_COMMUNES
    has_year = req.construction_year is not None

    if not has_year or not county_known:
        confidence = "low"
    elif req.surface_m2 > 30 and county_known:
        confidence = "high"
    else:
        confidence = "medium"

    # ── Note ─────────────────────────────────────────────────────────────────
    note = (
        "Predicted by XGBoost hedonic model V4.1 trained on CBR RM Santiago 2013-2014. "
        f"age={age}yr, zone={city_zone}, bucket={construction_year_bucket}. "
        "price_percentile_50 and gap_pct defaulted to neutral values (no DB lookup)."
    )

    return PredictResponse(
        predicted_uf_m2=predicted_uf_m2,
        predicted_uf_total=predicted_uf_total,
        gap_pct_vs_median=None,
        confidence=confidence,
        note=note,
    )
