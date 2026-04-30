"""
ingest_candidates.py
--------------------
Ingests property candidates from existing RE_CL tables into opportunity.candidates.

Sources:
  A. cbr_transaction — from transactions_clean (824k rows)
  B. scraped_listing  — from scraped_listings (5k rows)

Run:
  py src/opportunity/ingest_candidates.py
  py src/opportunity/ingest_candidates.py --source cbr --batch-size 10000
  py src/opportunity/ingest_candidates.py --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()

MODEL_VERSION = "v1.0"

TYPE_MAP = {
    "apartments": "apartment",
    "residential": "house",
    "retail": "retail",
    "office": "office",
    "warehouse": "warehouse",
    "industrial": "industrial",
    "unknown": "land",
}

VALID_TYPES = {
    "apartment", "house", "land", "retail", "office",
    "warehouse", "industrial", "gas_station", "pharmacy",
    "supermarket", "bank_branch", "clinic", "restaurant",
}


def map_type(project_type: str, surface_land: float, surface_building: float) -> str:
    if not project_type:
        return "land"
    mapped = TYPE_MAP.get(project_type.lower().strip(), project_type.lower().strip())
    if mapped not in VALID_TYPES:
        # Heuristic: if land >> building, treat as land
        if surface_land and surface_building and surface_land > surface_building * 5:
            return "land"
        return "land"
    # Heuristic for 'unknown': land or building based on ratio
    if mapped == "land" and surface_land and surface_building:
        if surface_building > surface_land * 0.5:
            return "apartment"  # probably a building
    return mapped


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


def ingest_cbr(engine, dry_run: bool = False, batch_size: int = 10000) -> int:
    """ETL: transactions_clean → opportunity.candidates (source='cbr_transaction')."""
    logger.info("Ingesting CBR transactions → opportunity.candidates ...")

    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM transactions_clean")).scalar()
        existing = conn.execute(
            text("SELECT COUNT(*) FROM opportunity.candidates WHERE source='cbr_transaction'")
        ).scalar()

    logger.info(f"  transactions_clean: {total:,} | already in candidates: {existing:,}")

    if dry_run:
        logger.info(f"  [DRY RUN] Would ingest ~{total - existing:,} new rows")
        return 0

    # Single bulk INSERT using psycopg2 directly (avoids SQLAlchemy bind param issues)
    import psycopg2
    db_url = _build_db_url()
    conn_pg = psycopg2.connect(db_url)
    conn_pg.autocommit = False
    cur = conn_pg.cursor()

    bulk_sql = """
        INSERT INTO opportunity.candidates
            (source, source_id, rol_sii, address, county_name,
             latitude, longitude, geom,
             property_type_code, surface_land_m2, surface_building_m2, construction_year,
             last_transaction_uf, last_transaction_date, avaluo_fiscal_uf,
             construction_ratio)
        SELECT
            'cbr_transaction',
            tc.id::TEXT,
            tc.id_role,
            tc.id_role,
            tc.county_name,
            tc.latitude,
            tc.longitude,
            tc.geom,
            CASE
                WHEN tc.project_type = 'apartments'  THEN 'apartment'
                WHEN tc.project_type = 'residential' THEN 'house'
                WHEN tc.project_type = 'retail'      THEN 'retail'
                WHEN tc.project_type = 'unknown'
                  AND tc.surface_land_m2 > COALESCE(tc.surface_building_m2, 0) * 5
                  THEN 'land'
                WHEN tc.project_type = 'unknown'     THEN 'apartment'
                ELSE 'land'
            END,
            tc.surface_land_m2,
            tc.surface_building_m2,
            tc.construction_year,
            tc.uf_value,
            tc.inscription_date,
            tc.calculated_value_uf,
            CASE
                WHEN tc.surface_land_m2 > 0 AND tc.surface_land_m2 > 0.1
                THEN LEAST(99.0, COALESCE(tc.surface_building_m2, 0)::FLOAT / tc.surface_land_m2::FLOAT)
                ELSE NULL
            END
        FROM transactions_clean tc
        WHERE NOT EXISTS (
            SELECT 1 FROM opportunity.candidates oc
            WHERE oc.source = 'cbr_transaction' AND oc.source_id = tc.id::TEXT
        )
        ON CONFLICT (source, source_id) DO NOTHING
    """

    logger.info("  Running bulk INSERT (may take ~5 min for 824k rows)...")
    cur.execute(bulk_sql)
    written = cur.rowcount
    conn_pg.commit()
    cur.close()
    conn_pg.close()
    logger.info(f"  CBR bulk insert done: {written:,} rows")

    return written


def ingest_scraped(engine, dry_run: bool = False) -> int:
    """ETL: scraped_listings → opportunity.candidates (source='scraped_listing')."""
    logger.info("Ingesting scraped listings → opportunity.candidates ...")

    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM scraped_listings")).scalar()
        existing = conn.execute(
            text("SELECT COUNT(*) FROM opportunity.candidates WHERE source='scraped_listing'")
        ).scalar()

    logger.info(f"  scraped_listings: {total:,} | already in candidates: {existing:,}")

    if dry_run:
        logger.info(f"  [DRY RUN] Would ingest ~{total - existing:,} new rows")
        return 0

    insert_sql = text("""
        INSERT INTO opportunity.candidates
            (source, source_id, county_name, latitude, longitude, geom,
             property_type_code, surface_land_m2, surface_building_m2,
             listed_price_uf, listed_at, construction_ratio)
        SELECT
            'scraped_listing',
            sl.id::TEXT,
            sl.county_name,
            sl.latitude,
            sl.longitude,
            CASE
                WHEN sl.latitude IS NOT NULL AND sl.longitude IS NOT NULL
                THEN ST_SetSRID(ST_MakePoint(sl.longitude, sl.latitude), 4326)
                ELSE NULL
            END,
            CASE
                WHEN sl.project_type ILIKE '%department%' OR sl.project_type ILIKE '%apto%' OR sl.project_type = 'apartments' THEN 'apartment'
                WHEN sl.project_type ILIKE '%house%' OR sl.project_type ILIKE '%casa%' OR sl.project_type = 'residential' THEN 'house'
                WHEN sl.project_type ILIKE '%land%' OR sl.project_type ILIKE '%terreno%' THEN 'land'
                WHEN sl.project_type ILIKE '%retail%' OR sl.project_type ILIKE '%local%' THEN 'retail'
                ELSE 'apartment'
            END,
            sl.surface_m2,
            sl.surface_m2,  -- scraped listings usually only have total surface
            sl.price_uf,
            sl.scraped_at,
            NULL
        FROM scraped_listings sl
        WHERE NOT EXISTS (
            SELECT 1 FROM opportunity.candidates oc
            WHERE oc.source = 'scraped_listing' AND oc.source_id = sl.id::TEXT
        )
    """)

    with engine.begin() as conn:
        result = conn.execute(insert_sql)
        written = result.rowcount

    logger.info(f"  Scraped listings written: {written:,}")
    return written


def mark_eriazo(engine, dry_run: bool = False) -> int:
    """Mark candidates as eriazo-like: land >= 500m2 AND construction_ratio < 0.10."""
    logger.info("Marking eriazo candidates ...")

    if dry_run:
        with engine.connect() as conn:
            n = conn.execute(text("""
                SELECT COUNT(*) FROM opportunity.candidates
                WHERE surface_land_m2 >= 500
                  AND COALESCE(construction_ratio, 0) < 0.10
            """)).scalar()
        logger.info(f"  [DRY RUN] Would mark {n:,} candidates as eriazo")
        return 0

    with engine.begin() as conn:
        result = conn.execute(text("""
            UPDATE opportunity.candidates
            SET is_eriazo = TRUE
            WHERE surface_land_m2 >= 500
              AND COALESCE(construction_ratio, 0) < 0.10
              AND is_eriazo = FALSE
        """))
        n = result.rowcount

    logger.info(f"  Marked {n:,} candidates as eriazo")
    return n


def main():
    parser = argparse.ArgumentParser(description="Ingest candidates into opportunity.candidates")
    parser.add_argument("--source", choices=["cbr", "scraped", "all"], default="all")
    parser.add_argument("--batch-size", type=int, default=10000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    total_written = 0

    logger.info("=" * 60)
    logger.info("OPPORTUNITY CANDIDATES INGESTION")
    logger.info("=" * 60)

    if args.source in ("cbr", "all"):
        n = ingest_cbr(engine, dry_run=args.dry_run, batch_size=args.batch_size)
        total_written += n

    if args.source in ("scraped", "all"):
        n = ingest_scraped(engine, dry_run=args.dry_run)
        total_written += n

    n_eriazo = mark_eriazo(engine, dry_run=args.dry_run)

    logger.info("=" * 60)
    logger.info(f"DONE: {total_written:,} candidates written | {n_eriazo:,} eriazo marked")

    if not args.dry_run:
        with engine.connect() as conn:
            r = conn.execute(text("""
                SELECT source, COUNT(*) as n,
                       COUNT(*) FILTER (WHERE is_eriazo) as eriazo
                FROM opportunity.candidates
                GROUP BY source ORDER BY source
            """)).fetchall()
            for row in r:
                logger.info(f"  {row[0]:20s}  {row[1]:,} rows  |  {row[2]:,} eriazo")

    logger.info("=" * 60)


if __name__ == "__main__":
    main()
