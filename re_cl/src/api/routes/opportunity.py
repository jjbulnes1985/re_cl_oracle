"""
opportunity.py
--------------
FastAPI routes for the Opportunity Engine v2.

Endpoints:
  GET /opportunity/candidates            — List opportunities with filters
  GET /opportunity/candidates/{id}       — Full candidate detail (scores + valuations + risks)
  GET /opportunity/competitors           — Commercial competitors by use_case
  GET /opportunity/use-cases             — Catalog of property types / use cases
  GET /opportunity/profiles              — Catalog of investor profiles
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.db import get_engine

router = APIRouter()


def _get_conn():
    engine = get_engine()
    with engine.connect() as conn:
        yield conn


@router.get("/candidates")
def list_candidates(
    use_case: str = Query("as_is", description="as_is | gas_station | pharmacy | supermarket | ..."),
    profile:  str = Query("value",  description="value | growth | income | redevelopment | operator"),
    commune:  Optional[str] = Query(None, description="Filter by county_name"),
    property_type: Optional[str] = Query(None, description="apartment | house | land | retail | ..."),
    score_min: float = Query(0.5, ge=0.0, le=1.0),
    is_eriazo: Optional[bool] = Query(None, description="Filter subutilized sites only"),
    limit:  int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    conn=Depends(_get_conn),
):
    """List top opportunity candidates with filters."""
    filters = ["s.opportunity_score >= :score_min"]
    params: dict = {"use_case": use_case, "profile": profile, "score_min": score_min,
                    "limit": limit, "offset": offset}

    if commune:
        filters.append("c.county_name = :commune")
        params["commune"] = commune
    if property_type:
        filters.append("c.property_type_code = :property_type")
        params["property_type"] = property_type
    if is_eriazo is not None:
        filters.append(f"c.is_eriazo = {'TRUE' if is_eriazo else 'FALSE'}")

    where_clause = " AND ".join(filters)

    rows = conn.execute(text(f"""
        SELECT
            c.id, c.address, c.county_name, c.latitude, c.longitude,
            c.property_type_code, c.surface_land_m2, c.surface_building_m2,
            c.is_eriazo, c.construction_ratio,
            c.last_transaction_uf, c.last_transaction_date, c.listed_price_uf,
            c.rol_sii,
            s.use_case, s.investor_profile, s.opportunity_score,
            s.undervaluation_score, s.location_score, s.use_specific_score,
            s.max_payable_uf, s.drivers,
            v.estimated_uf, v.p25_uf, v.p50_uf, v.p75_uf,
            v.confidence AS valuation_confidence
        FROM opportunity.candidates c
        JOIN opportunity.scores s
            ON s.candidate_id = c.id
            AND s.use_case = :use_case
            AND s.investor_profile = :profile
        LEFT JOIN opportunity.valuations v
            ON v.candidate_id = c.id AND v.method = 'triangulated'
        WHERE {where_clause}
        ORDER BY s.opportunity_score DESC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    total = conn.execute(text(f"""
        SELECT COUNT(*)
        FROM opportunity.candidates c
        JOIN opportunity.scores s
            ON s.candidate_id = c.id
            AND s.use_case = :use_case
            AND s.investor_profile = :profile
        WHERE {where_clause}
    """), {k: v for k, v in params.items() if k not in ("limit", "offset")}).scalar()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [dict(r._mapping) for r in rows],
    }


