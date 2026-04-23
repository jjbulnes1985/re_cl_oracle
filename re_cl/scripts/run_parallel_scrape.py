"""
run_parallel_scrape.py
----------------------
Phase 9: Single-command CLI entry for parallel multi-source scraping.

Runs PI (40 communes x 4 types in batches) + Toctoc (4 types concurrent)
CONCURRENTLY via ThreadPoolExecutor -> DataInmobiliaria (next unscraped
commune, saved cookies) -> normalize_county -> scraped_to_scored.

Usage:
    py scripts/run_parallel_scrape.py
    py scripts/run_parallel_scrape.py --batch-size 3              # gentler on MeLi
    py scripts/run_parallel_scrape.py --max-pages-toctoc 100      # deeper Toctoc
    py scripts/run_parallel_scrape.py --skip-di                   # skip DI (quota)
    py scripts/run_parallel_scrape.py --dry-run                   # preview

Prereq: data/processed/datainmobiliaria_cookies.json must exist.
        Create once: py src/scraping/datainmobiliaria.py --manual-login
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipelines.flows import parallel_scrape_flow


def main():
    parser = argparse.ArgumentParser(
        description="Phase 9: run parallel multi-source scrape + post-process"
    )
    parser.add_argument("--batch-size", type=int, default=6,
                        help="PI parallel batch size (3-8 recommended). Default: 6")
    parser.add_argument("--pi-max-pages", type=int, default=1,
                        help="Max pages per PI commune request. Default: 1 (MeLi gate).")
    parser.add_argument("--max-pages-toctoc", type=int, default=50,
                        help="Toctoc pages per type. Default: 50")
    parser.add_argument("--di-min-year", type=int, default=2019,
                        help="DataInmobiliaria min year. Default: 2019")
    parser.add_argument("--di-max-pages", type=int, default=100,
                        help="DataInmobiliaria max pages per commune. Default: 100")
    parser.add_argument("--skip-di", action="store_true",
                        help="Skip DataInmobiliaria (use when quota exhausted)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without DB writes")
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("PHASE 9 - PARALLEL SCRAPE + POST-PROCESS")
    logger.info(f"  PI batch_size:       {args.batch_size}")
    logger.info(f"  PI max_pages:        {args.pi_max_pages}")
    logger.info(f"  Toctoc max_pages:    {args.max_pages_toctoc}")
    logger.info(f"  DI min_year:         {args.di_min_year}")
    logger.info(f"  Skip DI:             {args.skip_di}")
    logger.info(f"  Dry run:             {args.dry_run}")
    logger.info("=" * 70)

    result = parallel_scrape_flow(
        pi_batch_size=args.batch_size,
        pi_max_pages=args.pi_max_pages,
        toctoc_max_pages=args.max_pages_toctoc,
        di_min_year=args.di_min_year,
        di_max_pages=args.di_max_pages,
        skip_di=args.skip_di,
        dry_run=args.dry_run,
    )

    logger.info("=" * 70)
    logger.info("RESULT")
    for k, v in result.items():
        logger.info(f"  {k}: {v}")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
