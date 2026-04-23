"""
normalize_county.py
-------------------
Fuzzy normalization of county_name in scraped_listings.

Problem: Scrapers produce inconsistent county names:
  "Las Condes" → OK
  "la condes"  → fuzzy → "Las Condes"
  "Nunoa"      → fuzzy → "Ñuñoa"  (missing tilde)
  "1 - 300"    → NULL  (address fragment, not a commune)
  "Depto. Vitacura" → "Vitacura"

Solution: rapidfuzz WRatio against canonical 40 RM communes.
  score >= 85 → assign canonical name
  score < 85  → set to NULL (excluded from scoring)

Usage:
    py src/ingestion/normalize_county.py
    py src/ingestion/normalize_county.py --dry-run
    py src/ingestion/normalize_county.py --min-score 80
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Canonical 40 RM communes
RM_COMMUNES_CANONICAL = [
    "Alhué", "Buin", "Calera de Tango", "Cerrillos", "Cerro Navia",
    "Colina", "Conchalí", "Curacaví", "El Bosque", "El Monte",
    "Estación Central", "Huechuraba", "Independencia", "Isla de Maipo",
    "La Cisterna", "La Florida", "La Granja", "La Pintana", "La Reina",
    "Lampa", "Las Condes", "Lo Barnechea", "Lo Espejo", "Lo Prado",
    "Macul", "Maipú", "María Pinto", "Melipilla", "Padre Hurtado",
    "Paine", "Pedro Aguirre Cerda", "Peñaflor", "Peñalolén", "Pirque",
    "Pudahuel", "Puente Alto", "Quilicura", "Quinta Normal", "Recoleta",
    "Renca", "San Bernardo", "San Joaquín", "San José de Maipo",
    "San Miguel", "San Ramón", "Santiago", "Talagante", "Tiltil",
    "Vitacura", "Ñuñoa",
]

# Exact string overrides before fuzzy matching (common typos/aliases)
EXACT_OVERRIDES: dict[str, str] = {
    "nunoa": "Ñuñoa",
    "ñunoa": "Ñuñoa",
    "nuñoa": "Ñuñoa",
    "pedro aguirre cerda": "Pedro Aguirre Cerda",
    "pac": "Pedro Aguirre Cerda",
    "san jose de maipo": "San José de Maipo",
    "calera de tango": "Calera de Tango",
    "estacion central": "Estación Central",
    "conchal": "Conchalí",
    "penalolen": "Peñalolén",
    "penaflor": "Peñaflor",
    "maria pinto": "María Pinto",
    "maipo": "Isla de Maipo",
    "lo barnechea": "Lo Barnechea",
    "barnechea": "Lo Barnechea",
    "puente alto": "Puente Alto",
    "las condes": "Las Condes",
    "vitacura": "Vitacura",
    "providencia": "Providencia",   # not in RM_40 but common — keep as-is
    "santiago centro": "Santiago",
    "centro": "Santiago",
}


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


def _normalize_one(raw: str, min_score: int = 85) -> str | None:
    """
    Normalize a single county name string.
    Returns canonical name or None if no match found.
    """
    if not raw or not isinstance(raw, str):
        return None

    # Strip numbers/punctuation at start (address fragments)
    cleaned = raw.strip()

    # Skip obvious non-communes (all digits, short codes, etc.)
    if not cleaned or len(cleaned) < 3:
        return None
    if cleaned.replace(" ", "").replace("-", "").isdigit():
        return None

    # Take first token before comma/dot (remove apartment/address suffix)
    cleaned = cleaned.split(",")[0].split(".")[0].strip()

    # Exact override (lowercase key)
    lower = cleaned.lower().strip()
    if lower in EXACT_OVERRIDES:
        return EXACT_OVERRIDES[lower]

    # Check exact match in canonical list (case-insensitive)
    for canon in RM_COMMUNES_CANONICAL:
        if canon.lower() == lower:
            return canon

    # Fuzzy matching
    try:
        from rapidfuzz import process, fuzz
        match, score, _ = process.extractOne(
            cleaned,
            RM_COMMUNES_CANONICAL,
            scorer=fuzz.WRatio,
        )
        if score >= min_score:
            return match
    except ImportError:
        logger.warning("rapidfuzz not installed — only exact matching available. pip install rapidfuzz")
        return None

    return None


def normalize_county(engine, min_score: int = 85, dry_run: bool = False) -> dict:
    """
    Normalize county_name for all scraped_listings.
    Adds normalized_county column and updates records.
    Returns summary stats.
    """
    # Ensure column exists
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE scraped_listings
            ADD COLUMN IF NOT EXISTS county_raw VARCHAR(200),
            ADD COLUMN IF NOT EXISTS county_normalized BOOLEAN DEFAULT FALSE
        """))

    # Load all distinct raw county names
    with engine.connect() as conn:
        raw_df = pd.read_sql(text("""
            SELECT DISTINCT county_name
            FROM scraped_listings
            WHERE county_normalized = FALSE OR county_normalized IS NULL
        """), conn)

    if raw_df.empty:
        logger.info("No county names to normalize.")
        return {"total": 0, "matched": 0, "nulled": 0}

    distinct_names = raw_df["county_name"].dropna().tolist()
    logger.info(f"Normalizing {len(distinct_names):,} distinct county names (min_score={min_score})")

    # Build mapping
    mapping: dict[str, str | None] = {}
    for raw in distinct_names:
        canonical = _normalize_one(raw, min_score=min_score)
        mapping[raw] = canonical

    # Stats
    matched = sum(1 for v in mapping.values() if v is not None)
    nulled  = sum(1 for v in mapping.values() if v is None)
    logger.info(f"  Matched: {matched:,} | Set to NULL: {nulled:,}")

    # Show unmatched for review
    unmatched = [(k, v) for k, v in mapping.items() if v is None and k]
    if unmatched:
        logger.info(f"  Unmatched ({len(unmatched)}): {[u[0] for u in unmatched[:20]]}")

    if dry_run:
        logger.info("[DRY RUN] No updates written.")
        return {"total": len(distinct_names), "matched": matched, "nulled": nulled}

    # Apply updates
    with engine.begin() as conn:
        # Save raw before overwriting
        conn.execute(text("""
            UPDATE scraped_listings
            SET county_raw = county_name
            WHERE county_raw IS NULL
        """))

        for raw, canonical in mapping.items():
            conn.execute(text("""
                UPDATE scraped_listings
                SET county_name = :canonical,
                    county_normalized = TRUE
                WHERE county_name = :raw
                  AND (county_normalized = FALSE OR county_normalized IS NULL)
            """), {"raw": raw, "canonical": canonical})

    logger.info(f"County normalization complete: {matched:,} matched, {nulled:,} set to NULL")
    return {"total": len(distinct_names), "matched": matched, "nulled": nulled}


def print_county_report(engine) -> None:
    """Print county distribution in scraped_listings."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT county_name, COUNT(*) AS n
            FROM scraped_listings
            GROUP BY county_name
            ORDER BY n DESC
            LIMIT 30
        """), conn)
    logger.info("Top 30 counties in scraped_listings:")
    for _, row in df.iterrows():
        flag = "" if row["county_name"] in RM_COMMUNES_CANONICAL else " [!]"
        logger.info(f"  {row['county_name'] or 'NULL':<30} {row['n']:>5}{flag}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--min-score", type=int, default=85,
                        help="Minimum fuzzy match score (0-100, default: 85)")
    parser.add_argument("--report",    action="store_true",
                        help="Print county distribution and exit")
    args = parser.parse_args()

    from sqlalchemy import create_engine as _ce
    engine = _ce(_build_db_url(), pool_pre_ping=True)

    if args.report:
        print_county_report(engine)
    else:
        normalize_county(engine, min_score=args.min_score, dry_run=args.dry_run)
        print_county_report(engine)
