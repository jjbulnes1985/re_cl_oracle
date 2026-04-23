"""
osm_features.py
---------------
Computes OSM/GTFS proximity features for each property in transactions_clean.

Features produced:
  - dist_metro_km       — km to nearest Metro Santiago station (hardcoded coords)
  - dist_bus_stop_km    — km to nearest RED bus stop (via Overpass API)
  - dist_school_km      — km to nearest school/colegio (Overpass)
  - dist_hospital_km    — km to nearest hospital/clinic (Overpass)
  - dist_park_km        — km to nearest park or plaza (Overpass)
  - dist_mall_km        — km to nearest mall or supermarket (Overpass)
  - amenities_500m      — count of amenities (school + hospital + park + shop) within 500m
  - amenities_1km       — count within 1km

Strategy:
  - Metro stations: hardcoded list (stable, no API needed)
  - All other POIs: Overpass API, bounding box = Santiago RM + 20km buffer
  - Cache: pickle files in data/processed/osm_cache/ with 7-day TTL
  - Distance: BallTree + haversine (same approach as spatial_features.py)
  - Graceful fallback: if Overpass is unreachable, returns NaN features with a warning.

Usage:
    python src/features/osm_features.py              # write to DB
    python src/features/osm_features.py --dry-run    # stats only, no DB write
"""

import argparse
import hashlib
import os
import pickle
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from loguru import logger
from sklearn.neighbors import BallTree
from sqlalchemy import create_engine, text

load_dotenv()

# ── Constants ──────────────────────────────────────────────────────────────────
EARTH_RADIUS_KM = 6371.0

# Santiago RM bounding box with ~20km buffer (south, west, north, east)
SANTIAGO_BBOX = (-33.85, -71.05, -33.25, -70.40)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_S = 60
OVERPASS_RETRIES = 3
OVERPASS_BACKOFF_BASE = 2  # seconds

CACHE_TTL_DAYS = 7

# Amenity counts: radii in km
AMENITY_RADII_KM = [0.5, 1.0]


