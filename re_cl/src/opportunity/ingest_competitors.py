"""
ingest_competitors.py
---------------------
Fetches existing commercial operators from OSM Overpass API and loads them
into opportunity.competitors.

Use cases covered:
  - gas_station  (amenity=fuel)
  - pharmacy     (amenity=pharmacy)
  - bank_branch  (amenity=bank)
  - supermarket  (shop=supermarket)

Run:
  py src/opportunity/ingest_competitors.py
  py src/opportunity/ingest_competitors.py --use-case gas_station
  py src/opportunity/ingest_competitors.py --dry-run
"""

import argparse
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# RM Santiago bounding box: south, west, north, east
RM_BBOX = "-33.75,-71.05,-33.25,-70.35"

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

USE_CASE_QUERIES = {
    "gas_station": f"""
        [out:json][timeout:60];
        (
          node["amenity"="fuel"]({RM_BBOX});
          way["amenity"="fuel"]({RM_BBOX});
        );
        out center;
    """,
    "pharmacy": f"""
        [out:json][timeout:60];
        (
          node["amenity"="pharmacy"]({RM_BBOX});
          way["amenity"="pharmacy"]({RM_BBOX});
        );
        out center;
    """,
    "bank_branch": f"""
        [out:json][timeout:60];
        (
          node["amenity"="bank"]({RM_BBOX});
          way["amenity"="bank"]({RM_BBOX});
        );
        out center;
    """,
    "supermarket": f"""
        [out:json][timeout:60];
        (
          node["shop"="supermarket"]({RM_BBOX});
          way["shop"="supermarket"]({RM_BBOX});
        );
        out center;
    """,
}

# Canonical operator name mapping (brand → canonical)
OPERATOR_MAP = {
    # Gas stations
    "copec": "Copec",
    "enex": "Shell/Enex",
    "shell": "Shell/Enex",
    "aramco": "Aramco",
    "esmax": "Aramco",
    "petrobras": "Aramco",
    "bp": "BP",
    "repsol": "Repsol",
    # Pharmacies
    "cruz verde": "Cruz Verde",
    "salcobrand": "Salcobrand",
    "ahumada": "Ahumada",
    "dr. simi": "Dr. Simi",
    "farmacias similares": "Dr. Simi",
    # Banks
    "banco estado": "Banco Estado",
    "bancoestado": "Banco Estado",
    "bci": "BCI",
    "santander": "Santander",
    "scotiabank": "Scotiabank",
    "itaú": "Itau",
    "itau": "Itau",
    "falabella": "Banco Falabella",
    "banco falabella": "Banco Falabella",
    "bice": "BICE",
    "consorcio": "Consorcio",
    # Supermarkets
    "lider": "Lider/Walmart",
    "walmart": "Lider/Walmart",
    "jumbo": "Jumbo/Cencosud",
    "cencosud": "Jumbo/Cencosud",
    "santa isabel": "Santa Isabel",
    "tottus": "Tottus/Falabella",
    "unimarc": "Unimarc",
    "acuenta": "Acuenta",
    "ekono": "Ekono",
}


def _canonical_operator(tags: dict) -> str:
    for key in ("brand", "operator", "name"):
        val = tags.get(key, "")
        if val:
            low = val.lower().strip()
            for pattern, canonical in OPERATOR_MAP.items():
                if pattern in low:
                    return canonical
            return val[:100]
    return "Unknown"


def _extract_point(element: dict) -> tuple[float, float] | None:
    if element.get("type") == "node":
        return element.get("lat"), element.get("lon")
    elif element.get("type") == "way":
        center = element.get("center", {})
        if center:
            return center.get("lat"), center.get("lon")
    return None, None


