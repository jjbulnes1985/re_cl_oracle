"""
scores.py
---------
FastAPI routes for model scores and summaries.

Endpoints:
  GET /scores/{score_id}     — Full score detail including SHAP
  GET /scores/summary        — Aggregate score statistics
  GET /scores/top            — Top-N highest opportunity scores
"""

from typing import Any, Dict, List, Optional
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.api.db import get_engine

router = APIRouter(prefix="/scores", tags=["scores"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ShapFeature(BaseModel):
    feature:   str
    shap:      float
    direction: str


class ScoreDetail(BaseModel):
    score_id:             int
    clean_id:             Optional[int]
    model_version:        Optional[str]
    opportunity_score:    Optional[float]
    undervaluation_score: Optional[float]
    data_confidence:      Optional[float]
    predicted_uf_m2:      Optional[float]
    actual_uf_m2:         Optional[float]
    gap_pct:              Optional[float]
    gap_percentile:       Optional[float]
    shap_top_features:    Optional[List[ShapFeature]]
    county_name:          Optional[str]
    project_type:         Optional[str]


class ScoreSummary(BaseModel):
    total_scored:  int
    mean_score:    float
    min_score:     float
    max_score:     float
    high_opp_count: int
    model_version: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=ScoreSummary)
def score_summary(engine: Engine = Depends(get_engine)):
    """Return aggregate statistics for the current model version."""
    from src.api.db import MODEL_VERSION
    query = text("""
        SELECT
            COUNT(*)                                    AS total_scored,
            ROUND(AVG(opportunity_score)::numeric, 4)  AS mean_score,
            ROUND(MIN(opportunity_score)::numeric, 4)  AS min_score,
            ROUND(MAX(opportunity_score)::numeric, 4)  AS max_score,
            COUNT(*) FILTER (WHERE opportunity_score > 0.7) AS high_opp_count
        FROM model_scores
        WHERE model_version = :v
    """)
    with engine.connect() as conn:
        row = conn.execute(query, {"v": MODEL_VERSION}).mappings().first()
    if row is None or row["total_scored"] == 0:
        raise HTTPException(status_code=404, detail="No scores found. Run opportunity_score.py first.")
    return ScoreSummary(model_version=MODEL_VERSION, **dict(row))


@router.get("/top", response_model=List[ScoreDetail])
def top_scores(
    n:             int           = Query(10, ge=1, le=500),
    project_type:  Optional[str] = Query(None),
    county_name:   Optional[str] = Query(None),
    engine:        Engine        = Depends(get_engine),
):
    """Return top-N highest opportunity scores."""
    from src.api.db import MODEL_VERSION
    filters = ["ms.model_version = :v"]
    params: dict = {"v": MODEL_VERSION, "n": n}

    if project_type:
        filters.append("tc.project_type = :project_type")
        params["project_type"] = project_type
    if county_name:
        filters.append("tc.county_name = :county_name")
        params["county_name"] = county_name

    where = " AND ".join(filters)
    query = text(f"""
        SELECT
            ms.id AS score_id, ms.clean_id, ms.model_version,
            ms.opportunity_score, ms.undervaluation_score,
            ms.data_confidence, ms.predicted_uf_m2, ms.actual_uf_m2,
            ms.gap_pct, ms.gap_percentile, ms.shap_top_features,
            tc.county_name, tc.project_type
        FROM model_scores ms
        JOIN transactions_clean tc ON tc.id = ms.clean_id
        WHERE {where}
        ORDER BY ms.opportunity_score DESC
        LIMIT :n
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().all()

    result = []
    for r in rows:
        d = dict(r)
        if d.get("shap_top_features"):
            try:
                d["shap_top_features"] = [
                    ShapFeature(**item)
                    for item in json.loads(d["shap_top_features"])
                ]
            except Exception:
                d["shap_top_features"] = None
        result.append(ScoreDetail(**d))
    return result


@router.get("/{score_id}", response_model=ScoreDetail)
def get_score(
    score_id: int,
    engine:   Engine = Depends(get_engine),
):
    """Get full score detail for a property."""
    query = text("""
        SELECT
            ms.id AS score_id, ms.clean_id, ms.model_version,
            ms.opportunity_score, ms.undervaluation_score,
            ms.data_confidence, ms.predicted_uf_m2, ms.actual_uf_m2,
            ms.gap_pct, ms.gap_percentile, ms.shap_top_features,
            tc.county_name, tc.project_type
        FROM model_scores ms
        JOIN transactions_clean tc ON tc.id = ms.clean_id
        WHERE ms.id = :sid
        LIMIT 1
    """)
    with engine.connect() as conn:
        row = conn.execute(query, {"sid": score_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Score {score_id} not found")

    d = dict(row)
    if d.get("shap_top_features"):
        try:
            d["shap_top_features"] = [
                ShapFeature(**item)
                for item in json.loads(d["shap_top_features"])
            ]
        except Exception:
            d["shap_top_features"] = None
    return ScoreDetail(**d)
