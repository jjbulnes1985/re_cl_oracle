"""
scoring_commercial.py
---------------------
Generic commercial use-case scoring overlay.
Reuses the same competition/demand/accessibility logic as gas_station.

Supported use cases (with loaded competitors):
  - pharmacy      (1,212 competitors in DB)
  - supermarket   (545 competitors in DB)
  - bank_branch   (0 — DUDA::bank_branch_overpass_blocked, skip for now)

Run:
  py src/opportunity/scoring_commercial.py --use-case pharmacy
  py src/opportunity/scoring_commercial.py --use-case supermarket
  py src/opportunity/scoring_commercial.py  # all available
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

# Min surface per use case
MIN_SURFACE = {
    "pharmacy":    80,
    "supermarket": 1500,
    "bank_branch": 100,
    "clinic":      200,
    "restaurant":  100,
}

# Cap rates mid (INFO_NO_FIDEDIGNA)
CAP_RATES = {
    "pharmacy":    0.075,
    "supermarket": 0.072,
    "bank_branch": 0.065,
    "clinic":      0.075,
    "restaurant":  0.085,
}

# NOI base UF/yr at min_surface (INFO_NO_FIDEDIGNA)
NOI_BASE = {
    "pharmacy":    1500,
    "supermarket": 12000,
    "bank_branch": 3000,
    "clinic":      2500,
    "restaurant":  800,
}

# Competition analysis radius km
COMPETITION_RADIUS = {
    "pharmacy":    1.0,
    "supermarket": 2.0,
    "bank_branch": 0.5,
    "clinic":      2.0,
    "restaurant":  0.5,
}


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


def score_use_case(use_case: str, engine) -> int:
    """Score all eligible candidates for a given commercial use case."""
    import psycopg2

    min_surface = MIN_SURFACE.get(use_case, 100)
    cap_rate    = CAP_RATES.get(use_case, 0.075)
    noi_base    = NOI_BASE.get(use_case, 1500)
    radius_m    = int(COMPETITION_RADIUS.get(use_case, 1.0) * 1000)

    # Check competitors exist
    with engine.connect() as conn:
        n_comp = conn.execute(text(
            "SELECT COUNT(*) FROM opportunity.competitors WHERE use_case = :uc"
        ), {"uc": use_case}).scalar()
        n_cands = conn.execute(text(
            "SELECT COUNT(*) FROM opportunity.candidates WHERE surface_land_m2 >= :s AND geom IS NOT NULL"
        ), {"s": min_surface}).scalar()

    if n_comp == 0:
        logger.warning(f"  {use_case}: no competitors in DB — DUDA::{use_case}_competitors_missing")
        return 0

    logger.info(f"  {use_case}: {n_comp} competitors, {n_cands} eligible candidates (surface>={min_surface}m2)")

    conn_pg = psycopg2.connect(_build_db_url())
    conn_pg.autocommit = False
    cur = conn_pg.cursor()

    sql = f"""
        WITH
        cands AS (
            SELECT DISTINCT ON (oc.id)
                oc.id,
                oc.county_name,
                oc.geom,
                oc.surface_land_m2,
                oc.last_transaction_uf,
                oc.listed_price_uf,
                oc.is_eriazo,
                bs.undervaluation_score,
                bs.confidence,
                v.estimated_uf
            FROM opportunity.candidates oc
            LEFT JOIN opportunity.scores bs
                ON bs.candidate_id = oc.id AND bs.use_case = 'as_is' AND bs.investor_profile = 'value'
            LEFT JOIN opportunity.valuations v
                ON v.candidate_id = oc.id AND v.method = 'triangulated'
            WHERE oc.surface_land_m2 >= {min_surface} AND oc.geom IS NOT NULL
            ORDER BY oc.id
        ),
        comp_density AS (
            SELECT c.id, COUNT(comp.id) AS n_competitors
            FROM cands c
            LEFT JOIN opportunity.competitors comp
                ON comp.use_case = '{use_case}'
                AND ST_DWithin(c.geom::geography, comp.geom::geography, {radius_m})
            GROUP BY c.id
        ),
        cand_commune_stats AS (
            SELECT c.county_name,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY cd.n_competitors) AS p25,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY cd.n_competitors) AS p75
            FROM cands c
            JOIN comp_density cd ON cd.id = c.id
            GROUP BY c.county_name
        ),
        pop_density AS (
            SELECT county_name, AVG(COALESCE(densidad_norm, 0.5)) AS densidad_norm
            FROM commune_stats
            GROUP BY county_name
        ),
        scored AS (
            SELECT DISTINCT ON (c.id)
                c.id AS candidate_id,
                c.surface_land_m2,
                c.is_eriazo,
                COALESCE(c.undervaluation_score, 0.5) AS underval,
                COALESCE(c.confidence, 0.5) AS conf,
                0.6 AS accessibility_score,
                COALESCE(pd.densidad_norm, 0.5) AS demand_score,
                CASE
                    WHEN cs.p75 - cs.p25 < 0.1 THEN 0.5
                    WHEN cd.n_competitors < cs.p25 THEN 1.0
                    WHEN cd.n_competitors > cs.p75 THEN 0.0
                    ELSE 1.0 - (cd.n_competitors - cs.p25) / NULLIF(cs.p75 - cs.p25, 0)
                END AS competition_score,
                1.0 AS zoning_score,
                cd.n_competitors,
                c.estimated_uf
            FROM cands c
            JOIN comp_density cd ON cd.id = c.id
            JOIN cand_commune_stats cs ON cs.county_name = c.county_name
            LEFT JOIN pop_density pd ON pd.county_name = c.county_name
            ORDER BY c.id
        )
        INSERT INTO opportunity.scores
            (candidate_id, use_case, investor_profile, model_version,
             undervaluation_score, location_score, use_specific_score,
             confidence, opportunity_score, max_payable_uf, drivers)
        SELECT
            candidate_id,
            '{use_case}',
            'operator',
            '{MODEL_VERSION}',
            underval,
            accessibility_score,
            (accessibility_score*0.30 + demand_score*0.25 + competition_score*0.30 + zoning_score*0.15),
            conf,
            LEAST(1, GREATEST(0,
                (accessibility_score*0.30 + demand_score*0.25 + competition_score*0.30 + zoning_score*0.15)*0.60
                + underval*0.25 + conf*0.15
            )),
            ROUND(({noi_base} * LEAST(3.0, GREATEST(0.5, surface_land_m2 / {min_surface}.0)) / {cap_rate})::NUMERIC, 0),
            json_build_object(
                'n_competitors_{use_case}', n_competitors,
                'competition_score', ROUND(competition_score::NUMERIC, 3),
                'demand_score', ROUND(demand_score::NUMERIC, 3),
                'is_eriazo', is_eriazo,
                'disclaimer', 'max_payable_uf: INFO_NO_FIDEDIGNA - proxy cap rate {cap_rate}, NOI proxy. Banda +-150bps.'
            )
        FROM scored
        ON CONFLICT (candidate_id, use_case, investor_profile, model_version) DO UPDATE
            SET opportunity_score = EXCLUDED.opportunity_score,
                use_specific_score = EXCLUDED.use_specific_score,
                max_payable_uf = EXCLUDED.max_payable_uf,
                drivers = EXCLUDED.drivers
    """

    cur.execute(sql)
    n = cur.rowcount
    conn_pg.commit()
    cur.close()
    conn_pg.close()
    logger.info(f"  {use_case}: {n:,} scores written")
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-case", default="all",
                        choices=["all", "pharmacy", "supermarket", "bank_branch", "clinic", "restaurant"])
    args = parser.parse_args()

    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info("=" * 60)
    logger.info("COMMERCIAL SCORING OVERLAYS")
    logger.info("=" * 60)

    use_cases = (
        ["pharmacy", "supermarket"]
        if args.use_case == "all"
        else [args.use_case]
    )

    total = 0
    for uc in use_cases:
        logger.info(f"Scoring {uc}...")
        n = score_use_case(uc, engine)
        total += n

    logger.info(f"DONE: {total:,} commercial scores written")
    logger.info("=" * 60)

    with engine.connect() as conn:
        r = conn.execute(text("""
            SELECT use_case, COUNT(*),
                   ROUND(AVG(opportunity_score)::NUMERIC, 3) AS avg_score,
                   COUNT(*) FILTER (WHERE opportunity_score >= 0.7) AS high
            FROM opportunity.scores
            WHERE use_case != 'as_is'
            GROUP BY use_case ORDER BY use_case
        """)).fetchall()
        for row in r:
            logger.info(f"  {row[0]:15s}  total={row[1]:,}  avg={row[2]}  high(>=0.7)={row[3]:,}")


if __name__ == "__main__":
    main()
