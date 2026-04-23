"""
analytics.py - Price trends and temporal analytics endpoints
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine
from src.api.db import get_engine

router = APIRouter(prefix="/analytics", tags=["analytics"])


class PriceTrendPoint(BaseModel):
    year: int
    quarter: int
    period: str          # "2013-Q1" format
    median_uf_m2: float
    n_transactions: int
    mean_uf_m2: float
    p25_uf_m2: Optional[float]
    p75_uf_m2: Optional[float]


class CommuneTrend(BaseModel):
    county_name: str
    trend: List[PriceTrendPoint]


@router.get("/price-trend", response_model=List[PriceTrendPoint])
def price_trend(
    project_type: Optional[str] = Query(None),
    county_name:  Optional[str] = Query(None),
    engine: Engine = Depends(get_engine),
):
    """Price trend over time (quarterly). Filter by type or commune."""
    filters = ["uf_m2_building IS NOT NULL", "is_outlier = FALSE"]
    params = {}
    if project_type:
        filters.append("project_type = :project_type")
        params["project_type"] = project_type
    if county_name:
        filters.append("county_name = :county_name")
        params["county_name"] = county_name
    where = " AND ".join(filters)
    query = text(f"""
        SELECT year, quarter,
               CONCAT(year, '-Q', quarter) AS period,
               ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY uf_m2_building)::numeric, 2) AS median_uf_m2,
               ROUND(AVG(uf_m2_building)::numeric, 2) AS mean_uf_m2,
               ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY uf_m2_building)::numeric, 2) AS p25_uf_m2,
               ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY uf_m2_building)::numeric, 2) AS p75_uf_m2,
               COUNT(*) AS n_transactions
        FROM transactions_clean
        WHERE {where}
        GROUP BY year, quarter
        ORDER BY year, quarter
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().all()
    return [PriceTrendPoint(**dict(r)) for r in rows]


@router.get("/price-trend/by-commune", response_model=List[CommuneTrend])
def price_trend_by_commune(
    top_n: int = Query(8, ge=1, le=20),
    project_type: Optional[str] = Query(None),
    engine: Engine = Depends(get_engine),
):
    """Price trend by top N communes (by transaction volume)."""
    type_filter = "AND project_type = :project_type" if project_type else ""
    params: dict = {"top_n": top_n}
    if project_type:
        params["project_type"] = project_type

    communes_q = text(f"""
        SELECT county_name FROM transactions_clean
        WHERE is_outlier = FALSE AND uf_m2_building IS NOT NULL {type_filter}
        GROUP BY county_name ORDER BY COUNT(*) DESC LIMIT :top_n
    """)
    with engine.connect() as conn:
        top_communes = [r[0] for r in conn.execute(communes_q, params).fetchall()]

    result = []
    for commune in top_communes:
        trend_data = price_trend(
            project_type=project_type,
            county_name=commune,
            engine=engine,
        )
        result.append(CommuneTrend(county_name=commune, trend=trend_data))
    return result


@router.get("/score-distribution")
def score_distribution(engine: Engine = Depends(get_engine)):
    """Distribution of opportunity scores by decile."""
    query = text("""
        SELECT
            width_bucket(opportunity_score, 0, 1, 10) AS decile,
            COUNT(*) AS n,
            ROUND(AVG(opportunity_score)::numeric, 3) AS mean_score,
            ROUND(AVG(gap_pct)::numeric, 4) AS mean_gap_pct
        FROM model_scores
        GROUP BY decile ORDER BY decile
    """)
    with engine.connect() as conn:
        rows = conn.execute(query).mappings().all()
    return [dict(r) for r in rows]
