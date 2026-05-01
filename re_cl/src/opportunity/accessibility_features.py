"""
accessibility_features.py
--------------------------
Computes real road accessibility scores for opportunity candidates using OSM road network.

Fetches trunk/primary/secondary roads for RM Santiago via osmnx,
builds a BallTree spatial index, then computes min distance (km) from each
candidate to the nearest major road.

Accessibility score:
  0 km → 1.0
  2 km → 0.0
  linear interpolation

Updates opportunity.scores.location_score and re-computes opportunity_score
for gas_station, pharmacy, supermarket overlays.

Run:
  py src/opportunity/accessibility_features.py              # all commercial use cases
  py src/opportunity/accessibility_features.py --dry-run    # preview only
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()

ROAD_CACHE = Path(__file__).resolve().parents[2] / "data" / "processed" / "rm_major_roads.pkl"
RM_BBOX = (-33.75, -71.05, -33.25, -70.35)  # south, west, north, east


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


def load_road_nodes(force_refresh: bool = False) -> np.ndarray:
    """
    Returns Nx2 array of (lat, lon) for trunk/primary/secondary road nodes in RM.
    Cached to disk for 30 days.
    """
    import pickle, time

    if ROAD_CACHE.exists() and not force_refresh:
        mtime = ROAD_CACHE.stat().st_mtime
        if time.time() - mtime < 30 * 86400:
            logger.info("  Loading road nodes from cache...")
            with open(ROAD_CACHE, "rb") as f:
                return pickle.load(f)

    logger.info("  Fetching road network via Overpass API (trunk/primary/secondary)...")
    import requests, time

    overpass_urls = [
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass-api.de/api/interpreter",
    ]
    south, west, north, east = RM_BBOX
    query = f"""
        [out:json][timeout:120];
        (
          way["highway"~"^(motorway|trunk|primary|secondary)$"]({south},{west},{north},{east});
        );
        out geom;
    """

    elements = []
    for url in overpass_urls:
        for attempt in range(2):
            try:
                resp = requests.post(url, data={"data": query},
                                     headers={"Accept": "*/*"}, timeout=150)
                if resp.status_code == 200:
                    elements = resp.json().get("elements", [])
                    logger.info(f"  {len(elements)} road segments via {url.split('/')[2]}")
                    break
                logger.warning(f"  {url.split('/')[2]} returned {resp.status_code}")
            except Exception as e:
                logger.warning(f"  {url.split('/')[2]} error: {e}")
            time.sleep(3)
        if elements:
            break

    if not elements:
        raise RuntimeError("Could not fetch road data from any Overpass endpoint")

    # Extract node coordinates from way geometries
    coords_list = []
    for el in elements:
        if el.get("type") == "way" and "geometry" in el:
            for node in el["geometry"]:
                coords_list.append((node["lat"], node["lon"]))

    coords_arr = np.radians(np.array(coords_list))
    ROAD_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(ROAD_CACHE, "wb") as f:
        pickle.dump(coords_arr, f)
    logger.info(f"  {len(coords_arr):,} road points cached")
    return coords_arr


def compute_accessibility(engine, road_nodes: np.ndarray, min_surface: float = 80.0) -> int:
    """
    Compute min distance to major road for each candidate.
    Updates opportunity.scores.location_score.
    """
    from sklearn.neighbors import BallTree

    logger.info("  Building BallTree on road nodes...")
    tree = BallTree(road_nodes, metric="haversine")

    logger.info("  Loading candidate coordinates...")
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, latitude, longitude
            FROM opportunity.candidates
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
              AND surface_land_m2 >= :s
        """), {"s": min_surface}).fetchall()

    logger.info(f"  {len(rows):,} candidates to process")

    coords = np.radians(np.array([[r[1], r[2]] for r in rows]))
    dist_rad, _ = tree.query(coords, k=1)
    dist_km = dist_rad[:, 0] * 6371.0  # Earth radius

    # Accessibility score: 0km=1.0, 2km=0.0, linear
    access_scores = np.clip(1.0 - dist_km / 2.0, 0.0, 1.0)

    logger.info(f"  dist_km_road: median={np.median(dist_km):.3f}km, mean={np.mean(dist_km):.3f}km")

    # Bulk update in batches
    import psycopg2
    conn_pg = psycopg2.connect(_build_db_url())
    conn_pg.autocommit = False
    cur = conn_pg.cursor()

    # Store accessibility scores in a temp table then join-update
    cur.execute("""
        CREATE TEMP TABLE tmp_road_access (
            candidate_id BIGINT, dist_km_road FLOAT, accessibility_score FLOAT
        )
    """)

    batch = [(int(rows[i][0]), float(dist_km[i]), float(access_scores[i]))
             for i in range(len(rows))]
    cur.executemany(
        "INSERT INTO tmp_road_access VALUES (%s, %s, %s)",
        batch
    )
    conn_pg.commit()

    # Update all commercial use case scores
    cur.execute("""
        UPDATE opportunity.scores s
        SET location_score = t.accessibility_score,
            opportunity_score = LEAST(1, GREATEST(0,
                (t.accessibility_score*0.30
                 + COALESCE(s.growth_score, 0.5)*0.25
                 + COALESCE(s.redevelopment_score, 0.3)*0.30
                 + 1.0*0.15)*0.60
                + COALESCE(s.undervaluation_score, 0.5)*0.25
                + COALESCE(s.confidence, 0.5)*0.15
            ))
        FROM tmp_road_access t
        WHERE s.candidate_id = t.candidate_id
          AND s.use_case IN ('gas_station', 'pharmacy', 'supermarket')
    """)
    n = cur.rowcount
    conn_pg.commit()

    # Also update as_is scores with location_score
    cur.execute("""
        UPDATE opportunity.scores s
        SET location_score = t.accessibility_score,
            opportunity_score = LEAST(1, GREATEST(0,
                COALESCE(s.undervaluation_score, 0.5)*0.65
                + t.accessibility_score*0.15
                + COALESCE(s.confidence, 0.5)*0.20
            ))
        FROM tmp_road_access t
        WHERE s.candidate_id = t.candidate_id AND s.use_case = 'as_is'
    """)
    n_asis = cur.rowcount
    conn_pg.commit()
    cur.close()
    conn_pg.close()

    logger.info(f"  Updated location_score for {n:,} commercial + {n_asis:,} as_is scores")
    return n + n_asis


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()

    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info("=" * 60)
    logger.info("ACCESSIBILITY FEATURES (OSM road proximity)")
    logger.info("=" * 60)

    road_nodes = load_road_nodes(force_refresh=args.force_refresh)
    logger.info(f"  {len(road_nodes):,} road points loaded")

    if args.dry_run:
        logger.info("  [DRY RUN] Would update accessibility scores")
        return

    n = compute_accessibility(engine, road_nodes)
    logger.info(f"DONE: {n:,} scores updated with real road accessibility")

    # Summary after update
    with engine.connect() as conn:
        r = conn.execute(text("""
            SELECT use_case,
                   ROUND(AVG(location_score)::NUMERIC, 3) AS avg_location,
                   COUNT(*) FILTER (WHERE opportunity_score >= 0.7) AS high
            FROM opportunity.scores
            GROUP BY use_case ORDER BY use_case
        """)).fetchall()
        logger.info("Score summary after accessibility update:")
        for row in r:
            logger.info(f"  {row[0]:15s}  avg_location={row[1]}  score>=0.7={row[2]:,}")

    logger.info("=" * 60)


if __name__ == "__main__":
    main()
