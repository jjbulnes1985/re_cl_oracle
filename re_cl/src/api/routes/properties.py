"""
properties.py
-------------
FastAPI routes for property listing and detail.

Endpoints:
  GET /properties                        — List scored properties with filters + pagination
  GET /properties/export                 — Export top scored properties as CSV download
  GET /properties/{id}                   — Single property detail
  GET /properties/communes               — List communes with stats
  GET /properties/{id}/comparables       — Find N comparable properties
"""

import csv
import io
import json
import math
import pickle
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.api.db import get_engine

router = APIRouter(prefix="/properties", tags=["properties"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class PropertySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    score_id:           int
    project_type:       Optional[str]
    county_name:        Optional[str]
    year:               Optional[int]
    real_value_uf:      Optional[float]
    surface_m2:         Optional[float]
    uf_m2_building:     Optional[float]
    opportunity_score:  Optional[float]
    undervaluation_score: Optional[float]
    gap_pct:            Optional[float]
    data_confidence:    Optional[float]
    latitude:           Optional[float]
    longitude:          Optional[float]
    # V4 thesis features
    age:                        Optional[int]   = None
    construction_year_bucket:   Optional[str]   = None
    city_zone:                  Optional[str]   = None
    log_surface:                Optional[float] = None
    # V4 OSM features
    dist_metro_km:      Optional[float] = None
    dist_school_km:     Optional[float] = None
    dist_park_km:       Optional[float] = None
    amenities_500m:     Optional[int]   = None
    amenities_1km:      Optional[int]   = None


class ShapFeature(BaseModel):
    feature:   str
    shap:      float
    direction: str


class PropertyDetail(PropertySummary):
    predicted_uf_m2:    Optional[float]
    gap_percentile:     Optional[float]
    shap_top_features:  Optional[List[ShapFeature]] = None  # parsed from JSON string
    # V4 additional OSM fields
    dist_bus_stop_km:   Optional[float] = None
    dist_hospital_km:   Optional[float] = None
    dist_mall_km:       Optional[float] = None
    age_sq:             Optional[float] = None


class CommuneStat(BaseModel):
    county_name:        str
    n_transactions:     int
    median_score:       Optional[float]
    pct_subvaloradas:   Optional[float]
    median_uf_m2:       Optional[float]
    median_gap_pct:     Optional[float]
    crime_index:        Optional[float]  = None
    crime_tier:         Optional[str]    = None
    educacion_score:    Optional[float]  = None
    hacinamiento_score: Optional[float]  = None
    densidad_norm:      Optional[float]  = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[PropertySummary])
def list_properties(
    project_type:  Optional[str]  = Query(None, description="Filter by typology"),
    county_name:   Optional[str]  = Query(None, description="Filter by commune"),
    city_zone:     Optional[str]  = Query(None, description="Filter by city zone: centro_norte, este, oeste, sur"),
    min_score:     float          = Query(0.0,  ge=0.0, le=1.0),
    max_score:     float          = Query(1.0,  ge=0.0, le=1.0),
    year:          Optional[int]  = Query(None),
    limit:         int            = Query(100,  ge=1, le=10000),
    offset:        int            = Query(0,    ge=0),
    response:      Response       = None,
    engine:        Engine         = Depends(get_engine),
):
    """List opportunity-scored properties with optional filters."""
    filters = [
        "vo.opportunity_score BETWEEN :min_score AND :max_score",
        "vo.latitude IS NOT NULL",
    ]
    params: dict = {"min_score": min_score, "max_score": max_score,
                    "limit": limit, "offset": offset}

    if project_type:
        filters.append("vo.project_type = :project_type")
        params["project_type"] = project_type
    if county_name:
        filters.append("vo.county_name = :county_name")
        params["county_name"] = county_name
    if year:
        filters.append("vo.year = :year")
        params["year"] = year
    if city_zone:
        filters.append("tf.city_zone = :city_zone")
        params["city_zone"] = city_zone

    where = " AND ".join(filters)
    count_query = text(f"""
        SELECT COUNT(*)
        FROM v_opportunities vo
        LEFT JOIN model_scores ms ON ms.id = vo.score_id
        LEFT JOIN transaction_features tf ON tf.clean_id = ms.clean_id
        WHERE {where}
    """)
    query = text(f"""
        SELECT vo.score_id, vo.project_type, vo.county_name, vo.year,
               vo.real_value_uf, vo.surface_m2, vo.uf_m2_building,
               vo.opportunity_score, vo.undervaluation_score,
               vo.gap_pct, vo.data_confidence, vo.latitude, vo.longitude,
               tf.age, tf.construction_year_bucket, tf.city_zone, tf.log_surface,
               tf.dist_metro_km, tf.dist_school_km, tf.dist_park_km,
               tf.amenities_500m, tf.amenities_1km
        FROM v_opportunities vo
        LEFT JOIN model_scores ms ON ms.id = vo.score_id
        LEFT JOIN transaction_features tf ON tf.clean_id = ms.clean_id
        WHERE {where}
        ORDER BY vo.opportunity_score DESC
        LIMIT :limit OFFSET :offset
    """)

    # count_params excludes limit/offset (not referenced in COUNT query)
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    with engine.connect() as conn:
        total = conn.execute(count_query, count_params).scalar() or 0
        rows = conn.execute(query, params).mappings().all()

    if response is not None:
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Page"] = str(offset // limit)
        response.headers["X-Page-Size"] = str(limit)

    return [PropertySummary(**dict(r)) for r in rows]


@router.get("/export")
def export_properties(
    project_type:  Optional[str]  = Query(None, description="Filter by typology"),
    county_name:   Optional[str]  = Query(None, description="Filter by commune"),
    city_zone:     Optional[str]  = Query(None, description="Filter by city zone"),
    min_score:     float          = Query(0.0,  ge=0.0, le=1.0),
    max_score:     float          = Query(1.0,  ge=0.0, le=1.0),
    limit:         int            = Query(1000, ge=1, le=5000),
    engine:        Engine         = Depends(get_engine),
):
    """Export top scored properties as a CSV file (max 5000 rows)."""
    filters = [
        "vo.opportunity_score BETWEEN :min_score AND :max_score",
        "vo.latitude IS NOT NULL",
    ]
    params: dict = {"min_score": min_score, "max_score": max_score, "limit": limit}

    if project_type:
        filters.append("vo.project_type = :project_type")
        params["project_type"] = project_type
    if county_name:
        filters.append("vo.county_name = :county_name")
        params["county_name"] = county_name
    if city_zone:
        filters.append("tf.city_zone = :city_zone")
        params["city_zone"] = city_zone

    where = " AND ".join(filters)
    query = text(f"""
        SELECT vo.score_id, vo.county_name, vo.project_type,
               tf.city_zone,
               vo.opportunity_score, vo.undervaluation_score,
               vo.gap_pct, vo.uf_m2_building, vo.real_value_uf,
               vo.surface_m2,
               tf.age,
               tf.dist_metro_km, tf.amenities_500m,
               vo.latitude, vo.longitude
        FROM v_opportunities vo
        LEFT JOIN model_scores ms ON ms.id = vo.score_id
        LEFT JOIN transaction_features tf ON tf.clean_id = ms.clean_id
        WHERE {where}
        ORDER BY vo.opportunity_score DESC
        LIMIT :limit
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().all()

    columns = [
        "score_id", "county_name", "project_type", "city_zone",
        "opportunity_score", "undervaluation_score", "gap_pct",
        "uf_m2_building", "real_value_uf", "surface_m2", "age",
        "dist_metro_km", "amenities_500m", "latitude", "longitude",
    ]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row.get(col) for col in columns])

    filename = f"re_cl_oportunidades_{date.today().isoformat()}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/communes", response_model=List[CommuneStat])
def list_communes(
    engine: Engine = Depends(get_engine),
):
    """Return commune-level opportunity statistics including enrichment data."""
    query = text("""
        SELECT county_name, n_transactions, median_score,
               pct_subvaloradas, median_uf_m2, median_gap_pct,
               crime_index, crime_tier, educacion_score,
               hacinamiento_score, densidad_norm
        FROM commune_stats
        ORDER BY median_score DESC NULLS LAST
    """)
    with engine.connect() as conn:
        rows = conn.execute(query).mappings().all()
    return [CommuneStat(**dict(r)) for r in rows]


@router.get("/communes/enriched")
def communes_enriched(engine: Engine = Depends(get_engine)):
    """Return commune stats with enrichment data for choropleth visualization."""
    query = text("""
        SELECT county_name, n_transactions, median_score,
               pct_subvaloradas, median_uf_m2, median_gap_pct,
               crime_index, crime_tier, educacion_score,
               hacinamiento_score, densidad_norm
        FROM commune_stats
        ORDER BY median_score DESC NULLS LAST
    """)
    with engine.connect() as conn:
        rows = conn.execute(query).mappings().all()
    return [dict(r) for r in rows]


# ── Haversine helper ─────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


@router.get("/search", response_model=List[PropertySummary])
def search_properties(
    q:         str           = Query(..., description="Free-text search on county_name and project_type"),
    min_score: float         = Query(0.0, ge=0.0, le=1.0),
    limit:     int           = Query(20,  ge=1, le=500),
    offset:    int           = Query(0,   ge=0),
    engine:    Engine        = Depends(get_engine),
):
    """Full-text search on county_name and project_type using ILIKE."""
    q = q.strip()[:100]
    if not q:
        raise HTTPException(status_code=400, detail="Search query 'q' must not be empty")

    params: dict = {
        "q":         f"%{q}%",
        "min_score": min_score,
        "limit":     limit,
        "offset":    offset,
    }
    query = text("""
        SELECT vo.score_id, vo.project_type, vo.county_name, vo.year,
               vo.real_value_uf, vo.surface_m2, vo.uf_m2_building,
               vo.opportunity_score, vo.undervaluation_score,
               vo.gap_pct, vo.data_confidence, vo.latitude, vo.longitude,
               tf.age, tf.construction_year_bucket, tf.city_zone, tf.log_surface,
               tf.dist_metro_km, tf.dist_school_km, tf.dist_park_km,
               tf.amenities_500m, tf.amenities_1km
        FROM v_opportunities vo
        LEFT JOIN model_scores ms ON ms.id = vo.score_id
        LEFT JOIN transaction_features tf ON tf.clean_id = ms.clean_id
        WHERE (vo.county_name ILIKE :q OR vo.project_type ILIKE :q)
          AND vo.opportunity_score >= :min_score
          AND vo.latitude IS NOT NULL
        ORDER BY vo.opportunity_score DESC
        LIMIT :limit OFFSET :offset
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().all()

    return [PropertySummary(**dict(r)) for r in rows]


@router.get("/{score_id}/comparables", response_model=List[PropertySummary])
def get_comparables(
    score_id: int,
    n: int = Query(5, ge=1, le=20),
    radius_km: float = Query(2.0, ge=0.1, le=10.0),
    engine: Engine = Depends(get_engine),
):
    """
    Find N comparable properties to a given property.

    Comparable = same project_type + within radius_km + similar surface (±50%) + similar year (±2).
    Ranked by Haversine distance (closest first). Excludes the property itself.
    """
    # 1. Fetch the source property
    src_query = text("""
        SELECT score_id, project_type, county_name, year, surface_m2,
               latitude, longitude, opportunity_score
        FROM v_opportunities
        WHERE score_id = :sid
        LIMIT 1
    """)
    with engine.connect() as conn:
        src = conn.execute(src_query, {"sid": score_id}).mappings().first()

    if src is None:
        raise HTTPException(status_code=404, detail=f"Property {score_id} not found")

    if src["latitude"] is None or src["longitude"] is None:
        raise HTTPException(status_code=422, detail="Source property has no coordinates")

    lat: float = src["latitude"]
    lon: float = src["longitude"]
    lat_rad = math.radians(lat)

    # Bounding box in degrees
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * math.cos(lat_rad)) if math.cos(lat_rad) != 0 else radius_km / 111.0

    surface_m2: float = src["surface_m2"] or 0.0
    year: int = src["year"] or 0

    params: dict = {
        "sid": score_id,
        "project_type": src["project_type"],
        "lat_min": lat - lat_delta,
        "lat_max": lat + lat_delta,
        "lon_min": lon - lon_delta,
        "lon_max": lon + lon_delta,
        "surf_min": surface_m2 * 0.5,
        "surf_max": surface_m2 * 1.5,
        "year_min": year - 2,
        "year_max": year + 2,
        "limit": n * 3,
    }

    # 2. Query candidates within bounding box
    cand_query = text("""
        SELECT score_id, project_type, county_name, year,
               real_value_uf, surface_m2, uf_m2_building,
               opportunity_score, undervaluation_score,
               gap_pct, data_confidence, latitude, longitude
        FROM v_opportunities
        WHERE project_type = :project_type
          AND latitude BETWEEN :lat_min AND :lat_max
          AND longitude BETWEEN :lon_min AND :lon_max
          AND score_id != :sid
          AND surface_m2 BETWEEN :surf_min AND :surf_max
          AND year BETWEEN :year_min AND :year_max
          AND latitude IS NOT NULL
        ORDER BY ABS(surface_m2 - :surf_mid) ASC
        LIMIT :limit
    """)
    params["surf_mid"] = surface_m2

    with engine.connect() as conn:
        candidates = conn.execute(cand_query, params).mappings().all()

    # 3. Compute Haversine distance, sort, return top n
    scored = []
    for row in candidates:
        dist = _haversine_km(lat, lon, row["latitude"], row["longitude"])
        scored.append((dist, dict(row)))

    scored.sort(key=lambda x: x[0])
    top = [PropertySummary(**item) for _, item in scored[:n]]
    return top


@router.get("/osm/bus-stops")
def get_bus_stops():
    """Return GTFS bus stop coordinates from local cache (gtfs_stops.pkl).
    Returns list of {stop_id, stop_name, lat, lon}. Empty list if cache not found."""
    cache_path = Path(__file__).resolve().parents[4] / "data/processed/gtfs_stops.pkl"
    if not cache_path.exists():
        return []
    try:
        df = pickle.load(open(cache_path, "rb"))
        # Subsample to keep response size reasonable (max 2000 stops)
        if len(df) > 2000:
            df = df.sample(2000, random_state=42)
        return df[["stop_id", "stop_name", "lat", "lon"]].rename(
            columns={"stop_name": "name"}
        ).to_dict(orient="records")
    except Exception:
        return []


@router.get("/{score_id}", response_model=PropertyDetail)
def get_property(
    score_id: int,
    engine:   Engine = Depends(get_engine),
):
    """Get full detail of a single scored property."""
    query = text("""
        SELECT vo.score_id, vo.project_type, vo.county_name, vo.year,
               vo.real_value_uf, vo.surface_m2, vo.uf_m2_building,
               vo.opportunity_score, vo.undervaluation_score,
               vo.gap_pct, vo.gap_percentile, vo.predicted_uf_m2,
               vo.data_confidence, vo.shap_top_features,
               vo.latitude, vo.longitude,
               tf.age, tf.age_sq, tf.construction_year_bucket, tf.city_zone, tf.log_surface,
               tf.dist_metro_km, tf.dist_bus_stop_km, tf.dist_school_km,
               tf.dist_hospital_km, tf.dist_park_km, tf.dist_mall_km,
               tf.amenities_500m, tf.amenities_1km
        FROM v_opportunities vo
        LEFT JOIN model_scores ms ON ms.id = vo.score_id
        LEFT JOIN transaction_features tf ON tf.clean_id = ms.clean_id
        WHERE vo.score_id = :sid
        LIMIT 1
    """)
    with engine.connect() as conn:
        row = conn.execute(query, {"sid": score_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Property {score_id} not found")
    d = dict(row)
    # shap_top_features is stored as JSONB; psycopg2 returns it as a parsed list.
    # PropertyDetail.shap_top_features expects Optional[str] — serialize back to JSON.
    if d.get("shap_top_features") is not None and not isinstance(d["shap_top_features"], str):
        d["shap_top_features"] = json.dumps(d["shap_top_features"])
    return PropertyDetail(**d)
