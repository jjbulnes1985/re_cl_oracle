"""
subclass.py
───────────
FastAPI routes for asset-subclass-specific scoring & heatmaps.

Endpoints:
  GET  /subclasses                   — List active subclasses with metadata
  GET  /subclasses/{name}/weights    — Detailed weight vector for a subclass
  GET  /subclasses/{name}/heatmap    — Lat/lng/score points for HeatmapLayer
  POST /subclasses/{name}/weights    — Update weights (admin only — JWT required)

Backed by:
  - asset_subclass_weights table (migration 015)
  - model_scores.subclass_scores JSONB (migration 016)
  - src/scoring/asset_subclass.py (offline scoring)
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from src.api.db import get_engine

router = APIRouter()


def _get_conn():
    engine = get_engine()
    with engine.connect() as conn:
        yield conn


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class SubclassMetadata(BaseModel):
    subclass: str
    description: str
    parent_class: str
    active: bool


class SubclassWeights(BaseModel):
    subclass: str
    description: str
    parent_class: str
    weights: dict
    sum: float


class HeatmapPoint(BaseModel):
    lat: float
    lng: float
    score: float
    candidate_id: int


class WeightsUpdate(BaseModel):
    w_underval:           float = Field(..., ge=0.0, le=1.0)
    w_cap_rate:           float = Field(..., ge=0.0, le=1.0)
    w_appreciation:       float = Field(..., ge=0.0, le=1.0)
    w_transit:            float = Field(..., ge=0.0, le=1.0)
    w_school:             float = Field(..., ge=0.0, le=1.0)
    w_traffic:            float = Field(..., ge=0.0, le=1.0)
    w_competitor_density: float = Field(..., ge=0.0, le=1.0)
    w_demographic_match:  float = Field(..., ge=0.0, le=1.0)
    w_liquidity:          float = Field(..., ge=0.0, le=1.0)
    w_regulatory_risk:    float = Field(..., ge=0.0, le=1.0)
    w_environmental_risk: float = Field(..., ge=0.0, le=1.0)
    w_data_confidence:    float = Field(..., ge=0.0, le=1.0)

    @field_validator("w_data_confidence")
    @classmethod
    def validate_sum(cls, v, info):
        # Pydantic v2: cross-field validation in model_validator preferred,
        # but for simplicity we validate in update endpoint instead.
        return v


# ─────────────────────────────────────────────────────────────────────────────
# GET /subclasses
# ─────────────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[SubclassMetadata])
def list_subclasses(
    parent_class: Optional[str] = Query(None, description="Filter: residential | commercial | land"),
    conn=Depends(_get_conn),
) -> list[SubclassMetadata]:
    """List all active subclasses, optionally filtered by parent_class."""
    sql = """
        SELECT subclass, description, parent_class, active
        FROM v_subclass_weights_active
        {where}
        ORDER BY parent_class, subclass
    """
    where_clause = ""
    params = {}
    if parent_class:
        if parent_class not in ("residential", "commercial", "land"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "parent_class must be residential|commercial|land")
        where_clause = "WHERE parent_class = :pc"
        params["pc"] = parent_class

    sql = sql.replace("{where}", where_clause)
    rows = conn.execute(text(sql), params).mappings().all()
    return [SubclassMetadata(**dict(r)) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# GET /subclasses/{name}/weights
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{name}/weights", response_model=SubclassWeights)
def get_subclass_weights(name: str, conn=Depends(_get_conn)) -> SubclassWeights:
    """Detailed weight vector for a subclass."""
    row = conn.execute(text("""
        SELECT *
        FROM asset_subclass_weights
        WHERE subclass = :name
    """), {"name": name}).mappings().first()

    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Subclass '{name}' not found")

    weight_keys = [k for k in row.keys() if k.startswith("w_")]
    weights = {k.replace("w_", ""): float(row[k]) for k in weight_keys}

    return SubclassWeights(
        subclass=row["subclass"],
        description=row["description"],
        parent_class=row["parent_class"],
        weights=weights,
        sum=round(sum(weights.values()), 4),
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /subclasses/{name}/heatmap
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{name}/heatmap", response_model=list[HeatmapPoint])
def get_subclass_heatmap(
    name: str,
    bbox: Optional[str] = Query(None, description="Optional bbox: minLng,minLat,maxLng,maxLat"),
    score_min: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(10000, le=50000),
    conn=Depends(_get_conn),
) -> list[HeatmapPoint]:
    """
    Returns lat/lng/score points for a HeatmapLayer.
    Score is the candidate's score for the requested subclass (from JSONB).
    """
    # Validate subclass exists
    sub_check = conn.execute(text(
        "SELECT 1 FROM asset_subclass_weights WHERE subclass = :n AND active = TRUE"
    ), {"n": name}).first()
    if not sub_check:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Subclass '{name}' not found or inactive")

    # Build bbox clause if provided
    bbox_clause = ""
    params: dict = {"name": name, "smin": score_min, "lim": limit}
    if bbox:
        try:
            min_lng, min_lat, max_lng, max_lat = [float(x) for x in bbox.split(",")]
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "bbox must be: minLng,minLat,maxLng,maxLat")
        bbox_clause = """
            AND ST_Y(c.geom) BETWEEN :min_lat AND :max_lat
            AND ST_X(c.geom) BETWEEN :min_lng AND :max_lng
        """
        params.update({"min_lat": min_lat, "max_lat": max_lat, "min_lng": min_lng, "max_lng": max_lng})

    sql = f"""
        SELECT
          c.id                          AS candidate_id,
          ST_Y(c.geom)                  AS lat,
          ST_X(c.geom)                  AS lng,
          (s.subclass_scores ->> :name)::numeric AS score
        FROM transactions_clean c
        JOIN model_scores s
          ON c.id = s.clean_id
         AND s.scoring_profile = 'default'
         AND s.subclass_scores IS NOT NULL
         AND s.subclass_scores ? :name
        WHERE c.geom IS NOT NULL
          AND (s.subclass_scores ->> :name)::numeric >= :smin
          {bbox_clause}
        ORDER BY (s.subclass_scores ->> :name)::numeric DESC
        LIMIT :lim
    """

    rows = conn.execute(text(sql), params).mappings().all()
    return [
        HeatmapPoint(
            lat=float(r["lat"]),
            lng=float(r["lng"]),
            score=float(r["score"]),
            candidate_id=int(r["candidate_id"]),
        )
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# POST /subclasses/{name}/weights — admin only
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{name}/weights", response_model=SubclassWeights)
def update_subclass_weights(
    name: str,
    weights: WeightsUpdate,
    conn=Depends(_get_conn),
    # TODO: add JWT auth dependency: user=Depends(require_admin)
) -> SubclassWeights:
    """
    Update weights for a subclass.
    Requires admin role (TODO: implement JWT auth).
    Database trigger validates sum = 1.0.
    """
    # Validate sum=1 client-side first (faster fail)
    total = (
        weights.w_underval + weights.w_cap_rate + weights.w_appreciation +
        weights.w_transit + weights.w_school + weights.w_traffic +
        weights.w_competitor_density + weights.w_demographic_match +
        weights.w_liquidity + weights.w_regulatory_risk +
        weights.w_environmental_risk + weights.w_data_confidence
    )
    if abs(total - 1.0) > 0.001:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Weights must sum to 1.0 (got {total:.4f}). Re-balance and try again.",
        )

    # Update (DB trigger will re-validate)
    try:
        result = conn.execute(text("""
            UPDATE asset_subclass_weights
            SET
              w_underval           = :w_underval,
              w_cap_rate           = :w_cap_rate,
              w_appreciation       = :w_appreciation,
              w_transit            = :w_transit,
              w_school             = :w_school,
              w_traffic            = :w_traffic,
              w_competitor_density = :w_competitor_density,
              w_demographic_match  = :w_demographic_match,
              w_liquidity          = :w_liquidity,
              w_regulatory_risk    = :w_regulatory_risk,
              w_environmental_risk = :w_environmental_risk,
              w_data_confidence    = :w_data_confidence
            WHERE subclass = :name
            RETURNING *
        """), {**weights.model_dump(), "name": name})
        conn.commit()
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Update failed: {e}")

    row = result.mappings().first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Subclass '{name}' not found")

    weight_keys = [k for k in row.keys() if k.startswith("w_")]
    weights_dict = {k.replace("w_", ""): float(row[k]) for k in weight_keys}

    return SubclassWeights(
        subclass=row["subclass"],
        description=row["description"],
        parent_class=row["parent_class"],
        weights=weights_dict,
        sum=round(sum(weights_dict.values()), 4),
    )