# ── Metro Santiago stations (hardcoded — stable network) ───────────────────────
METRO_STATIONS = [
    # Línea 1 (San Pablo ↔ Los Dominicos)
    {"name": "San Pablo",                  "lat": -33.4503, "lon": -70.7185},
    {"name": "Neptuno",                    "lat": -33.4497, "lon": -70.7085},
    {"name": "Las Rejas",                  "lat": -33.4497, "lon": -70.6980},
    {"name": "Ecuador",                    "lat": -33.4497, "lon": -70.6880},
    {"name": "San Alberto Hurtado",        "lat": -33.4503, "lon": -70.6780},
    {"name": "Universidad de Santiago",    "lat": -33.4508, "lon": -70.6680},
    {"name": "Estación Central",           "lat": -33.4508, "lon": -70.6580},
    {"name": "Alameda",                    "lat": -33.4508, "lon": -70.6507},
    {"name": "Universidad de Chile",       "lat": -33.4412, "lon": -70.6497},
    {"name": "Baquedano",                  "lat": -33.4380, "lon": -70.6390},
    {"name": "Salvador",                   "lat": -33.4380, "lon": -70.6290},
    {"name": "Manuel Montt",               "lat": -33.4269, "lon": -70.6200},
    {"name": "Pedro de Valdivia",          "lat": -33.4269, "lon": -70.6100},
    {"name": "Los Leones",                 "lat": -33.4269, "lon": -70.6000},
    {"name": "Tobalaba",                   "lat": -33.4180, "lon": -70.5975},
    {"name": "El Golf",                    "lat": -33.4130, "lon": -70.5920},
    {"name": "Alcántara",                  "lat": -33.4080, "lon": -70.5868},
    {"name": "Escuela Militar",            "lat": -33.4030, "lon": -70.5815},
    {"name": "Manquehue",                  "lat": -33.3980, "lon": -70.5770},
    {"name": "Hernando de Magallanes",     "lat": -33.3935, "lon": -70.5720},
    {"name": "Los Dominicos",              "lat": -33.3890, "lon": -70.5670},
    # Línea 2 (Vespucio Norte ↔ La Cisterna)
    {"name": "Vespucio Norte",             "lat": -33.3760, "lon": -70.6430},
    {"name": "Zapadores",                  "lat": -33.3900, "lon": -70.6350},
    {"name": "Dorsal",                     "lat": -33.4020, "lon": -70.6280},
    {"name": "Cerro Blanco",               "lat": -33.4090, "lon": -70.6440},
    {"name": "Patronato",                  "lat": -33.4190, "lon": -70.6440},
    {"name": "Cal y Canto",                "lat": -33.4340, "lon": -70.6510},
    {"name": "Puente Cal y Canto",         "lat": -33.4380, "lon": -70.6530},
    {"name": "La Moneda",                  "lat": -33.4440, "lon": -70.6550},
    {"name": "Los Héroes",                 "lat": -33.4490, "lon": -70.6560},
    {"name": "Franklin",                   "lat": -33.4580, "lon": -70.6570},
    {"name": "El Llano",                   "lat": -33.4650, "lon": -70.6590},
    {"name": "San Miguel",                 "lat": -33.4760, "lon": -70.6590},
    {"name": "Lo Vial",                    "lat": -33.4830, "lon": -70.6610},
    {"name": "Departamental",              "lat": -33.4900, "lon": -70.6620},
    {"name": "Ciudad del Niño",            "lat": -33.4970, "lon": -70.6620},
    {"name": "Lo Ovalle",                  "lat": -33.5060, "lon": -70.6620},
    {"name": "El Parrón",                  "lat": -33.5130, "lon": -70.6630},
    {"name": "La Cisterna",                "lat": -33.5180, "lon": -70.6650},
    # Línea 3 (Baquedano ↔ Fernando Castillo Velasco)
    {"name": "Parque Bustamante",          "lat": -33.4360, "lon": -70.6310},
    {"name": "Santa Isabel",               "lat": -33.4470, "lon": -70.6310},
    {"name": "Irarrázaval",                "lat": -33.4560, "lon": -70.6310},
    {"name": "Monseñor Eyzaguirre",        "lat": -33.4650, "lon": -70.6280},
    {"name": "Ñuñoa",                      "lat": -33.4570, "lon": -70.5990},
    {"name": "Chile España",               "lat": -33.4510, "lon": -70.5860},
    {"name": "Villa Frei",                 "lat": -33.4430, "lon": -70.5760},
    {"name": "Quilín",                     "lat": -33.4890, "lon": -70.5890},
    {"name": "Los Orientales",             "lat": -33.4980, "lon": -70.5890},
    {"name": "Simón Bolívar",              "lat": -33.4750, "lon": -70.6230},
    {"name": "Plaza Egaña",                "lat": -33.4580, "lon": -70.5700},
    {"name": "Fernando Castillo Velasco",  "lat": -33.4490, "lon": -70.5570},
    # Línea 4 (Tobalaba ↔ Puente Alto)
    {"name": "Cristóbal Colón",            "lat": -33.4250, "lon": -70.5880},
    {"name": "Francisco Bilbao",           "lat": -33.4340, "lon": -70.5790},
    {"name": "Los Domínicos",              "lat": -33.4490, "lon": -70.5650},
    {"name": "Príncipe de Gales",          "lat": -33.4600, "lon": -70.5680},
    {"name": "Las Torres",                 "lat": -33.4690, "lon": -70.5680},
    {"name": "Grecia",                     "lat": -33.4780, "lon": -70.5700},
    {"name": "Los Presidentes",            "lat": -33.4870, "lon": -70.5700},
    {"name": "Estadio La Florida",         "lat": -33.4950, "lon": -70.5720},
    {"name": "San José de La Estrella",    "lat": -33.5050, "lon": -70.5740},
    {"name": "Los Quillayes",              "lat": -33.5150, "lon": -70.5780},
    {"name": "Elisa Correa",               "lat": -33.5240, "lon": -70.5810},
    {"name": "Hospital Sótero del Río",    "lat": -33.5320, "lon": -70.5870},
    {"name": "Protectora de la Infancia",  "lat": -33.5400, "lon": -70.5920},
    {"name": "Las Mercedes",               "lat": -33.5480, "lon": -70.5960},
    {"name": "Trinidad",                   "lat": -33.5560, "lon": -70.5990},
    {"name": "Rojas Magallanes",           "lat": -33.5640, "lon": -70.6010},
    {"name": "Puente Alto",                "lat": -33.5710, "lon": -70.6030},
    # Línea 4A (Vicente Valdés ↔ Vicuña Mackenna)
    {"name": "Vicente Valdés",             "lat": -33.5080, "lon": -70.5770},
    {"name": "Vicuña Mackenna",            "lat": -33.4930, "lon": -70.5810},
    # Línea 5 (Plaza Maipú ↔ Vicente Valdés)
    {"name": "Plaza Maipú",                "lat": -33.5120, "lon": -70.7560},
    {"name": "Santiago Bueras",            "lat": -33.5100, "lon": -70.7430},
    {"name": "Del Sol",                    "lat": -33.5090, "lon": -70.7310},
    {"name": "Monte Tabor",                "lat": -33.5080, "lon": -70.7190},
    {"name": "Pudahuel",                   "lat": -33.4560, "lon": -70.7490},
    {"name": "Barrancas",                  "lat": -33.4600, "lon": -70.7310},
    {"name": "Laguna Sur",                 "lat": -33.4640, "lon": -70.7190},
    {"name": "Pudahuel II",                "lat": -33.4650, "lon": -70.7060},
    {"name": "Ciudad Empresarial",         "lat": -33.3770, "lon": -70.6290},
    {"name": "Bicentenario",               "lat": -33.3860, "lon": -70.6190},
    {"name": "El Aguilucho",               "lat": -33.3950, "lon": -70.6080},
    {"name": "Los Libertadores",           "lat": -33.4040, "lon": -70.5980},
    {"name": "Quinta Normal",              "lat": -33.4380, "lon": -70.6920},
    {"name": "Pudahuel (L5)",              "lat": -33.4420, "lon": -70.7050},
    {"name": "San Pablo (L5)",             "lat": -33.4460, "lon": -70.7220},
    {"name": "Baquedano (L5)",             "lat": -33.4380, "lon": -70.6390},
    # Línea 6 (Cerrillos ↔ Ñuble)
    {"name": "Cerrillos",                  "lat": -33.4950, "lon": -70.7110},
    {"name": "Lo Valledor",                "lat": -33.4870, "lon": -70.7010},
    {"name": "Pedro Aguirre Cerda",        "lat": -33.4800, "lon": -70.6920},
    {"name": "Franklin (L6)",              "lat": -33.4730, "lon": -70.6820},
    {"name": "Bio Bio",                    "lat": -33.4670, "lon": -70.6720},
    {"name": "Ñuble",                      "lat": -33.4590, "lon": -70.6620},
    {"name": "Estadio Nacional",           "lat": -33.4550, "lon": -70.6120},
    {"name": "Inés de Suárez",             "lat": -33.4490, "lon": -70.6030},
    {"name": "Los Leones (L6)",            "lat": -33.4380, "lon": -70.5980},
    {"name": "Escuela Militar (L6)",       "lat": -33.4080, "lon": -70.5880},
]


