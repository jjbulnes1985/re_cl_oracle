"""
tasks.py
--------
Prefect task wrappers for each RE_CL pipeline step.

Each task wraps an existing module's main() or run() function,
adding Prefect retries, logging, and result caching.
"""

import os
import sys
from pathlib import Path

from prefect import task
from prefect.logging import get_run_logger
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


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


def _build_scraper_engine():
    """Build a SQLAlchemy engine sized for parallel scraper writes.

    Default SQLAlchemy pool is 5 — too small for >=6 concurrent coroutines
    hitting _write_batch() via engine.begin(). Use pool_size=10 + overflow=5.
    """
    return create_engine(
        _build_db_url(),
        pool_size=10,
        max_overflow=5,
        pool_timeout=30,
        pool_pre_ping=True,
    )


# ── Ingestion ──────────────────────────────────────────────────────────────────

@task(name="load-transactions", retries=2, retry_delay_seconds=30)
def task_load_transactions(csv_path: str = None) -> int:
    """Load raw CSV into transactions_raw table."""
    logger = get_run_logger()
    from src.ingestion.load_transactions import load_csv, write_to_db, update_geom
    from dotenv import load_dotenv
    load_dotenv()

    engine = create_engine(_build_db_url(), pool_pre_ping=True)
    path   = csv_path or os.getenv("RAW_CSV_PATH")
    if not path:
        raise ValueError("RAW_CSV_PATH not set and no csv_path provided")

    logger.info(f"Loading CSV from {path}")
    n = load_csv(path, engine)
    update_geom(engine)
    logger.info(f"Loaded {n:,} rows into transactions_raw")
    return n


@task(name="clean-transactions", retries=1)
def task_clean_transactions(dry_run: bool = False) -> int:
    """Clean and normalize transactions_raw → transactions_clean."""
    logger = get_run_logger()
    from src.ingestion.clean_transactions import main as clean_main
    from dotenv import load_dotenv
    load_dotenv()

    logger.info("Running clean_transactions...")
    n = clean_main(dry_run=dry_run)
    logger.info(f"clean_transactions done: {n} rows written")
    return n or 0


# ── Feature Engineering ───────────────────────────────────────────────────────

@task(name="build-features", retries=1)
def task_build_features(dry_run: bool = False) -> int:
    """Compute price, spatial, and temporal features → transaction_features."""
    logger = get_run_logger()
    from src.features.build_features import main as features_main
    from dotenv import load_dotenv
    load_dotenv()

    logger.info("Building features...")
    n = features_main(dry_run=dry_run)
    logger.info(f"Features built: {n} rows")
    return n or 0


# ── Model Training ────────────────────────────────────────────────────────────

@task(name="train-hedonic-model", retries=0)
def task_train_model() -> dict:
    """Train XGBoost hedonic model and save to disk. Returns metrics dict."""
    logger = get_run_logger()
    from src.models.hedonic_model import train, load_training_data, save_model
    from dotenv import load_dotenv
    load_dotenv()

    engine = create_engine(_build_db_url(), pool_pre_ping=True)
    logger.info("Loading training data...")
    df = load_training_data(engine)
    logger.info(f"Training model on {len(df):,} rows...")
    model, encoders, metrics = train(df)
    save_model(model, encoders, metrics)
    logger.info(f"Model trained. RMSE: {metrics.get('rmse_pct_of_median', 'N/A')}%")
    return metrics


# ── Scoring ───────────────────────────────────────────────────────────────────

@task(name="compute-opportunity-scores", retries=1)
def task_score(dry_run: bool = False) -> int:
    """Compute opportunity scores → model_scores table."""
    logger = get_run_logger()
    from src.scoring.opportunity_score import main as score_main
    from dotenv import load_dotenv
    load_dotenv()

    logger.info("Computing opportunity scores...")
    score_main(dry_run=dry_run)
    return 0


