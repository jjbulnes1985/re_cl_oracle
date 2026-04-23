#!/usr/bin/env python3
"""
setup_pipeline.py
-----------------
Complete RE_CL pipeline setup from zero to running system.

Usage:
    python scripts/setup_pipeline.py                    # full setup
    python scripts/setup_pipeline.py --skip-data        # skip CSV ingestion
    python scripts/setup_pipeline.py --skip-osm         # skip OSM enrichment
    python scripts/setup_pipeline.py --skip-gtfs        # skip GTFS bus-stop enrichment (V6)
    python scripts/setup_pipeline.py --skip-model       # skip model training
    python scripts/setup_pipeline.py --skip-backtest    # skip backtesting
    python scripts/setup_pipeline.py --dry-run          # preview steps only
    python scripts/setup_pipeline.py --from-step 3      # resume from step N
    python scripts/setup_pipeline.py --help             # show this help
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# This script lives at re_cl/scripts/setup_pipeline.py
# REPO_DIR = re_cl/
REPO_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_DIR / "src"
DB_DIR = REPO_DIR / "db"
MODELS_DIR = REPO_DIR / "models"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_banner(step_num: int, name: str) -> None:
    width = 62
    print(f"\n{'=' * width}")
    print(f"  STEP {step_num}: {name}")
    print(f"{'=' * width}")


def run_step(
    step_num: int,
    name: str,
    cmd: "list[str]",
    cwd: "Path | None" = None,
    skip: bool = False,
    dry_run: bool = False,
    env: "dict | None" = None,
) -> bool:
    """Execute one pipeline step. Returns True on success."""
    if skip:
        print(f"\n[{step_num}] SKIP  {name}")
        return True

    _print_banner(step_num, name)

    if dry_run:
        print(f"  DRY-RUN cmd : {' '.join(str(c) for c in cmd)}")
        print(f"  DRY-RUN cwd : {cwd or REPO_DIR}")
        print(f"[{step_num}] DRY-RUN OK")
        return True

    t0 = time.perf_counter()
    run_env = {**os.environ, **(env or {})}
    result = subprocess.run(
        cmd,
        cwd=str(cwd or REPO_DIR),
        env=run_env,
    )
    elapsed = time.perf_counter() - t0

    if result.returncode != 0:
        print(f"\n[{step_num}] FAILED after {elapsed:.1f}s  (exit code {result.returncode})")
        return False

    print(f"\n[{step_num}] OK ({elapsed:.1f}s)")
    return True


# ---------------------------------------------------------------------------
# Step 1 -- Validate environment
# ---------------------------------------------------------------------------

def step_validate_env(dry_run: bool) -> bool:
    """Check .env exists and DB is reachable."""
    _print_banner(1, "Validate environment")

    env_path = REPO_DIR / ".env"
    if not env_path.exists():
        print(
            "ERROR: .env not found.\n"
            f"  Expected: {env_path}\n"
            "  Copy .env.example and fill in values, then re-run."
        )
        return False
    print(f"  .env found: {env_path}")

    if dry_run:
        print("  DRY-RUN: skipping DB connection check")
        print("[1] DRY-RUN OK")
        return True

    # Try DB connection
    try:
        from dotenv import load_dotenv
        from sqlalchemy import create_engine, text

        load_dotenv(env_path, override=False)

        url = os.getenv("DATABASE_URL") or (
            "postgresql://{user}:{pw}@{host}:{port}/{db}".format(
                user=os.getenv("POSTGRES_USER", "re_cl"),
                pw=os.getenv("POSTGRES_PASSWORD", ""),
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=os.getenv("POSTGRES_PORT", "5432"),
                db=os.getenv("POSTGRES_DB", "re_cl"),
            )
        )

        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        print("  DB connection OK")
    except ImportError as exc:
        print(f"ERROR: missing Python package -- {exc}")
        print("  Run: pip install -r requirements.txt")
        return False
    except Exception as exc:
        print(f"ERROR: DB connection failed -- {exc}")
        print("  Start Docker first: cd re_cl && docker-compose up -d")
        return False

    print("[1] OK")
    return True


# ---------------------------------------------------------------------------
# Step 2 -- Apply DB migrations
# ---------------------------------------------------------------------------

def _psql_available() -> bool:
    """Return True if native psql is in PATH."""
    try:
        probe = subprocess.run(
            ["psql", "--version"],
            capture_output=True,
        )
        return probe.returncode == 0
    except FileNotFoundError:
        return False


def step_apply_migrations(dry_run: bool) -> bool:
    """Apply schema.sql + all migrations in db/migrations/ in sorted order."""
    _print_banner(2, "Apply DB migrations")

    migration_dir = DB_DIR / "migrations"
    if not migration_dir.exists():
        print(f"  WARNING: migrations dir not found: {migration_dir} -- skipping")
        print("[2] OK (no migrations)")
        return True

    migrations = sorted(migration_dir.glob("*.sql"))
    if not migrations:
        print("  No .sql files found in migrations/ -- skipping")
        print("[2] OK (no migrations)")
        return True

    # Apply base schema first, then numbered migrations
    schema_file = DB_DIR / "schema.sql"
    all_files = ([schema_file] if schema_file.exists() else []) + list(migrations)

    if dry_run:
        for sql_file in all_files:
            print(f"  DRY-RUN: would apply {sql_file.name}")
        print("[2] DRY-RUN OK")
        return True

    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_DIR / ".env", override=False)
    except ImportError:
        pass  # already loaded by step 1, or not installed

    user = os.getenv("POSTGRES_USER", "re_cl")
    db = os.getenv("POSTGRES_DB", "re_cl")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    password = os.getenv("POSTGRES_PASSWORD", "")

    use_native_psql = _psql_available()
    if use_native_psql:
        print("  Using native psql")
    else:
        print("  psql not in PATH -- using docker exec fallback (container: re_cl_db)")

    for sql_file in all_files:
        print(f"  Applying {sql_file.name} ...")

        if use_native_psql:
            cmd = [
                "psql",
                "-U", user,
                "-d", db,
                "-h", host,
                "-p", port,
                "-f", str(sql_file),
            ]
            env = {**os.environ, "PGPASSWORD": password}
            result = subprocess.run(cmd, env=env)
        else:
            # Docker exec fallback -- pipe SQL via stdin
            docker_cmd = [
                "docker", "exec", "-i", "re_cl_db",
                "psql", "-U", user, "-d", db,
            ]
            with open(sql_file, "rb") as fh:
                result = subprocess.run(docker_cmd, stdin=fh)

        if result.returncode != 0:
            print(f"  ERROR: {sql_file.name} failed (exit {result.returncode})")
            return False
        print(f"    {sql_file.name} OK")

    print("[2] OK")
    return True


# ---------------------------------------------------------------------------
# Step 10 -- Summary report
# ---------------------------------------------------------------------------

def step_summary(dry_run: bool) -> bool:
    """Query row counts from each key table and print a summary."""
    _print_banner(10, "Summary report")

    if dry_run:
        print("  DRY-RUN: would query row counts from all tables")
        print("[10] DRY-RUN OK")
        return True

    try:
        from dotenv import load_dotenv
        from sqlalchemy import create_engine, text

        load_dotenv(REPO_DIR / ".env", override=False)

        url = os.getenv("DATABASE_URL") or (
            "postgresql://{user}:{pw}@{host}:{port}/{db}".format(
                user=os.getenv("POSTGRES_USER", "re_cl"),
                pw=os.getenv("POSTGRES_PASSWORD", ""),
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=os.getenv("POSTGRES_PORT", "5432"),
                db=os.getenv("POSTGRES_DB", "re_cl"),
            )
        )
        engine = create_engine(url)

        tables = [
            "transactions_raw",
            "transactions_clean",
            "transaction_features",
            "model_scores",
            "scraped_listings",
        ]
        views = ["v_opportunities", "v_scraped_market"]

        print(f"\n  {'Table / View':<30}  {'Rows':>12}")
        print(f"  {'-'*30}  {'-'*12}")

        with engine.connect() as conn:
            for obj in tables + views:
                try:
                    row = conn.execute(
                        text(f"SELECT COUNT(*) FROM {obj}")
                    ).scalar()
                    print(f"  {obj:<30}  {row:>12,}")
                except Exception:
                    print(f"  {obj:<30}  {'(not found)':>12}")

            # Model metrics breakdown by version
            try:
                rows = conn.execute(
                    text(
                        "SELECT model_version, COUNT(*) AS n, "
                        "ROUND(AVG(opportunity_score)::numeric, 3) AS avg_score "
                        "FROM model_scores "
                        "GROUP BY model_version "
                        "ORDER BY model_version"
                    )
                ).fetchall()
                if rows:
                    print(f"\n  {'Model version':<25}  {'Scored':>8}  {'Avg score':>10}")
                    print(f"  {'-'*25}  {'-'*8}  {'-'*10}")
                    for r in rows:
                        print(f"  {str(r[0]):<25}  {r[1]:>8,}  {float(r[2]):>10.3f}")
            except Exception:
                pass

        engine.dispose()

        # Check models/ dir for pkl files
        pkl_files = list(MODELS_DIR.glob("*.pkl")) if MODELS_DIR.exists() else []
        print(f"\n  Model artifacts in models/: {len(pkl_files)}")
        for p in sorted(pkl_files):
            size_mb = p.stat().st_size / 1_048_576
            print(f"    {p.name}  ({size_mb:.1f} MB)")

    except Exception as exc:
        # Non-fatal: summary failure should not abort the pipeline
        print(f"  WARNING: summary query failed -- {exc}")

    print("\n[10] OK")
    return True


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RE_CL complete pipeline setup -- zero to running system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--from-step",
        type=int,
        default=1,
        metavar="N",
        help="Start execution from step N (1-10). Steps before N are skipped.",
    )
    parser.add_argument(
        "--skip-data",
        action="store_true",
        help="Skip step 3 (CSV ingestion) and step 4 (cleaning).",
    )
    parser.add_argument(
        "--skip-osm",
        action="store_true",
        help="Skip OSM enrichment inside step 5 (feature engineering).",
    )
    parser.add_argument(
        "--skip-gtfs",
        action="store_true",
        help="Skip GTFS bus-stop enrichment inside step 5 (feature engineering, V6).",
    )
    parser.add_argument(
        "--skip-model",
        action="store_true",
        help="Skip step 6 (model training).",
    )
    parser.add_argument(
        "--skip-backtest",
        action="store_true",
        help="Skip step 8 (walk-forward backtesting).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print every command that would run without executing it.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    dry_run: bool = args.dry_run
    from_step: int = args.from_step

    python = sys.executable  # same interpreter that launched this script

    print("=" * 62)
    print("  RE_CL -- Pipeline Setup")
    print(f"  REPO_DIR : {REPO_DIR}")
    print(f"  from_step: {from_step}")
    print(f"  dry_run  : {dry_run}")
    print("=" * 62)

    t_global = time.perf_counter()

    # ------------------------------------------------------------------
    # STEP 1 -- Validate environment
    # ------------------------------------------------------------------
    if from_step <= 1:
        ok = step_validate_env(dry_run=dry_run)
        if not ok:
            return 1
    else:
        print(f"\n[1] SKIP  Validate environment (--from-step {from_step})")

    # ------------------------------------------------------------------
    # STEP 2 -- Apply DB migrations
    # ------------------------------------------------------------------
    if from_step <= 2:
        ok = step_apply_migrations(dry_run=dry_run)
        if not ok:
            return 1
    else:
        print(f"\n[2] SKIP  Apply DB migrations (--from-step {from_step})")

    # ------------------------------------------------------------------
    # STEP 3 -- Load CSV -> transactions_raw
    # ------------------------------------------------------------------
    skip_step3 = args.skip_data or from_step > 3
    ok = run_step(
        3,
        "Load CSV -> transactions_raw",
        [python, str(SRC_DIR / "ingestion" / "load_transactions.py")],
        skip=skip_step3,
        dry_run=dry_run,
    )
    if not ok:
        return 1

    # ------------------------------------------------------------------
    # STEP 4 -- Clean and normalize -> transactions_clean
    # ------------------------------------------------------------------
    skip_step4 = args.skip_data or from_step > 4
    ok = run_step(
        4,
        "Clean and normalize -> transactions_clean",
        [python, str(SRC_DIR / "ingestion" / "clean_transactions.py")],
        skip=skip_step4,
        dry_run=dry_run,
    )
    if not ok:
        return 1

    # ------------------------------------------------------------------
    # STEP 5 -- Build features -> transaction_features
    # ------------------------------------------------------------------
    skip_step5 = from_step > 5
    build_features_cmd = [python, str(SRC_DIR / "features" / "build_features.py")]
    if args.skip_osm:
        build_features_cmd.append("--skip-osm")
    if args.skip_gtfs:
        build_features_cmd.append("--skip-gtfs")

    step5_label = "Build features -> transaction_features"
    skip_flags = [f for f, cond in [("--skip-osm", args.skip_osm), ("--skip-gtfs", args.skip_gtfs)] if cond]
    if skip_flags:
        step5_label += f" ({' '.join(skip_flags)})"

    ok = run_step(
        5,
        step5_label,
        build_features_cmd,
        skip=skip_step5,
        dry_run=dry_run,
    )
    if not ok:
        return 1

    # ------------------------------------------------------------------
    # STEP 6 -- Train hedonic model -> models/
    # ------------------------------------------------------------------
    skip_step6 = args.skip_model or from_step > 6
    ok = run_step(
        6,
        "Train hedonic XGBoost model -> models/",
        [python, str(SRC_DIR / "models" / "hedonic_model.py"), "--eval"],
        skip=skip_step6,
        dry_run=dry_run,
    )
    if not ok:
        return 1

    # ------------------------------------------------------------------
    # STEP 7 -- Score all properties -> model_scores (all profiles)
    # ------------------------------------------------------------------
    skip_step7 = from_step > 7
    ok = run_step(
        7,
        "Score all properties -> model_scores (all profiles)",
        [
            python,
            str(SRC_DIR / "scoring" / "opportunity_score.py"),
            "--all-profiles",
        ],
        skip=skip_step7,
        dry_run=dry_run,
    )
    if not ok:
        return 1

    # ------------------------------------------------------------------
    # STEP 8 -- Walk-forward backtesting validation
    # ------------------------------------------------------------------
    skip_step8 = args.skip_backtest or from_step > 8
    ok = run_step(
        8,
        "Walk-forward backtesting validation",
        [python, str(SRC_DIR / "backtesting" / "walk_forward.py")],
        skip=skip_step8,
        dry_run=dry_run,
    )
    if not ok:
        return 1

    # ------------------------------------------------------------------
    # STEP 9 -- Build commune maps (commune_ranking + heatmap)
    # ------------------------------------------------------------------
    skip_step9 = from_step > 9

    ok = run_step(
        9,
        "Build commune ranking",
        [python, str(SRC_DIR / "maps" / "commune_ranking.py")],
        skip=skip_step9,
        dry_run=dry_run,
    )
    if not ok:
        return 1

    ok = run_step(
        9,
        "Build interactive heatmap",
        [python, str(SRC_DIR / "maps" / "heatmap.py")],
        skip=skip_step9,
        dry_run=dry_run,
    )
    if not ok:
        return 1

    # ------------------------------------------------------------------
    # STEP 10 -- Summary report
    # ------------------------------------------------------------------
    ok = step_summary(dry_run=dry_run)
    if not ok:
        return 1

    total = time.perf_counter() - t_global
    print(f"\n{'=' * 62}")
    print(f"  Pipeline complete in {total:.1f}s")
    print(f"{'=' * 62}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
