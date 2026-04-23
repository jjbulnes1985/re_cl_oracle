"""
flows.py
--------
Prefect flows for RE_CL pipeline orchestration.

Flows:
  full_pipeline      — End-to-end: ingest → clean → features → train → score → maps
  scoring_only       — Re-score with existing model (skips training)
  scraping_flow      — Scrape fresh listings → score → maps
  maps_only          — Regenerate maps/ranking from existing scores

Scheduling examples (configure in Prefect UI or via CLI):
  prefect deployment build src/pipelines/flows.py:full_pipeline -n weekly --cron "0 3 * * 0"
  prefect deployment build src/pipelines/flows.py:scraping_flow -n daily  --cron "0 5 * * *"

Usage (local):
  python src/pipelines/flows.py                           # full pipeline
  python src/pipelines/flows.py --flow scoring_only
  python src/pipelines/flows.py --flow maps_only
  python src/pipelines/flows.py --flow scraping --max-pages 100
"""

import argparse
import concurrent.futures
import os
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from prefect import flow
from prefect.logging import get_run_logger

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.pipelines.tasks import (
    task_load_transactions,
    task_clean_transactions,
    task_build_features,
    task_osm_enrichment,
    task_gtfs_enrichment,
    task_train_model,
    task_score,
    task_backtesting,
    task_commune_ranking,
    task_heatmap,
    task_scrape_portal,
    task_scrape_toctoc,
    task_run_alerts,
    task_webhook_notify,
    task_scrape_pi_parallel,
    task_scrape_toctoc_parallel,
    task_scrape_di_next_commune,
    task_normalize_county,
    task_score_scraped,
)

MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0")


# ── Full pipeline ──────────────────────────────────────────────────────────────

@flow(
    name="RE_CL Full Pipeline",
    description="End-to-end: ingest CSV → clean → features → OSM → train hedonic model → score → backtesting → maps",
)
def full_pipeline(
    csv_path: str = None,
    dry_run: bool = False,
    retrain: bool = True,
    skip_osm: bool = False,
    skip_gtfs: bool = False,
) -> dict:
    """
    Full RE_CL pipeline.
    Runs sequentially: ingestion → cleaning → features → OSM enrichment →
    GTFS enrichment → model → scoring → backtesting → maps.

    Parameters
    ----------
    csv_path : str, optional
        Path to raw CSV file. Falls back to RAW_CSV_PATH env var.
    dry_run : bool
        If True, no data is written to the database.
    retrain : bool
        If False, skips model training (uses existing model on disk).
    skip_osm : bool
        If True, skips the OSM enrichment step (useful when offline).
    skip_gtfs : bool
        If True, skips the GTFS bus-stop enrichment step (V6).
    """
    logger = get_run_logger()
    logger.info(f"=== RE_CL Full Pipeline START (version={MODEL_VERSION}, skip_osm={skip_osm}, skip_gtfs={skip_gtfs}) ===")

    results = {}

    # Step 1: Ingest
    results["n_raw"] = task_load_transactions(csv_path=csv_path)

    # Step 2: Clean (depends on ingestion completing)
    results["n_clean"] = task_clean_transactions(dry_run=dry_run)

    # Step 3: Features
    results["n_features"] = task_build_features(dry_run=dry_run)

    # Step 4: OSM enrichment (V4.2) — skippable when offline
    results["osm"] = task_osm_enrichment(skip_osm=skip_osm)

    # Step 4b: GTFS enrichment (V6) — skippable when offline
    if not skip_gtfs:
        results["gtfs"] = task_gtfs_enrichment()
    else:
        logger.info("Skipping GTFS enrichment (skip_gtfs=True)")

    # Step 5: Train (optional — skip if model already exists)
    if retrain:
        results["metrics"] = task_train_model()
    else:
        logger.info("Skipping model training (retrain=False)")

    # Step 6: Score
    task_score(dry_run=dry_run)

    # Step 7: Backtesting (V4.5)
    results["backtesting"] = task_backtesting()

    # Step 8: Maps
    task_commune_ranking(dry_run=dry_run)
    results["heatmap"] = task_heatmap()

    task_webhook_notify("pipeline_complete", count=0)
    logger.info(f"=== RE_CL Full Pipeline DONE ===")
    return results


# ── Scoring only (skip ingestion & training) ─────────────────────────────────