def fetch_overpass(use_case: str) -> list[dict]:
    query = USE_CASE_QUERIES[use_case].strip()
    logger.info(f"  Querying Overpass for {use_case} in RM ...")
    headers = {"Accept": "*/*", "Content-Type": "application/x-www-form-urlencoded"}
    for url in OVERPASS_URLS:
        for attempt in range(2):
            try:
                resp = requests.post(url, data={"data": query}, headers=headers, timeout=120)
                if resp.status_code == 200:
                    elements = resp.json().get("elements", [])
                    logger.info(f"  {use_case}: {len(elements)} OSM elements found (via {url.split('/')[2]})")
                    return elements
                logger.warning(f"  {url.split('/')[2]} attempt {attempt+1} returned {resp.status_code}")
            except Exception as e:
                logger.warning(f"  {url.split('/')[2]} attempt {attempt+1} failed: {e}")
            time.sleep(3)
    logger.error(f"  Failed to fetch {use_case} from all Overpass endpoints")
    return []


def ingest_use_case(use_case: str, elements: list[dict], engine, dry_run: bool = False) -> int:
    from sqlalchemy import text

    if not elements:
        return 0

    rows = []
    for el in elements:
        lat, lon = _extract_point(el)
        if not lat or not lon:
            continue
        tags = el.get("tags", {})
        operator = _canonical_operator(tags)
        name = tags.get("name", tags.get("brand", ""))
        addr = tags.get("addr:street", "")
        if tags.get("addr:housenumber"):
            addr += f" {tags['addr:housenumber']}"
        county = tags.get("addr:city", tags.get("addr:suburb", ""))
        source_id = f"osm_{el['type']}_{el['id']}"
        rows.append({
            "use_case": use_case,
            "operator": operator,
            "name": name[:200] if name else None,
            "address": addr[:500] if addr else None,
            "county_name": county[:100] if county else None,
            "latitude": lat,
            "longitude": lon,
            "source": "osm",
            "source_id": source_id,
        })

    if dry_run:
        logger.info(f"  [DRY RUN] Would insert {len(rows)} {use_case} competitors")
        return 0

    if not rows:
        return 0

    insert_sql = text("""
        INSERT INTO opportunity.competitors
            (use_case, operator, name, address, county_name,
             latitude, longitude, geom, source, source_id)
        VALUES
            (:use_case, :operator, :name, :address, :county_name,
             :latitude, :longitude,
             ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326),
             :source, :source_id)
        ON CONFLICT (source, source_id) DO NOTHING
    """)

    written = 0
    with engine.begin() as conn:
        for row in rows:
            result = conn.execute(insert_sql, row)
            written += result.rowcount

    logger.info(f"  {use_case}: {written} competitors written to DB")
    return written


def main():
    parser = argparse.ArgumentParser(description="Ingest commercial competitors from OSM")
    parser.add_argument("--use-case", choices=list(USE_CASE_QUERIES.keys()) + ["all"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from sqlalchemy import create_engine
    db_url = os.getenv("DATABASE_URL") or "postgresql://{user}:{pwd}@{host}:{port}/{db}".format(
        user=os.getenv("POSTGRES_USER", "re_cl_user"),
        pwd=os.getenv("POSTGRES_PASSWORD", ""),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        db=os.getenv("POSTGRES_DB", "re_cl"),
    )
    engine = create_engine(db_url, pool_pre_ping=True)

    use_cases = list(USE_CASE_QUERIES.keys()) if args.use_case == "all" else [args.use_case]

    logger.info("=" * 60)
    logger.info("COMPETITORS INGESTION (OSM)")
    logger.info("=" * 60)

    total = 0
    for uc in use_cases:
        elements = fetch_overpass(uc)
        n = ingest_use_case(uc, elements, engine, dry_run=args.dry_run)
        total += n
        time.sleep(2)  # OSM rate limit courtesy

    logger.info("=" * 60)
    logger.info(f"DONE: {total} competitors written")

    if not args.dry_run:
        from sqlalchemy import text
        with engine.connect() as conn:
            r = conn.execute(text(
                "SELECT use_case, COUNT(*), COUNT(DISTINCT operator) as operators "
                "FROM opportunity.competitors GROUP BY use_case ORDER BY use_case"
            )).fetchall()
            for row in r:
                logger.info(f"  {row[0]:15s}  {row[1]:,} locations  |  {row[2]} operators")

    logger.info("=" * 60)


if __name__ == "__main__":
    main()
