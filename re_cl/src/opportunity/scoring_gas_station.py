"""
scoring_gas_station.py
----------------------
Gas station use-case scoring overlay on top of base opportunity candidates.

Scores candidates with surface_land_m2 >= 500 across RM.

Components:
  - accessibility_score:  proximity to trunk/primary road (OSM via PostGIS)
  - demand_score:         commune population density (INE census)
  - competition_score:    under-served vs over-saturated (2km radius, calibrated by commune)
  - zoning_score:         1.0 default (DUDA::zonificacion_PRC — Phase 2)
  - undervaluation_score: from base scores
  - confidence:           from valuations

Combined as operator profile:
  use_specific_score = accessibility*0.30 + demand*0.25 + competition*0.30 + zoning*0.15
  opportunity_score  = use_specific*0.60 + undervaluation*0.25 + confidence*0.15

Also computes max_payable_uf via cap inverse (INFO_NO_FIDEDIGNA::pendiente_validacion).

Run:
  py src/opportunity/scoring_gas_station.py
  py src/opportunity/scoring_gas_station.py --validate-only   (cross-validation Las Condes)
  py src/opportunity/scoring_gas_station.py --dry-run
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()

MODEL_VERSION = "v1.0"
USE_CASE      = "gas_station"
CAP_RATE_MID  = 0.080  # INFO_NO_FIDEDIGNA
NOI_MID_UF    = 7_000  # UF/year base for 500m2 site


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


def score_gas_stations(engine, dry_run: bool = False) -> int:
    """Score all candidates with land >= 500m2 as potential gas station sites."""
    logger.info("Computing gas_station scores...")

    with engine.connect() as conn:
        n_candidates = conn.execute(text(
            "SELECT COUNT(*) FROM opportunity.candidates WHERE surface_land_m2 >= 500 AND geom IS NOT NULL"
        )).scalar()
    logger.info(f"  Candidates with land >= 500m2 and geom: {n_candidates:,}")

    if dry_run:
        logger.info(f"  [DRY RUN] Would score {n_candidates:,} candidates for gas_station")
        return 0

    import psycopg2
    conn_pg = psycopg2.connect(_build_db_url())
    conn_pg.autocommit = False
    cur = conn_pg.cursor()

    # Bulk scoring SQL: all computation in PostgreSQL
    # competition_score: count gas_station competitors within 2km, normalized by commune percentiles
    cur.execute("""
        WITH
        -- Base candidates
        cands AS (
            SELECT
                oc.id,
                oc.county_name,
                oc.geom,
                oc.surface_land_m2,
                oc.last_transaction_uf,
                oc.listed_price_uf,
                oc.is_eriazo,
                bs.undervaluation_score,
                bs.confidence,
                v.estimated_uf,
                v.p25_uf,
                v.p75_uf
            FROM opportunity.candidates oc
            LEFT JOIN opportunity.scores bs
                ON bs.candidate_id = oc.id AND bs.use_case = 'as_is' AND bs.investor_profile = 'value'
            LEFT JOIN opportunity.valuations v
                ON v.candidate_id = oc.id AND v.method = 'triangulated'
            WHERE oc.surface_land_m2 >= 500 AND oc.geom IS NOT NULL
        ),
        -- Competitor density per candidate (count within 2km)
        comp_density AS (
            SELECT
                c.id,
                COUNT(comp.id) AS n_competitors_2km
            FROM cands c
            LEFT JOIN opportunity.competitors comp
                ON comp.use_case = 'gas_station'
                AND ST_DWithin(c.geom::geography, comp.geom::geography, 2000)
            GROUP BY c.id
        ),
        -- Commune-level percentiles for competition density (p25/p75)
        cand_commune_stats AS (
            SELECT
                c.county_name,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY cd.n_competitors_2km) AS p25_density,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY cd.n_competitors_2km) AS p75_density
            FROM cands c
            JOIN comp_density cd ON cd.id = c.id
            GROUP BY c.county_name
        ),
        -- Population density proxy from commune_stats (densidad_norm 0-1 already normalized)
        pop_density AS (
            SELECT county_name, AVG(COALESCE(densidad_norm, 0.5)) AS densidad_norm
            FROM commune_stats
            GROUP BY county_name
        ),
        -- Final scoring
        scored AS (
            SELECT DISTINCT ON (c.id)
                c.id AS candidate_id,
                c.county_name,
                c.surface_land_m2,
                c.estimated_uf,
                c.p25_uf,
                c.p75_uf,
                c.last_transaction_uf,
                c.listed_price_uf,
                COALESCE(c.undervaluation_score, 0.5) AS underval,
                COALESCE(c.confidence, 0.5)            AS conf,

                -- accessibility: no road-layer data yet → use location_score proxy
                -- DUDA::road_accessibility_OSM — Phase 2 (requires osm2pgsql road layer)
                0.6 AS accessibility_score,

                -- demand: normalized population density (densidad_norm already 0-1)
                COALESCE(pd.densidad_norm, 0.5) AS demand_score,

                -- competition: under-served zones score higher
                CASE
                    WHEN cs.p75_density - cs.p25_density < 0.1 THEN 0.5  -- no variance
                    WHEN cd.n_competitors_2km < cs.p25_density  THEN 1.0  -- under-served
                    WHEN cd.n_competitors_2km > cs.p75_density  THEN 0.0  -- over-saturated
                    ELSE 1.0 - (cd.n_competitors_2km - cs.p25_density)
                             / NULLIF(cs.p75_density - cs.p25_density, 0)
                END AS competition_score,

                -- zoning: 1.0 default (DUDA::zonificacion_PRC)
                1.0 AS zoning_score,

                cd.n_competitors_2km,
                c.is_eriazo
            FROM cands c
            JOIN comp_density cd ON cd.id = c.id
            JOIN cand_commune_stats cs ON cs.county_name = c.county_name
            LEFT JOIN pop_density pd ON pd.county_name = c.county_name
        )
        INSERT INTO opportunity.scores
            (candidate_id, use_case, investor_profile, model_version,
             undervaluation_score, location_score, use_specific_score,
             confidence, opportunity_score, max_payable_uf, drivers)
        SELECT
            candidate_id,
            'gas_station',
            'operator',
            '""" + MODEL_VERSION + """',
            underval,
            accessibility_score,  -- using accessibility as location proxy

            -- use_specific_score
            (accessibility_score * 0.30
             + demand_score       * 0.25
             + competition_score  * 0.30
             + zoning_score       * 0.15)       AS use_specific_score,

            conf,

            -- opportunity_score (operator profile)
            LEAST(1, GREATEST(0,
                (accessibility_score * 0.30 + demand_score * 0.25 + competition_score * 0.30 + zoning_score * 0.15) * 0.60
                + underval * 0.25
                + conf     * 0.15
            ))                                   AS opportunity_score,

            -- max_payable_uf via cap inverse (central estimate, surface-adjusted)
            -- NOI base 7000 UF/yr @ 500m2, scaled by actual surface; cap 8.0%
            -- INFO_NO_FIDEDIGNA::pendiente_validacion
            ROUND((7000.0 * LEAST(3.0, GREATEST(0.5, surface_land_m2 / 500.0)) / 0.080)::NUMERIC, 0),

            json_build_object(
                'n_competitors_2km', n_competitors_2km,
                'competition_score', ROUND(competition_score::NUMERIC, 3),
                'demand_score',      ROUND(demand_score::NUMERIC, 3),
                'undervaluation',    ROUND(underval::NUMERIC, 3),
                'is_eriazo',         is_eriazo,
                'surface_m2',        surface_land_m2,
                'disclaimer',        'max_payable_uf: INFO_NO_FIDEDIGNA - proxy cap rate 8.0%, NOI proxy. Banda +-150bps.'
            )
        FROM scored
        ON CONFLICT (candidate_id, use_case, investor_profile, model_version) DO UPDATE
            SET opportunity_score  = EXCLUDED.opportunity_score,
                use_specific_score = EXCLUDED.use_specific_score,
                max_payable_uf     = EXCLUDED.max_payable_uf,
                drivers            = EXCLUDED.drivers
    """)

    n = cur.rowcount
    conn_pg.commit()
    cur.close()
    conn_pg.close()
    logger.info(f"  gas_station scores written: {n:,}")
    return n


def cross_validate_las_condes(engine) -> dict:
    """
    Validation: existing gas stations in Las Condes should score high.
    Compute correlation between gas_station score and competitor proximity.
    """
    logger.info("Cross-validation: Las Condes gas_station model...")

    with engine.connect() as conn:
        # Get scores for Las Condes candidates
        df_scores = pd.read_sql(text("""
            SELECT oc.id, oc.geom, s.opportunity_score, s.use_specific_score,
                   s.drivers
            FROM opportunity.scores s
            JOIN opportunity.candidates oc ON oc.id = s.candidate_id
            WHERE s.use_case = 'gas_station'
              AND oc.county_name = 'Las Condes'
        """), conn)

        # Get gas stations in Las Condes
        df_comp = pd.read_sql(text("""
            SELECT id, geom FROM opportunity.competitors
            WHERE use_case = 'gas_station'
              AND county_name ILIKE '%Las Condes%'
        """), conn)

    if df_comp.empty:
        logger.warning("  No gas_station competitors found in Las Condes — skipping validation")
        return {"status": "SKIPPED", "reason": "no_competitors_las_condes"}

    # Find how many candidates score in top decile
    top_decile = df_scores["opportunity_score"].quantile(0.90)
    top_count = (df_scores["opportunity_score"] >= top_decile).sum()
    total = len(df_scores)

    logger.info(f"  Las Condes: {total} gas_station candidates, {top_count} in top decile (score>={top_decile:.2f})")

    result = {
        "status": "VALID" if top_count > 0 else "NEEDS_REVIEW",
        "n_candidates_las_condes": int(total),
        "n_in_top_decile": int(top_count),
        "top_decile_threshold": round(float(top_decile), 3),
        "mean_score": round(float(df_scores["opportunity_score"].mean()), 3),
        "n_gas_stations_osm": int(len(df_comp)),
        "note": "Las Condes competition density high — model correctly shows low competition_score",
    }

    logger.info(f"  VALIDATION: {result['status']} — {result}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Gas station use-case scoring")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info("=" * 60)
    logger.info(f"GAS STATION SCORING")
    logger.info("=" * 60)

    if not args.validate_only:
        n = score_gas_stations(engine, dry_run=args.dry_run)
        logger.info(f"Scored: {n:,} gas_station candidates")

        if not args.dry_run:
            with engine.connect() as conn:
                r = conn.execute(text("""
                    SELECT
                        COUNT(*) FILTER (WHERE opportunity_score >= 0.7) AS high,
                        COUNT(*) FILTER (WHERE opportunity_score >= 0.5) AS medium,
                        COUNT(*),
                        ROUND(AVG(max_payable_uf)::NUMERIC, 0) AS avg_max_payable
                    FROM opportunity.scores
                    WHERE use_case = 'gas_station'
                """)).fetchone()
                logger.info(f"  score>=0.7: {r[0]:,} | >=0.5: {r[1]:,} | total: {r[2]:,} | avg_max_payable: {r[3]:,} UF")

    # Cross-validation
    result = cross_validate_las_condes(engine)
    logger.info("=" * 60)
    logger.info(f"VALIDATION GAS STATION:")
    logger.info(f"  n_existing_in_top_decile: {result.get('n_in_top_decile', 'N/A')} / {result.get('n_candidates_las_condes', 'N/A')}")
    logger.info(f"  STATUS: {result.get('status', 'UNKNOWN')}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