# ── Cache utilities ─────────────────────────────────────────────────────────────

def _cache_dir() -> Path:
    """Returns cache directory path, creating it if necessary."""
    base = Path(__file__).resolve().parents[3] / "data" / "processed" / "osm_cache"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cache_key(query: str) -> str:
    return hashlib.md5(query.encode()).hexdigest()


def _cache_load(key: str) -> Optional[List[Dict]]:
    path = _cache_dir() / f"{key}.pkl"
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    if datetime.now() - mtime > timedelta(days=CACHE_TTL_DAYS):
        logger.debug(f"Cache expired for {key}")
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def _cache_save(key: str, data: List[Dict]) -> None:
    path = _cache_dir() / f"{key}.pkl"
    with open(path, "wb") as f:
        pickle.dump(data, f)


# ── Overpass API ────────────────────────────────────────────────────────────────

def _overpass_query(query: str) -> Optional[List[Dict]]:
    """
    Executes an Overpass query with retry + exponential backoff.
    Returns list of elements with lat/lon, or None on failure.
    """
    key = _cache_key(query)
    cached = _cache_load(key)
    if cached is not None:
        logger.debug(f"Cache hit for query key {key[:8]}")
        return cached

    for attempt in range(1, OVERPASS_RETRIES + 1):
        try:
            logger.debug(f"Overpass request attempt {attempt}/{OVERPASS_RETRIES}")
            resp = requests.post(
                OVERPASS_URL,
                data={"data": query},
                timeout=OVERPASS_TIMEOUT_S,
                headers={"User-Agent": "RE_CL/1.0 (real-estate research, Chile)"},
            )
            resp.raise_for_status()
            data = resp.json()
            elements = data.get("elements", [])
            # Normalise: ways have a 'center' key with lat/lon
            results = []
            for el in elements:
                if el.get("type") == "node":
                    results.append({"lat": el["lat"], "lon": el["lon"]})
                elif el.get("type") in ("way", "relation") and "center" in el:
                    results.append({"lat": el["center"]["lat"], "lon": el["center"]["lon"]})
            logger.debug(f"Overpass returned {len(results)} elements")
            _cache_save(key, results)
            return results
        except requests.exceptions.Timeout:
            logger.warning(f"Overpass timeout on attempt {attempt}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Overpass error on attempt {attempt}: {e}")

        if attempt < OVERPASS_RETRIES:
            wait = OVERPASS_BACKOFF_BASE ** attempt
            logger.info(f"Retrying Overpass in {wait}s...")
            time.sleep(wait)

    logger.error("Overpass API unavailable after all retries — features will be NaN")
    return None