@flow(
    name="RE_CL Scoring Only",
    description="Re-compute scores with existing model. Skips ingestion and training.",
)
def scoring_only(dry_run: bool = False) -> None:
    logger = get_run_logger()
    logger.info(f"=== Scoring Only (version={MODEL_VERSION}) ===")

    task_score(dry_run=dry_run)
    task_commune_ranking(dry_run=dry_run)
    task_heatmap()

    task_webhook_notify("scoring_complete", count=0)
    logger.info("=== Scoring Only DONE ===")


# ── Maps only ─────────────────────────────────────────────────────────────────

@flow(
    name="RE_CL Maps Only",
    description="Regenerate heatmap and commune ranking from existing model_scores.",
)
def maps_only(dry_run: bool = False) -> str:
    logger = get_run_logger()
    logger.info("=== Maps Only ===")

    task_commune_ranking(dry_run=dry_run)
    out = task_heatmap()

    logger.info(f"=== Maps Only DONE: {out} ===")
    return out


# ── Scraping flow (V2) ────────────────────────────────────────────────────────

@flow(
    name="RE_CL Scraping + Score",
    description="Scrape fresh listings from Portal Inmobiliario & Toctoc, then re-score.",
)
def scraping_flow(
    max_pages: int = 50,
    dry_run: bool = False,
    sources: list = None,
) -> dict:
    """
    V2 flow: scrape fresh data from portals → re-score → maps.
    sources: list of ["portal", "toctoc"] (default: both)
    """
    logger = get_run_logger()
    if sources is None:
        sources = ["portal", "toctoc"]

    logger.info(f"=== Scraping Flow START (sources={sources}, max_pages={max_pages}) ===")

    results = {}

    if "portal" in sources:
        results["n_portal"] = task_scrape_portal(max_pages=max_pages)

    if "toctoc" in sources:
        results["n_toctoc"] = task_scrape_toctoc(max_pages=max_pages)

    # Re-score with fresh data
    task_score(dry_run=dry_run)
    task_commune_ranking(dry_run=dry_run)
    results["heatmap"] = task_heatmap()

    logger.info(f"=== Scraping Flow DONE: {results} ===")
    return results


# ── Backtesting flow (V4.5) ───────────────────────────────────────────────────

@flow(
    name="RE_CL Backtest",
    description="Standalone walk-forward backtesting: temporal split + commune calibration + OLS benchmark.",
)
def backtest_flow() -> dict:
    """
    Standalone backtesting flow for model validation.
    Runs temporal walk-forward split, commune calibration, and OLS benchmark.
    Reports are saved to data/exports/.
    """
    logger = get_run_logger()
    logger.info("=== Backtest Flow START ===")
    result = task_backtesting()
    logger.info(f"=== Backtest Flow DONE: {result} ===")
    return result


# ── Daily scrape + score + alert (scheduled) ──────────────────────────────────

@flow(
    name="RE_CL Daily Scrape + Alert",
    description="Scrape fresh listings, re-score scraped data, fire alerts. Designed to run daily at 06:00.",
)
def daily_scrape_and_alert(
    max_pages: int = 100,
    sources: list = None,
    alert_threshold: float = None,
    dry_run: bool = False,
) -> dict:
    """
    Lightweight daily flow for personal use:
      1. Scrape portal + toctoc
      2. Re-score scraped listings
      3. Run alert notifier (only new properties since last run)

    Recommended cron: "0 6 * * *"  (every day at 06:00)
    """
    logger = get_run_logger()
    if sources is None:
        sources = ["portal", "toctoc"]

    logger.info(f"=== Daily Scrape + Alert START (sources={sources}, max_pages={max_pages}) ===")

    results = {}

    if "portal" in sources:
        results["n_portal"] = task_scrape_portal(max_pages=max_pages)

    if "toctoc" in sources:
        results["n_toctoc"] = task_scrape_toctoc(max_pages=max_pages)

    # Re-score only scraped listings (skips CBR retraining)
    task_score(dry_run=dry_run)
    task_commune_ranking(dry_run=dry_run)
    task_heatmap()

    # Fire alerts for newly scored high-opportunity properties
    results["n_alerts"] = task_run_alerts(
        threshold=alert_threshold,
        last_hours=25,   # only properties scored in the last ~day
        dry_run=dry_run,
    )

    logger.info(f"=== Daily Scrape + Alert DONE: {results} ===")
    return results


# ── GTFS refresh flow (V6) ────────────────────────────────────────────────────