# ── Maps & Rankings ───────────────────────────────────────────────────────────

@task(name="compute-commune-ranking", retries=1)
def task_commune_ranking(dry_run: bool = False) -> int:
    """Compute commune statistics → commune_stats table."""
    logger = get_run_logger()
    from src.maps.commune_ranking import main as ranking_main
    from dotenv import load_dotenv
    load_dotenv()

    logger.info("Computing commune ranking...")
    ranking_main(dry_run=dry_run)
    return 0


@task(name="generate-heatmap", retries=1)
def task_heatmap(output: str = None) -> str:
    """Generate Folium heatmap HTML."""
    logger = get_run_logger()
    from src.maps.heatmap import main as heatmap_main
    from dotenv import load_dotenv
    load_dotenv()

    logger.info("Generating heatmap...")
    heatmap_main(output=output)
    model_version = os.getenv("MODEL_VERSION", "v1.0")
    exports_dir   = os.getenv("EXPORTS_DIR", "data/exports")
    out = output or f"{exports_dir}/heatmap_{model_version}.html"
    logger.info(f"Heatmap saved: {out}")
    return out


# ── Scraping (V2) ─────────────────────────────────────────────────────────────

@task(name="scrape-portal-inmobiliario", retries=3, retry_delay_seconds=60)
def task_scrape_portal(max_pages: int = 50) -> int:
    """Scrape Portal Inmobiliario and write to scraped_listings table."""
    logger = get_run_logger()
    from src.scraping.portal_inmobiliario import run as scrape_run
    from dotenv import load_dotenv
    load_dotenv()

    engine = _build_scraper_engine()
    logger.info(f"Scraping Portal Inmobiliario (max_pages={max_pages})...")
    n = scrape_run(engine=engine, max_pages=max_pages)
    logger.info(f"Scraped {n:,} listings")
    return n


@task(name="scrape-toctoc", retries=3, retry_delay_seconds=60)
def task_scrape_toctoc(max_pages: int = 50) -> int:
    """Scrape Toctoc.com and write to scraped_listings table."""
    logger = get_run_logger()
    from src.scraping.toctoc import run as scrape_run
    from dotenv import load_dotenv
    load_dotenv()

    engine = _build_scraper_engine()
    logger.info(f"Scraping Toctoc (max_pages={max_pages})...")
    n = scrape_run(engine=engine, max_pages=max_pages)
    logger.info(f"Scraped {n:,} listings")
    return n


# ── OSM Enrichment (V4.2) ─────────────────────────────────────────────────────

@task(name="osm-enrichment", retries=2, retry_delay_seconds=60)
def task_osm_enrichment(skip_osm: bool = False) -> dict:
    """Enrich transaction_features with OSM/Metro proximity features."""
    logger = get_run_logger()
    from dotenv import load_dotenv
    load_dotenv()

    if skip_osm:
        logger.info("Skipping OSM enrichment (skip_osm=True)")
        return {"skipped": True}

    from src.features import osm_features

    engine = create_engine(_build_db_url(), pool_pre_ping=True)
    logger.info("Running OSM enrichment (Overpass API)...")
    df = osm_features.run(engine=engine)
    n = len(df)
    logger.info(f"OSM enrichment done: {n} rows updated")
    return {"rows": n}


# ── GTFS Enrichment (V6) ─────────────────────────────────────────────────────

@task(name="gtfs-enrichment", retries=1, retry_delay_seconds=60)
def task_gtfs_enrichment() -> dict:
    """Fetch DTPM GTFS bus stops and compute dist_gtfs_bus_km."""
    logger = get_run_logger()
    try:
        from src.features import gtfs_features
        gtfs_features.run()
        logger.info("GTFS enrichment complete")
        return {"skipped": False}
    except Exception as e:
        logger.warning(f"GTFS enrichment skipped: {e}")
        return {"skipped": True, "reason": str(e)}