def _build_overpass_query(bbox: Tuple, amenity_tags: List[Tuple[str, str]]) -> str:
    """
    Builds an Overpass QL query for multiple amenity tags within a bounding box.
    amenity_tags: list of (key, value) pairs e.g. [("amenity", "school"), ("amenity", "college")]
    """
    s, w, n, e = bbox
    union_parts = []
    for key, value in amenity_tags:
        union_parts.append(f'  node["{key}"="{value}"]({s},{w},{n},{e});')
        union_parts.append(f'  way["{key}"="{value}"]({s},{w},{n},{e});')
    union_str = "\n".join(union_parts)
    return f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];\n(\n{union_str}\n);\nout center;"


# ── BallTree distance helpers ───────────────────────────────────────────────────

def _build_tree(coords: List[Dict]) -> Optional[BallTree]:
    """Builds a BallTree from a list of dicts with 'lat'/'lon' keys."""
    if not coords:
        return None
    arr = np.radians([[c["lat"], c["lon"]] for c in coords])
    return BallTree(arr, metric="haversine")


def _nearest_km(tree: Optional[BallTree], query_rad: np.ndarray) -> np.ndarray:
    """Returns distance in km from each query point to its nearest tree point."""
    if tree is None:
        return np.full(len(query_rad), np.nan)
    dist_rad, _ = tree.query(query_rad, k=1)
    return dist_rad.flatten() * EARTH_RADIUS_KM