@flow(
    name="RE_CL GTFS Refresh",
    description="Fetch DTPM GTFS bus stops and update dist_gtfs_bus_km. Runs weekly on Monday at 07:00.",
)
def gtfs_refresh_flow() -> dict:
    """Standalone GTFS enrichment flow for scheduled weekly refresh."""
    logger = get_run_logger()
    logger.info("=== GTFS Refresh Flow START ===")
    result = task_gtfs_enrichment()
    logger.info(f"=== GTFS Refresh Flow DONE: {result} ===")
    return result


# ── Data Inmobiliaria daily flow (CBR 2019-present) ──────────────────────────

@flow(
    name="RE_CL DataInmobiliaria Daily",
    description="Scrape next unscraped RM commune from datainmobiliaria.cl (CBR ventas 2019+). "
                "Guest: 1 commune/day (~15k records). With credentials: all 40 communes in one run. "
                "Scheduled daily at 01:00 — runs 40 nights to complete full RM coverage.",
)
def datainmobiliaria_daily_flow(
    min_year: int = 2019,
    max_pages: int = 100,
    dry_run: bool = False,
) -> dict:
    """
    Picks next unscraped commune from checkpoint → scrapes → saves to transactions_raw.
    After all 40 communes done, triggers re-clean + retrain.
    """
    import asyncio
    from sqlalchemy import create_engine, text

    logger = get_run_logger()

    def _build_db_url():
        url = os.getenv("DATABASE_URL")
        if url:
            return url
        return (
            f"postgresql://{os.getenv('POSTGRES_USER','re_cl_user')}:"
            f"{os.getenv('POSTGRES_PASSWORD','')}@"
            f"{os.getenv('POSTGRES_HOST','localhost')}:"
            f"{os.getenv('POSTGRES_PORT','5432')}/"
            f"{os.getenv('POSTGRES_DB','re_cl')}"
        )

    from src.scraping.datainmobiliaria import (
        _next_unscraped_commune,
        _load_checkpoint,
        RM_COMMUNE_POLYGONS,
        scrape_all,
    )

    next_c = _next_unscraped_commune()
    if next_c is None:
        cp = _load_checkpoint()
        total_rows = sum(v.get("rows", 0) for v in cp.values())
        logger.info(f"All {len(RM_COMMUNE_POLYGONS)} communes already scraped ({total_rows} total rows). Nothing to do.")
        return {"status": "complete", "communes_done": len(cp), "total_rows": total_rows}

    cp = _load_checkpoint()
    logger.info(f"Next commune: {next_c} ({len(cp)}/{len(RM_COMMUNE_POLYGONS)} done so far)")

    engine = create_engine(_build_db_url(), pool_pre_ping=True)
    rows_written = asyncio.run(scrape_all(
        engine,
        communes=[next_c],
        fuente="ventas",
        dry_run=dry_run,
        max_pages=max_pages,
        min_year=min_year,
        headless=True,
        use_checkpoint=True,
    ))

    cp_after = _load_checkpoint()
    result = {
        "commune": next_c,
        "rows_written": rows_written,
        "communes_done": len(cp_after),
        "communes_total": len(RM_COMMUNE_POLYGONS),
    }

    if len(cp_after) == len(RM_COMMUNE_POLYGONS):
        logger.info("All communes scraped! Consider running full retrain pipeline.")
        result["all_done"] = True

    return result


# ── Phase 9: Parallel scrape flow ─────────────────────────────────────────────

