"""
deploy.py
---------
Register RE_CL Prefect deployments with schedules.

Deployments:
  - daily-scrape-and-alert   → runs every day at 06:00 (scraping + scoring + alerts)
  - weekly-full-pipeline     → runs every Sunday at 03:00 (full retrain + maps)
  - weekly-backtesting       → runs every Sunday at 04:00 (walk-forward backtest)
  - post-pipeline-validation → runs every Sunday at 05:30 (data quality validation)

Usage:
    # Start a local Prefect server first:
    prefect server start

    # Then in another terminal:
    python src/pipelines/deploy.py

    # Start a Prefect worker to execute runs:
    prefect worker start --pool default-agent-pool
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from prefect import flow
from prefect.deployments import Deployment
from prefect.logging import get_run_logger
from prefect.server.schemas.schedules import CronSchedule

from src.pipelines.flows import daily_scrape_and_alert, full_pipeline, backtest_flow, gtfs_refresh_flow


# ── Validation flow ───────────────────────────────────────────────────────────

@flow(
    name="RE_CL Validation",
    description="Run data quality validation after pipeline completes.",
)
def validation_flow() -> bool:
    """Run data quality validation after pipeline."""
    logger = get_run_logger()
    result = subprocess.run(
        [sys.executable, "scripts/validate_data.py", "--json", "--exit-code"],
        capture_output=True,
        text=True,
    )
    logger.info(result.stdout)
    if result.returncode != 0:
        logger.warning(
            "Data validation FAILED — check data/exports/validation_report.json"
        )
    return result.returncode == 0


def deploy_all() -> None:
    # ── Daily: scrape + score + alert ────────────────────────────────────────
    daily = Deployment.build_from_flow(
        flow=daily_scrape_and_alert,
        name="daily-scrape-and-alert",
        schedule=CronSchedule(cron="0 6 * * *", timezone="America/Santiago"),
        parameters={
            "max_pages": 100,
            "sources": ["portal", "toctoc"],
            "dry_run": False,
        },
        description="Scrape fresh listings, re-score, and fire alerts. Runs daily at 06:00 Santiago time.",
        tags=["re_cl", "daily", "scraping", "alerts"],
    )
    daily_id = daily.apply()
    print(f"[OK] daily-scrape-and-alert deployed: {daily_id}")

    # ── Weekly: full retrain + maps ───────────────────────────────────────────
    weekly = Deployment.build_from_flow(
        flow=full_pipeline,
        name="weekly-full-pipeline",
        schedule=CronSchedule(cron="0 3 * * 0", timezone="America/Santiago"),
        parameters={
            "dry_run": False,
            "retrain": True,
        },
        description="Full pipeline: ingest → clean → features → retrain → score → maps. Runs every Sunday at 03:00.",
        tags=["re_cl", "weekly", "full-pipeline"],
    )
    weekly_id = weekly.apply()
    print(f"[OK] weekly-full-pipeline deployed: {weekly_id}")

    # ── Weekly: backtesting validation (V4.5) ────────────────────────────────
    backtest = Deployment.build_from_flow(
        flow=backtest_flow,
        name="weekly-backtesting",
        schedule=CronSchedule(cron="0 4 * * 0", timezone="America/Santiago"),
        parameters={},
        description="Walk-forward backtesting: temporal split + commune calibration + OLS benchmark. Runs every Sunday at 04:00.",
        tags=["re_cl", "weekly", "backtesting", "v4"],
    )
    backtest_id = backtest.apply()
    print(f"[OK] weekly-backtesting deployed: {backtest_id}")

    # ── Weekly: post-pipeline data quality validation ─────────────────────────
    validation = Deployment.build_from_flow(
        flow=validation_flow,
        name="post-pipeline-validation",
        schedule=CronSchedule(cron="30 5 * * 0", timezone="America/Santiago"),
        parameters={},
        description="Data quality validation after weekly pipeline. Runs every Sunday at 05:30.",
        tags=["re_cl", "weekly", "validation"],
    )
    validation_id = validation.apply()
    print(f"[OK] post-pipeline-validation deployed: {validation_id}")

    # ── Weekly: GTFS bus-stop refresh (V6) ───────────────────────────────────
    gtfs = Deployment.build_from_flow(
        flow=gtfs_refresh_flow,
        name="gtfs-weekly-refresh",
        schedule=CronSchedule(cron="0 7 * * 1", timezone="America/Santiago"),
        parameters={},
        description="Fetch DTPM GTFS bus stops and update dist_gtfs_bus_km. Runs every Monday at 07:00.",
        tags=["re_cl", "weekly", "gtfs", "v6"],
    )
    gtfs_id = gtfs.apply()
    print(f"[OK] gtfs-weekly-refresh deployed: {gtfs_id}")

    print("\nDeployments registered. Start a worker to execute runs:")
    print("  prefect worker start --pool default-agent-pool")
    print("\nOr trigger a manual run:")
    print("  prefect deployment run 'RE_CL Daily Scrape + Alert/daily-scrape-and-alert'")
    print("  prefect deployment run 'RE_CL Full Pipeline/weekly-full-pipeline'")
    print("  prefect deployment run 'RE_CL Backtest/weekly-backtesting'")
    print("  prefect deployment run 'RE_CL Validation/post-pipeline-validation'")
    print("  prefect deployment run 'RE_CL GTFS Refresh/gtfs-weekly-refresh'")


if __name__ == "__main__":
    deploy_all()