def _count_within_km(tree: Optional[BallTree], query_rad: np.ndarray, radius_km: float) -> np.ndarray:
    """Returns count of tree points within radius_km of each query point."""
    if tree is None:
        return np.zeros(len(query_rad), dtype=int)
    radius_rad = radius_km / EARTH_RADIUS_KM
    counts = tree.query_radius(query_rad, r=radius_rad, count_only=True)
    return counts.astype(int)


# ── Main feature computation ────────────────────────────────────────────────────

def fetch_all_poi_trees(bbox: Tuple) -> Dict[str, Optional[BallTree]]:
    """
    Fetches all POI categories from Overpass and returns a dict of BallTrees.
    Falls back to None trees if Overpass is unavailable.
    """
    logger.info("Fetching POI data from Overpass API (with cache)...")

    amenity_configs = {
        "bus_stop": [
            ("highway", "bus_stop"),
            ("amenity", "bus_station"),
        ],
        "school": [
            ("amenity", "school"),
            ("amenity", "college"),
            ("amenity", "university"),
        ],
        "hospital": [
            ("amenity", "hospital"),
            ("amenity", "clinic"),
            ("amenity", "doctors"),
        ],
        "park": [
            ("leisure", "park"),
            ("leisure", "garden"),
            ("leisure", "playground"),
        ],
        "mall": [
            ("shop", "mall"),
            ("shop", "supermarket"),
            ("shop", "department_store"),
        ],
    }

    trees = {}
    for category, tags in amenity_configs.items():
        query = _build_overpass_query(bbox, tags)
        elements = _overpass_query(query)
        if elements is not None:
            trees[category] = _build_tree(elements)
            logger.info(f"  {category}: {len(elements):,} POIs loaded")
        else:
            trees[category] = None
            logger.warning(f"  {category}: Overpass failed — will return NaN")

    return trees