@flow(
    name="RE_CL Parallel Scrape",
    description=(
        "Phase 9: Parallel scraping across 3 sources. "
        "PI (40 communes × 4 types in batches) + Toctoc (4 types concurrent) run "
        "CONCURRENTLY via ThreadPoolExecutor. Then DI (next unscraped commune, "
        "saved cookies) → normalize_county → score. Each PI/Toctoc thread owns "
        "its own asyncio event loop (required since asyncio.run can't be nested)."
    ),
)
def parallel_scrape_flow(
    pi_batch_size: int = 6,
    pi_max_pages: int = 1,
    toctoc_max_pages: int = 50,
    di_min_year: int = 2019,
    di_max_pages: int = 100,
    skip_di: bool = False,
    dry_run: bool = False,
) -> dict:
    """Full parallel scrape pipeline.

    Execution order:
      1. PI + Toctoc CONCURRENTLY (ThreadPoolExecutor, max_workers=2).
         Each worker thread invokes the Prefect task which internally runs
         asyncio.run(run_parallel(...)). Two separate threads = two separate
         event loops = safe concurrent Playwright Chromium instances.
      2. DI sequential (quota-sensitive: ~15k records/IP/day guest limit).
      3. normalize_county + score_scraped (DB-only post-processing).
    """
    logger = get_run_logger()
    logger.info(
        f"=== Parallel Scrape START (pi_batch={pi_batch_size}, "
        f"toctoc_pages={toctoc_max_pages}, skip_di={skip_di}, dry_run={dry_run}) ==="
    )

    results = {}

    # Stage 1: PI + Toctoc concurrent via two-thread pool.
    # Why: asyncio.gather() can't host two independent asyncio.run() calls in
    # the same thread — each Playwright scraper already uses asyncio.run()
    # internally (see portal_inmobiliario.run_parallel / toctoc.run_parallel).
    # ThreadPoolExecutor gives each scraper its own thread + event loop.
    logger.info("[Stage 1] Submitting PI + Toctoc to ThreadPoolExecutor(max_workers=2)")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        pi_future = executor.submit(
            task_scrape_pi_parallel,
            batch_size=pi_batch_size,
            max_pages=pi_max_pages,
        )
        tt_future = executor.submit(
            task_scrape_toctoc_parallel,
            max_pages=toctoc_max_pages,
        )
        # Block until both complete. .result() propagates exceptions.
        results["n_pi"] = pi_future.result()
        results["n_toctoc"] = tt_future.result()
    logger.info(
        f"[Stage 1] Done — PI={results['n_pi']}, Toctoc={results['n_toctoc']}"
    )

    # Stage 2: DI sequential (guest quota — do not parallelize with PI/Toctoc,
    # same IP would look bot-like to DI anti-fraud, and quota accounting is
    # per-IP per-day).
    if skip_di:
        logger.info("[Stage 2] Skipping DataInmobiliaria (skip_di=True)")
        results["di"] = {"skipped": True}
    else:
        results["di"] = task_scrape_di_next_commune(
            min_year=di_min_year, max_pages=di_max_pages, dry_run=dry_run,
        )

    # Stage 3: Post-processing (DB-only, fast).
    results["normalize"] = task_normalize_county(dry_run=dry_run)
    results["score"] = task_score_scraped(dry_run=dry_run)

    logger.info(f"=== Parallel Scrape DONE: {results} ===")
    return results


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RE_CL Pipeline Runner")
    parser.add_argument(
        "--flow",
        choices=["full", "scoring_only", "maps_only", "scraping", "daily", "backtest", "gtfs_refresh", "datainmobiliaria", "parallel"],
        default="full",
    )
    parser.add_argument("--csv-path",        type=str,  default=None)
    parser.add_argument("--dry-run",         action="store_true")
    parser.add_argument("--no-retrain",      action="store_true")
    parser.add_argument("--skip-osm",        action="store_true", help="Skip OSM enrichment (use when offline)")
    parser.add_argument("--skip-gtfs",       action="store_true", help="Skip GTFS bus-stop enrichment (V6)")
    parser.add_argument("--max-pages",       type=int,  default=50)
    parser.add_argument("--sources",         nargs="+", default=["portal", "toctoc"])
    parser.add_argument("--skip-di",         action="store_true", help="Skip DataInmobiliaria in parallel flow")
    parser.add_argument("--batch-size",      type=int,  default=6,  help="PI parallel batch size (Phase 9)")
    parser.add_argument("--max-pages-toctoc", type=int, default=50, help="Toctoc pages per type (Phase 9)")
    args = parser.parse_args()

    if args.flow == "full":
        full_pipeline(
            csv_path=args.csv_path,
            dry_run=args.dry_run,
            retrain=not args.no_retrain,
            skip_osm=args.skip_osm,
            skip_gtfs=args.skip_gtfs,
        )
    elif args.flow == "scoring_only":
        scoring_only(dry_run=args.dry_run)
    elif args.flow == "maps_only":
        maps_only(dry_run=args.dry_run)
    elif args.flow == "scraping":
        scraping_flow(
            max_pages=args.max_pages,
            dry_run=args.dry_run,
            sources=args.sources,
        )
    elif args.flow == "daily":
        daily_scrape_and_alert(
            max_pages=args.max_pages,
            dry_run=args.dry_run,
            sources=args.sources,
        )
    elif args.flow == "backtest":
        backtest_flow()
    elif args.flow == "gtfs_refresh":
        gtfs_refresh_flow()
    elif args.flow == "datainmobiliaria":
        datainmobiliaria_daily_flow(dry_run=args.dry_run)
    elif args.flow == "parallel":
        parallel_scrape_flow(
            pi_batch_size=args.batch_size,
            toctoc_max_pages=args.max_pages_toctoc,
            skip_di=args.skip_di,
            dry_run=args.dry_run,
        )