# ── Webhook Notification (V6) ─────────────────────────────────────────────────

@task(name="webhook-notify")
def task_webhook_notify(event: str, count: int = 0) -> None:
    """Post a pipeline completion event to the configured webhook URL."""
    import os
    import requests
    url = os.getenv("ALERT_WEBHOOK_URL", "")
    if not url:
        return
    try:
        requests.post(url, json={
            "event": event,
            "count": count,
            "source": "re_cl_prefect",
            "timestamp": __import__("datetime").datetime.utcnow().isoformat()
        }, timeout=5)
    except Exception:
        pass


# ── Backtesting (V4.5) ────────────────────────────────────────────────────────

@task(name="backtesting-validation", retries=1)
def task_backtesting() -> dict:
    """Run walk-forward backtesting and save reports to data/exports/."""
    logger = get_run_logger()
    from dotenv import load_dotenv
    load_dotenv()

    from src.backtesting.walk_forward import (
        run_temporal_split,
        run_commune_calibration,
        run_ols_benchmark,
    )

    engine = create_engine(_build_db_url(), pool_pre_ping=True)
    logger.info("Running temporal walk-forward split...")
    temporal = run_temporal_split(engine)

    logger.info("Running commune calibration...")
    calibration = run_commune_calibration(engine)

    logger.info("Running OLS benchmark...")
    run_ols_benchmark(engine)

    result = {
        "temporal_r2": temporal.get("r2") if temporal else None,
        "calibration_communes": len(calibration) if calibration is not None else 0,
    }
    logger.info(f"Backtesting complete: {result}")
    return result


# ── Phase 9: Parallel scraping tasks ──────────────────────────────────────────

@task(name="scrape-pi-parallel", retries=2, retry_delay_seconds=60)
def task_scrape_pi_parallel(batch_size: int = 6, max_pages: int = 1) -> int:
    """Run Portal Inmobiliario parallel scrape (40 communes × 4 types in batches)."""
    logger = get_run_logger()
    # Import the MODULE (not the symbol) so monkeypatch.setattr on
    # src.scraping.portal_inmobiliario.run_parallel is observed by this task.
    import src.scraping.portal_inmobiliario as pi_mod
    from dotenv import load_dotenv
    load_dotenv()
    engine = _build_scraper_engine()
    logger.info(f"[PI-parallel] batch_size={batch_size}, max_pages={max_pages}")
    n = pi_mod.run_parallel(engine=engine, batch_size=batch_size, max_pages=max_pages)
    logger.info(f"[PI-parallel] Wrote {n:,} listings")
    return n


@task(name="scrape-toctoc-parallel", retries=2, retry_delay_seconds=60)
def task_scrape_toctoc_parallel(max_pages: int = 50) -> int:
    """Run Toctoc parallel scrape (4 property types concurrently)."""
    logger = get_run_logger()
    # Module-level import — same reason as PI task (monkeypatch compatibility).
    import src.scraping.toctoc as tt_mod
    from dotenv import load_dotenv
    load_dotenv()
    engine = _build_scraper_engine()
    logger.info(f"[Toctoc-parallel] max_pages={max_pages}")
    n = tt_mod.run_parallel(engine=engine, max_pages=max_pages)
    logger.info(f"[Toctoc-parallel] Wrote {n:,} listings")
    return n


