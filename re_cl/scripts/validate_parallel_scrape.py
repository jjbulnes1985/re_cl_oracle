"""
validate_parallel_scrape.py
---------------------------
Phase 9 validation: queries scraped_listings + model_scores after a
parallel-scrape run and produces a JSON report.

Success criteria:
  - Total scraped_listings > 5000   → exit 0
  - At least 2 distinct sources     → exit 0
  - model_scores has entries scored_at within the last 2 hours (proves the
    scraped_to_scored pipeline ran after the scrape)

Usage:
    py scripts/validate_parallel_scrape.py
    py scripts/validate_parallel_scrape.py --json
    py scripts/validate_parallel_scrape.py --min-total 5000
    py scripts/validate_parallel_scrape.py --output data/exports/phase9_validation_report.json
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _build_db_url() -> str:
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


def collect_report(engine, min_total: int = 5000) -> dict:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "min_total_required": min_total,
        "checks": {},
    }
    with engine.connect() as conn:
        # Total listings
        total = conn.execute(text("SELECT COUNT(*) FROM scraped_listings")).scalar() or 0
        report["total_listings"] = int(total)
        report["checks"]["total_gt_min"] = bool(total >= min_total)

        # Per source
        rows = conn.execute(text(
            "SELECT source, COUNT(*) AS n FROM scraped_listings GROUP BY source ORDER BY n DESC"
        )).mappings().all()
        report["by_source"] = [{"source": r["source"], "n": int(r["n"])} for r in rows]
        report["distinct_sources"] = len(rows)
        report["checks"]["at_least_2_sources"] = len(rows) >= 2

        # Per project_type
        rows = conn.execute(text(
            "SELECT project_type, COUNT(*) AS n FROM scraped_listings "
            "GROUP BY project_type ORDER BY n DESC"
        )).mappings().all()
        report["by_project_type"] = [{"type": r["project_type"], "n": int(r["n"])} for r in rows]

        # Top-10 communes
        rows = conn.execute(text(
            "SELECT county_name, COUNT(*) AS n FROM scraped_listings "
            "WHERE county_name IS NOT NULL AND county_name != '' "
            "GROUP BY county_name ORDER BY n DESC LIMIT 10"
        )).mappings().all()
        report["top_communes"] = [{"county": r["county_name"], "n": int(r["n"])} for r in rows]

        # Most recent scrape timestamp
        latest = conn.execute(text(
            "SELECT MAX(scraped_at) FROM scraped_listings"
        )).scalar()
        report["latest_scraped_at"] = latest.isoformat() if latest else None

        # Recently scored (last 2 hours) — detect that post-processing ran
        # Some schemas use model_scores.scored_at, some use created_at. Try both.
        try:
            recent_scores = conn.execute(text(
                "SELECT COUNT(*) FROM model_scores WHERE scored_at > :cutoff"
            ), {"cutoff": datetime.now(timezone.utc) - timedelta(hours=2)}).scalar() or 0
        except Exception:
            try:
                recent_scores = conn.execute(text(
                    "SELECT COUNT(*) FROM model_scores WHERE created_at > :cutoff"
                ), {"cutoff": datetime.now(timezone.utc) - timedelta(hours=2)}).scalar() or 0
            except Exception:
                recent_scores = None
        report["recent_scores_last_2h"] = recent_scores
        report["checks"]["post_processing_ran"] = bool(
            recent_scores is not None and recent_scores > 0
        )

    # DI checkpoint coverage
    cp_file = Path("data/processed/datainmobiliaria_checkpoint.json")
    if cp_file.exists():
        try:
            cp = json.loads(cp_file.read_text(encoding="utf-8"))
            report["di_checkpoint_communes_done"] = len(cp)
            report["di_checkpoint_total_rows"] = sum(v.get("rows", 0) for v in cp.values())
        except Exception as e:
            report["di_checkpoint_error"] = str(e)
    else:
        report["di_checkpoint"] = "absent"

    # Final status
    report["status"] = "PASS" if all(report["checks"].values()) else "FAIL"
    return report


def main():
    parser = argparse.ArgumentParser(description="Validate Phase 9 parallel scrape")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    parser.add_argument("--output", default="data/exports/phase9_validation_report.json",
                        help="Path to write JSON report")
    parser.add_argument("--min-total", type=int, default=5000,
                        help="Minimum total scraped_listings required (default 5000)")
    parser.add_argument("--exit-code", action="store_true",
                        help="Exit 1 on FAIL status (for CI use)")
    args = parser.parse_args()

    engine = create_engine(_build_db_url(), pool_pre_ping=True)
    report = collect_report(engine, min_total=args.min_total)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Phase 9 Validation — status: {report['status']}")
        print(f"  Total listings:         {report['total_listings']:,}")
        print(f"  Distinct sources:       {report['distinct_sources']}")
        print(f"  Min-total check passed: {report['checks']['total_gt_min']}")
        print(f"  2+ sources check:       {report['checks']['at_least_2_sources']}")
        print(f"  Post-processing ran:    {report['checks']['post_processing_ran']}")
        print(f"  Report saved:           {out_path}")

    if args.exit_code and report["status"] != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()