@router.get("/candidates/{candidate_id}")
def get_candidate(candidate_id: int, use_case: str = "as_is", profile: str = "value",
                  conn=Depends(_get_conn)):
    """Full candidate detail: candidate info + all scores + valuations + risks."""
    cand = conn.execute(text("""
        SELECT c.*, s.opportunity_score, s.undervaluation_score, s.location_score,
               s.use_specific_score, s.max_payable_uf, s.drivers, s.risk_summary,
               v.estimated_uf, v.p25_uf, v.p50_uf, v.p75_uf, v.confidence AS val_confidence
        FROM opportunity.candidates c
        LEFT JOIN opportunity.scores s
            ON s.candidate_id = c.id AND s.use_case = :use_case AND s.investor_profile = :profile
        LEFT JOIN opportunity.valuations v ON v.candidate_id = c.id AND v.method = 'triangulated'
        WHERE c.id = :id
    """), {"id": candidate_id, "use_case": use_case, "profile": profile}).fetchone()

    if not cand:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Candidate not found")

    # All scores for this candidate
    scores = conn.execute(text("""
        SELECT use_case, investor_profile, opportunity_score, max_payable_uf, scored_at
        FROM opportunity.scores WHERE candidate_id = :id ORDER BY opportunity_score DESC
    """), {"id": candidate_id}).fetchall()

    # All valuations
    valuations = conn.execute(text("""
        SELECT method, estimated_uf, p25_uf, p75_uf, confidence, inputs, notes
        FROM opportunity.valuations WHERE candidate_id = :id ORDER BY method
    """), {"id": candidate_id}).fetchall()

    # Risks
    risks = conn.execute(text("""
        SELECT category, severity, description FROM opportunity.risks
        WHERE candidate_id = :id ORDER BY severity
    """), {"id": candidate_id}).fetchall()

    # Due diligence checklist (static by use_case)
    dd_checklist = {
        "gas_station": [
            "Verificar uso permitido en plan regulador comunal (DOM)",
            "Revisar expropiaciones vigentes en BCN",
            "Solicitar certificado de informaciones previas",
            "Tasación independiente (Tinsa / GPS Property)",
            "Consultar SEC sobre distancias técnicas DS 160/2008",
        ],
        "as_is": [
            "Verificar estado de dominio en CBR",
            "Certificado de hipotecas y gravámenes",
            "Tasación independiente",
            "Revisar situación tributaria SII",
        ],
    }

    return {
        **dict(cand._mapping),
        "all_scores": [dict(r._mapping) for r in scores],
        "valuations": [dict(r._mapping) for r in valuations],
        "risks": [dict(r._mapping) for r in risks],
        "due_diligence": dd_checklist.get(use_case, dd_checklist["as_is"]),
        "cap_rate_disclaimer": (
            "INFO_NO_FIDEDIGNA::pendiente_validacion — max_payable_uf basado en proxy "
            "cap rate USA net lease + spread Chile. Banda ±150bps. Verificar con tasador local."
        ),
    }


@router.get("/competitors")
def list_competitors(
    use_case: str = Query(..., description="gas_station | pharmacy | bank_branch | supermarket"),
    commune: Optional[str] = Query(None),
    limit: int = Query(200, le=1000),
    conn=Depends(_get_conn),
):
    """List commercial competitors by use case."""
    filters = ["use_case = :use_case"]
    params: dict = {"use_case": use_case, "limit": limit}
    if commune:
        filters.append("county_name ILIKE :commune")
        params["commune"] = f"%{commune}%"

    rows = conn.execute(text(f"""
        SELECT id, use_case, operator, name, address, county_name,
               latitude, longitude, operational_status, source
        FROM opportunity.competitors
        WHERE {' AND '.join(filters)}
        ORDER BY operator, name
        LIMIT :limit
    """), params).fetchall()

    total = conn.execute(text(f"""
        SELECT COUNT(*) FROM opportunity.competitors
        WHERE {' AND '.join(filters)}
    """), {k: v for k, v in params.items() if k != "limit"}).scalar()

    return {"total": total, "items": [dict(r._mapping) for r in rows]}


@router.get("/use-cases")
def list_use_cases(conn=Depends(_get_conn)):
    """Catalog of available property types and use cases."""
    rows = conn.execute(text("""
        SELECT code, name, category, is_use_case,
               min_surface_land_m2, typical_capex_uf_per_m2,
               typical_cap_rate_low, typical_cap_rate_mid, typical_cap_rate_high, notes
        FROM opportunity.property_types
        ORDER BY category, code
    """)).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/profiles")
def list_profiles(conn=Depends(_get_conn)):
    """Catalog of investor profiles with scoring weights."""
    rows = conn.execute(text("""
        SELECT code, name, description, weights
        FROM opportunity.investor_profiles
        ORDER BY code
    """)).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/summary")
def get_summary(conn=Depends(_get_conn)):
    """Summary statistics for the Opportunity Engine."""
    stats = conn.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM opportunity.candidates) AS total_candidates,
            (SELECT COUNT(*) FROM opportunity.candidates WHERE is_eriazo) AS eriazo_candidates,
            (SELECT COUNT(*) FROM opportunity.scores WHERE use_case = 'as_is') AS scored_as_is,
            (SELECT COUNT(*) FROM opportunity.scores WHERE use_case = 'gas_station') AS scored_gas_station,
            (SELECT COUNT(*) FROM opportunity.scores WHERE opportunity_score >= 0.7) AS high_opportunity,
            (SELECT COUNT(*) FROM opportunity.competitors) AS total_competitors,
            (SELECT COUNT(*) FROM opportunity.valuations WHERE method = 'triangulated') AS valuated
    """)).fetchone()
    return dict(stats._mapping)