@task(name="scrape-di-next-commune", retries=1, retry_delay_seconds=120)
def task_scrape_di_next_commune(
    min_year: int = 2019,
    max_pages: int = 100,
    dry_run: bool = False,
) -> dict:
    """Scrape next unscraped RM commune from datainmobiliaria.cl using saved cookies.

    Uses data/processed/datainmobiliaria_cookies.json (must be created once
    manually via: py src/scraping/datainmobiliaria.py --manual-login).
    Guest quota: ~15k records/IP/day → schedule daily.
    """
    logger = get_run_logger()
    import asyncio as _asyncio
    import src.scraping.datainmobiliaria as di_mod
    from dotenv import load_dotenv
    load_dotenv()

    next_c = di_mod._next_unscraped_commune()
    if next_c is None:
        cp = di_mod._load_checkpoint()
        total_rows = sum(v.get("rows", 0) for v in cp.values())
        logger.info(f"[DI] All {len(di_mod.RM_COMMUNE_POLYGONS)} communes done ({total_rows} rows total).")
        return {"status": "complete", "communes_done": len(cp), "total_rows": total_rows}

    engine = _build_scraper_engine()
    cp = di_mod._load_checkpoint()
    logger.info(f"[DI] Scraping {next_c} ({len(cp)}/{len(di_mod.RM_COMMUNE_POLYGONS)} done)")

    try:
        rows_written = _asyncio.run(di_mod.scrape_all(
            engine,
            communes=[next_c],
            fuente="ventas",
            dry_run=dry_run,
            max_pages=max_pages,
            min_year=min_year,
            headless=True,
            use_checkpoint=True,
            check_quota_only=False,
            manual_login=False,   # rely on saved cookies; never block for interactive login
        ))
    except Exception as e:
        logger.warning(f"[DI] {next_c} failed: {e}")
        return {"commune": next_c, "rows_written": 0, "error": str(e)}

    cp_after = di_mod._load_checkpoint()
    return {
        "commune": next_c,
        "rows_written": rows_written,
        "communes_done": len(cp_after),
        "communes_total": len(di_mod.RM_COMMUNE_POLYGONS),
    }


@task(name="normalize-county", retries=1, retry_delay_seconds=30)
def task_normalize_county(dry_run: bool = False, min_score: int = 85):
    """Fuzzy-normalize county_name in scraped_listings to canonical RM communes."""
    logger = get_run_logger()
    import inspect
    import src.ingestion.normalize_county as nc_mod
    from dotenv import load_dotenv
    load_dotenv()
    engine = _build_scraper_engine()
    logger.info(f"[normalize_county] dry_run={dry_run} min_score={min_score}")
    sig = inspect.signature(nc_mod.normalize_county)
    kwargs = {}
    if "dry_run" in sig.parameters:
        kwargs["dry_run"] = dry_run
    if "min_score" in sig.parameters:
        kwargs["min_score"] = min_score
    result = nc_mod.normalize_county(engine, **kwargs)
    logger.info(f"[normalize_county] result: {result}")
    return result


@task(name="score-scraped-listings", retries=1, retry_delay_seconds=30)
def task_score_scraped(dry_run: bool = False):
    """Score scraped_listings via the hedonic model → model_scores."""
    logger = get_run_logger()
    import inspect
    import src.scoring.scraped_to_scored as sts_mod
    from dotenv import load_dotenv
    load_dotenv()
    logger.info(f"[score_scraped] dry_run={dry_run}")
    sig = inspect.signature(sts_mod.main)
    kwargs = {}
    if "dry_run" in sig.parameters:
        kwargs["dry_run"] = dry_run
    result = sts_mod.main(**kwargs)
    logger.info(f"[score_scraped] result: {result}")
    return result


# ── Alerts ────────────────────────────────────────────────────────────────────

@task(name="run-alerts", retries=1)
def task_run_alerts(
    threshold: float = None,
    last_hours: int = None,
    dry_run: bool = False,
) -> int:
    """
    Run the alert notifier: detect high-opportunity properties and
    notify via console + JSON + email (if configured).
    Returns number of new alerts fired.
    """
    logger = get_run_logger()
    from src.alerts.notifier import main as alert_main
    from dotenv import load_dotenv
    load_dotenv()

    logger.info(f"Running alert notifier (threshold={threshold}, last_hours={last_hours})...")
    n = alert_main(dry_run=dry_run, threshold=threshold, last_hours=last_hours)
    logger.info(f"Alerts fired: {n}")
    return n