def compute_osm_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Given a DataFrame with 'id', 'latitude', 'longitude', computes all OSM features.
    Returns DataFrame with 'id' + feature columns.
    """
    feature_cols = [
        "dist_metro_km",
        "dist_bus_stop_km",
        "dist_school_km",
        "dist_hospital_km",
        "dist_park_km",
        "dist_mall_km",
        "amenities_500m",
        "amenities_1km",
    ]

    result = df[["id"]].copy()
    for col in feature_cols:
        result[col] = np.nan if "dist_" in col else 0

    # Filter to rows with valid coordinates
    has_coords = df["latitude"].notna() & df["longitude"].notna()
    if "has_valid_coords" in df.columns:
        has_coords = has_coords & df["has_valid_coords"].astype(bool)

    valid = df[has_coords].copy()
    n_valid = len(valid)
    n_total = len(df)
    logger.info(f"  {n_valid:,} / {n_total:,} properties have valid coordinates")

    if valid.empty:
        logger.warning("No valid coordinates — all OSM features will be NaN/0")
        return result

    # Build radians array for all valid properties
    query_rad = np.radians(valid[["latitude", "longitude"]].values)

    # ── Metro (hardcoded) ──────────────────────────────────────────────────────
    metro_tree = _build_tree(METRO_STATIONS)
    dist_metro = _nearest_km(metro_tree, query_rad)
    result.loc[has_coords, "dist_metro_km"] = dist_metro
    logger.info(f"  dist_metro_km: median {np.nanmedian(dist_metro):.2f} km")

    # ── Overpass POIs ──────────────────────────────────────────────────────────
    poi_trees = fetch_all_poi_trees(SANTIAGO_BBOX)

    dist_bus = _nearest_km(poi_trees.get("bus_stop"), query_rad)
    result.loc[has_coords, "dist_bus_stop_km"] = dist_bus
    if not np.all(np.isnan(dist_bus)):
        logger.info(f"  dist_bus_stop_km: median {np.nanmedian(dist_bus):.3f} km")

    dist_school = _nearest_km(poi_trees.get("school"), query_rad)
    result.loc[has_coords, "dist_school_km"] = dist_school
    if not np.all(np.isnan(dist_school)):
        logger.info(f"  dist_school_km: median {np.nanmedian(dist_school):.3f} km")

    dist_hospital = _nearest_km(poi_trees.get("hospital"), query_rad)
    result.loc[has_coords, "dist_hospital_km"] = dist_hospital
    if not np.all(np.isnan(dist_hospital)):
        logger.info(f"  dist_hospital_km: median {np.nanmedian(dist_hospital):.3f} km")

    dist_park = _nearest_km(poi_trees.get("park"), query_rad)
    result.loc[has_coords, "dist_park_km"] = dist_park
    if not np.all(np.isnan(dist_park)):
        logger.info(f"  dist_park_km: median {np.nanmedian(dist_park):.3f} km")

    dist_mall = _nearest_km(poi_trees.get("mall"), query_rad)
    result.loc[has_coords, "dist_mall_km"] = dist_mall
    if not np.all(np.isnan(dist_mall)):
        logger.info(f"  dist_mall_km: median {np.nanmedian(dist_mall):.3f} km")

    # ── Amenity counts (school + hospital + park + mall within radius) ─────────
    # Aggregate all "neighbourhood quality" POI trees
    amenity_categories = ["school", "hospital", "park", "mall"]
    for radius_km, col in [(0.5, "amenities_500m"), (1.0, "amenities_1km")]:
        total_counts = np.zeros(n_valid, dtype=int)
        for cat in amenity_categories:
            tree = poi_trees.get(cat)
            total_counts += _count_within_km(tree, query_rad, radius_km)
        result.loc[has_coords, col] = total_counts
        logger.info(
            f"  {col}: mean {total_counts.mean():.1f}, "
            f"max {total_counts.max()}, p95 {np.percentile(total_counts, 95):.0f}"
        )

    return result


def _build_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db   = os.getenv("POSTGRES_DB",   "re_cl")
    user = os.getenv("POSTGRES_USER", "re_cl_user")
    pwd  = os.getenv("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


def run(engine=None) -> pd.DataFrame:
    """
    Called by build_features.py. Returns DataFrame with clean_id + OSM features.
    Loads coordinates from transactions_clean, computes features, returns result.
    """
    if engine is None:
        engine = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info("Loading transactions_clean coordinates for OSM features...")
    query = """
        SELECT id, latitude, longitude, has_valid_coords
        FROM transactions_clean
        WHERE is_outlier = FALSE
    """
    df = pd.read_sql(query, engine)
    logger.info(f"  {len(df):,} rows loaded")

    result = compute_osm_features(df)

    # Rename id → clean_id for consistency with build_features merge contract
    result = result.rename(columns={"id": "clean_id"})
    return result


def main(dry_run: bool = False) -> None:
    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info("=" * 60)
    logger.info("OSM FEATURES — START")
    logger.info("=" * 60)

    t0 = time.perf_counter()
    result = run(engine=engine)
    elapsed = time.perf_counter() - t0

    logger.info(f"Computed {len(result):,} rows in {elapsed:.1f}s")
    logger.info(f"Columns: {list(result.columns)}")

    # Coverage stats
    for col in result.columns:
        if col == "clean_id":
            continue
        n_nonnan = result[col].notna().sum() if result[col].dtype == float else (result[col] > 0).sum()
        pct = n_nonnan / len(result) * 100
        logger.info(f"  {col}: {n_nonnan:,} non-null/non-zero ({pct:.1f}%)")

    if dry_run:
        logger.info("[DRY RUN] Would merge into transaction_features — skipping DB write")
        logger.info(result.describe().to_string())
        return

    logger.info("OSM FEATURES — COMPLETE (call build_features.py to persist)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute OSM proximity features")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview stats only — do not write to DB")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
