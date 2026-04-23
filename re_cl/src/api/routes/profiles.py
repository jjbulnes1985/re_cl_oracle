"""
profiles.py
-----------
FastAPI routes for scoring profiles.

Endpoints:
  GET  /profiles              — List all built-in profiles
  GET  /profiles/{name}       — Get profile detail
  POST /profiles/score        — Score a batch with a custom profile (in-memory, no DB write)
"""

from typing import Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.engine import Engine

from src.api.db import get_engine, MODEL_VERSION
from src.scoring.scoring_profile import (
    ScoringProfile, compute_profile_score, list_profiles,
)

router = APIRouter(prefix="/profiles", tags=["profiles"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProfileInfo(BaseModel):
    name:        str
    description: str
    weights:     Dict[str, float]
    is_default:  bool


class CustomWeights(BaseModel):
    undervaluation: float = Field(0.70, ge=0.0, le=1.0, description="Peso subvaloración")
    confidence:     float = Field(0.30, ge=0.0, le=1.0, description="Peso confianza de datos")
    location:       float = Field(0.0,  ge=0.0, le=1.0, description="Peso ubicación")
    growth:         float = Field(0.0,  ge=0.0, le=1.0, description="Peso crecimiento demográfico")
    volume:         float = Field(0.0,  ge=0.0, le=1.0, description="Peso volumen de transacciones")

    @model_validator(mode="after")
    def weights_must_be_positive(self):
        total = self.undervaluation + self.confidence + self.location + self.growth + self.volume
        if total == 0:
            raise ValueError("Al menos un peso debe ser mayor que 0")
        return self


class ScoreRequest(BaseModel):
    profile:    Optional[str]         = Field(None, description="Nombre de perfil predefinido")
    weights:    Optional[CustomWeights] = Field(None, description="Pesos personalizados (se normaliza automáticamente)")
    county_name: Optional[str]        = Field(None, description="Filtrar por comuna")
    project_type: Optional[str]       = Field(None, description="Filtrar por tipología")
    limit:      int                   = Field(100, ge=1, le=5000)

    @model_validator(mode="after")
    def profile_or_weights(self):
        if self.profile is None and self.weights is None:
            raise ValueError("Se debe especificar 'profile' o 'weights'")
        return self


class ScoredProperty(BaseModel):
    score_id:            int
    county_name:         Optional[str]
    project_type:        Optional[str]
    opportunity_score:   Optional[float]
    undervaluation_score: Optional[float]
    gap_pct:             Optional[float]
    uf_m2_building:      Optional[float]
    scoring_profile:     Optional[str]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[ProfileInfo])
def get_profiles():
    """Return all available scoring profiles."""
    return [ProfileInfo(**p) for p in list_profiles()]


@router.get("/{name}", response_model=ProfileInfo)
def get_profile(name: str):
    """Get a specific scoring profile by name."""
    try:
        profile = ScoringProfile.from_name(name)
        return ProfileInfo(
            name=profile.name,
            description=profile.description,
            weights=profile.weights,
            is_default=(name == "default"),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/score", response_model=List[ScoredProperty])
def score_with_profile(
    request: ScoreRequest = Body(...),
    engine:  Engine       = Depends(get_engine),
):
    """
    Re-score properties using a custom profile (in-memory, no DB write).

    Supply either:
      - profile: "default" | "location" | "growth" | "liquidity"
      - weights: custom per-dimension weights (auto-normalized)

    Returns top properties re-ranked by the requested profile.
    """
    # Build profile
    if request.profile:
        try:
            profile = ScoringProfile.from_name(request.profile)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        w = request.weights
        profile = ScoringProfile.custom(
            undervaluation = w.undervaluation,
            confidence     = w.confidence,
            location       = w.location,
            growth         = w.growth,
            volume         = w.volume,
        )

    # Load base data for scoring
    from sqlalchemy import text
    # Build filters with bound params to avoid SQL injection
    filter_clauses = ["vo.model_version = :model_version", "vo.opportunity_score IS NOT NULL"]
    params: dict = {"model_version": MODEL_VERSION}
    if request.county_name:
        filter_clauses.append("vo.county_name = :county_name")
        params["county_name"] = request.county_name
    if request.project_type:
        filter_clauses.append("vo.project_type = :project_type")
        params["project_type"] = request.project_type

    # dist_km_centroid and cluster_id live in transaction_features, not v_opportunities
    query = text(f"""
        SELECT vo.score_id, vo.county_name, vo.project_type,
               vo.undervaluation_score, vo.data_confidence, vo.gap_pct,
               vo.uf_m2_building,
               tf.dist_km_centroid, tf.cluster_id
        FROM v_opportunities vo
        LEFT JOIN model_scores ms ON ms.id = vo.score_id
        LEFT JOIN transaction_features tf ON tf.clean_id = ms.clean_id
        WHERE {' AND '.join(filter_clauses)}
        ORDER BY vo.opportunity_score DESC
        LIMIT 5000
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail="No scored data found. Run opportunity_score.py first.")

    df = pd.DataFrame([dict(r) for r in rows])
    df = df.rename(columns={"score_id": "id"})  # scoring_profile expects 'id'

    # Compute with custom profile
    scored = compute_profile_score(df, profile)
    scored = scored.rename(columns={"id": "score_id"})
    scored = scored.sort_values("opportunity_score", ascending=False).head(request.limit)

    return [
        ScoredProperty(
            score_id            = int(row["score_id"]),
            county_name         = row.get("county_name"),
            project_type        = row.get("project_type"),
            opportunity_score   = row.get("opportunity_score"),
            undervaluation_score = row.get("undervaluation_score"),
            gap_pct             = row.get("gap_pct"),
            uf_m2_building      = row.get("uf_m2_building"),
            scoring_profile     = row.get("scoring_profile"),
        )
        for _, row in scored.iterrows()
    ]
