"""
run_di_bulk_multi.py
--------------------
Bulk Data Inmobiliaria scraper with multi-account rotation.

Sorts pending communes from smallest to largest (maximize communes completed per day).
Rotates automatically to next account when quota (402) is hit.
Stops when all accounts are exhausted.

Usage:
  py scripts/run_di_bulk_multi.py                  # use all configured accounts
  py scripts/run_di_bulk_multi.py --dry-run        # preview without writing
  py scripts/run_di_bulk_multi.py --min-year 2019  # default
  py scripts/run_di_bulk_multi.py --max-communes 5 # limit per session

Setup accounts first:
  py scripts/di_setup_accounts.py --account 1
  py scripts/di_setup_accounts.py --account 2
  py scripts/di_setup_accounts.py --account 3
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine

load_dotenv()

DATA_DIR     = Path(__file__).resolve().parents[1] / "data" / "processed"
CHECKPOINT_F = DATA_DIR / "datainmobiliaria_checkpoint.json"
DEFAULT_COOKIE = DATA_DIR / "datainmobiliaria_cookies.json"

# Estimated row counts per commune (based on observed data + RM population proxy).
# Sorted small→large so maximum communes complete before quota hits.
COMMUNE_SIZE_ESTIMATE = {
    "Las Condes":         200,    # observed ~142
    "Vitacura":           500,
    "Pirque":             600,
    "Buin":               900,
    "Melipilla":          900,
    "Talagante":          900,
    "Providencia":       1000,    # observed ~434 (could be more with full quota)
    "Santiago":          1000,    # observed ~404
    "Cerrillos":         1500,
    "Lampa":             1500,
    "Independencia":     1500,
    "Huechuraba":        2000,
    "Lo Barnechea":      2000,
    "Colina":            2000,
    "Estación Central":  2000,
    "San Joaquín":       2000,
    "La Cisterna":       2000,
    "Lo Prado":          3000,
    "Cerro Navia":       3000,
    "Lo Espejo":         3000,
    "San Ramón":         3000,
    "Pedro Aguirre Cerda": 3000,
    "Quinta Normal":     3500,
    "Conchalí":          3500,
    "Recoleta":          3500,
    "San Miguel":        4000,
    "Macul":             4000,
    "Renca":             4000,
    "La Granja":         5000,
    "El Bosque":         5000,
    "Peñalolén":         7000,
    "Quilicura":         8000,
    "La Pintana":        8000,
    "San Bernardo":     12000,
    "Pudahuel":         12600,    # observed ~5819 at page 46 (partial)
    "Maipú":            13000,
    "La Florida":       14127,    # observed
    "Ñuñoa":            15637,    # observed
    "Puente Alto":      15000,
}


def _load_checkpoint() -> dict:
    if CHECKPOINT_F.exists():
        try:
            return json.loads(CHECKPOINT_F.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _discover_accounts() -> list[Path]:
    """Find all cookie files: default + di_cookies_2.json, di_cookies_3.json, ..."""
    files = []
    if DEFAULT_COOKIE.exists():
        files.append(DEFAULT_COOKIE)
    extras = sorted(DATA_DIR.glob("di_cookies_*.json"))
    for f in extras:
        if f not in files:
            files.append(f)
    return files


def _pending_communes_sorted() -> list[str]:
    """Return pending communes sorted by estimated size (small first).
    Partial communes (quota hit mid-scrape) are included and prioritized first
    so they complete before starting new ones.
    """
    from src.scraping.datainmobiliaria import RM_COMMUNE_POLYGONS
    cp = _load_checkpoint()
    fully_done = {k for k, v in cp.items() if not v.get("partial")}
    partial    = {k for k, v in cp.items() if v.get("partial")}
    pending    = [c for c in RM_COMMUNE_POLYGONS if c not in fully_done]
    # Partial communes first (they already have some rows), then small→large
    pending.sort(key=lambda c: (0 if c in partial else 1, COMMUNE_SIZE_ESTIMATE.get(c, 5000)))
    return pending


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


def main():
    parser = argparse.ArgumentParser(description="Bulk DI scraper — multi-account rotation, small communes first")
    parser.add_argument("--dry-run",       action="store_true",        help="Parse but don't write to DB")
    parser.add_argument("--min-year",      type=int,   default=2019,   help="Min inscription year (default: 2019)")
    parser.add_argument("--max-pages",     type=int,   default=100,    help="Max pages per commune (default: 100)")
    parser.add_argument("--max-communes",  type=int,   default=None,   help="Max communes to scrape in this session")
    parser.add_argument("--fuente",        type=str,   default="ventas", choices=["ventas", "catastro"])
    args = parser.parse_args()

    # Discover accounts
    accounts = _discover_accounts()
    if not accounts:
        logger.error("No cookie files found. Run: py scripts/di_setup_accounts.py --account 1")
        sys.exit(1)

    logger.info(f"Accounts configured: {len(accounts)}")
    for i, f in enumerate(accounts, 1):
        logger.info(f"  Account {i}: {f.name}")

    # Pending communes (small → large)
    pending = _pending_communes_sorted()
    if args.max_communes:
        pending = pending[:args.max_communes]

    if not pending:
        logger.info("All communes already scraped. Nothing to do.")
        return

    logger.info(f"\nPending communes ({len(pending)}, smallest first):")
    for c in pending:
        est = COMMUNE_SIZE_ESTIMATE.get(c, "?")
        logger.info(f"  {c:25s} ~{est} rows est.")

    logger.info("")

    # Import scrape_all
    from src.scraping.datainmobiliaria import scrape_all

    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    primary  = accounts[0]
    extras   = accounts[1:] if len(accounts) > 1 else []

    # Optional: per-account proxy URLs from .env (DI_PROXY_1, DI_PROXY_2, DI_PROXY_3, ...)
    # Format: http://user:pass@host:port  (residential proxy) or http://host:port (open proxy)
    proxy_urls = []
    for i in range(1, len(accounts) + 1):
        url = os.getenv(f"DI_PROXY_{i}")
        proxy_urls.append(url if url else None)

    if any(proxy_urls):
        logger.info(f"Proxies configured: {sum(1 for p in proxy_urls if p)}/{len(accounts)}")
        for i, p in enumerate(proxy_urls, 1):
            if p:
                # Hide credentials in log
                masked = p.split("@")[-1] if "@" in p else p
                logger.info(f"  Account {i}: via {masked}")
            else:
                logger.info(f"  Account {i}: direct (no proxy)")
    else:
        logger.info("No proxies configured (set DI_PROXY_1, DI_PROXY_2, DI_PROXY_3 in .env)")

    logger.info("=" * 60)
    logger.info(f"Starting bulk scrape: {len(pending)} communes, {len(accounts)} account(s)")
    logger.info("=" * 60)

    total = asyncio.run(scrape_all(
        engine,
        communes          = pending,
        fuente            = args.fuente,
        dry_run           = args.dry_run,
        max_pages         = args.max_pages,
        min_year          = args.min_year,
        headless          = True,
        use_checkpoint    = True,
        cookie_file       = primary,
        extra_cookie_files= extras,
        proxy_urls        = proxy_urls if any(proxy_urls) else None,
    ))

    # Final status
    cp = _load_checkpoint()
    done_now = [c for c in pending if c in cp]
    still_pending = [c for c in pending if c not in cp]

    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Session complete: {total} rows written")
    logger.info(f"Communes finished this session: {len(done_now)}/{len(pending)}")
    if still_pending:
        logger.info(f"Still pending ({len(still_pending)}): {', '.join(still_pending[:5])}{'...' if len(still_pending)>5 else ''}")
        logger.info("Run again tomorrow with refreshed VPN/accounts to continue.")
    else:
        logger.info("All target communes scraped!")
    logger.info("=" * 60)

    if total > 0 and not args.dry_run:
        # Update PostGIS geom for any rows written without geometry
        logger.info("\nUpdating PostGIS geom for new rows...")
        try:
            with engine.begin() as conn:
                from sqlalchemy import text as _text
                result = conn.execute(_text("""
                    UPDATE transactions_raw
                    SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
                    WHERE longitude IS NOT NULL
                      AND latitude  IS NOT NULL
                      AND geom IS NULL
                      AND data_source = 'data_inmobiliaria'
                """))
                logger.info(f"  geom updated: {result.rowcount} rows")
        except Exception as e:
            logger.warning(f"  geom update skipped: {e}")

        logger.info("\nNext steps:")
        logger.info("  py src/ingestion/clean_transactions.py")
        logger.info("  py src/features/build_features.py --skip-ieut")
        logger.info("  py src/models/hedonic_model.py")


if __name__ == "__main__":
    main()
