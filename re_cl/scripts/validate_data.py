#!/usr/bin/env python3
"""
validate_data.py
----------------
Data quality validation across all RE_CL pipeline tables.

Runs a set of SQL checks and produces a pass/fail report.
Marks critical failures separately from warnings.

Usage:
    python scripts/validate_data.py               # all checks, human-readable output
    python scripts/validate_data.py --critical    # only critical checks
    python scripts/validate_data.py --json        # JSON output + save to data/exports/
    python scripts/validate_data.py --exit-code   # exit 1 if any critical check fails
    python scripts/validate_data.py --critical --exit-code --json   # combinable
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths — script lives at re_cl/scripts/validate_data.py
# ---------------------------------------------------------------------------
REPO_DIR = Path(__file__).resolve().parent.parent
EXPORTS_DIR = REPO_DIR / "data" / "exports"

# ---------------------------------------------------------------------------
# Checks and thresholds
# ---------------------------------------------------------------------------

CHECKS: dict[str, str] = {
    "raw_has_data": "SELECT COUNT(*) FROM transactions_raw",
    "clean_has_data": "SELECT COUNT(*) FROM transactions_clean",
    "clean_retention_pct": """
        SELECT 100.0 * COUNT(*) / NULLIF((SELECT COUNT(*) FROM transactions_raw), 0)
        FROM transactions_clean
    """,
    "valid_price_pct": """
        SELECT 100.0 * SUM(CASE WHEN has_valid_price THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0)
        FROM transactions_clean
    """,
    "valid_coords_pct": """
        SELECT 100.0 * COUNT(*) / NULLIF((SELECT COUNT(*) FROM transactions_clean), 0)
        FROM transactions_clean WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    """,
    "coords_in_rm_bbox": """
        SELECT 100.0 * COUNT(*) / NULLIF((SELECT COUNT(*) FROM transactions_clean WHERE latitude IS NOT NULL), 0)
        FROM transactions_clean
        WHERE latitude BETWEEN -33.65 AND -33.30
          AND longitude BETWEEN -70.85 AND -70.45
    """,
    "features_coverage": """
        SELECT 100.0 * COUNT(tf.*) / NULLIF((SELECT COUNT(*) FROM transactions_clean WHERE is_outlier = FALSE), 0)
        FROM transaction_features tf
    """,
    "scores_coverage": """
        SELECT 100.0 * COUNT(*) / NULLIF((SELECT COUNT(*) FROM transactions_clean WHERE is_outlier = FALSE AND has_valid_price = TRUE), 0)
        FROM model_scores
    """,
    "score_range_valid": """
        SELECT COUNT(*) FROM model_scores
        WHERE opportunity_score < 0 OR opportunity_score > 1
    """,
    "median_score_sane": """
        SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY opportunity_score)
        FROM model_scores
    """,
    "no_null_gap_pct_all": """
        SELECT 100.0 * COUNT(*) / NULLIF((SELECT COUNT(*) FROM model_scores), 0)
        FROM model_scores WHERE gap_pct IS NULL
    """,
    "commune_stats_populated": "SELECT COUNT(*) FROM commune_stats",
}

# (operator, value_or_range)
# operators: "gt", "lt", "eq", "between"
THRESHOLDS: dict[str, tuple[str, Any]] = {
    "raw_has_data":            ("gt",      0),
    "clean_has_data":          ("gt",      0),
    "clean_retention_pct":     ("gt",      70.0),
    "valid_price_pct":         ("gt",      85.0),
    "valid_coords_pct":        ("gt",      80.0),
    "coords_in_rm_bbox":       ("gt",      95.0),
    "features_coverage":       ("gt",      95.0),
    "scores_coverage":         ("gt",      90.0),
    "score_range_valid":       ("eq",      0),
    "median_score_sane":       ("between", (0.3, 0.7)),
    "no_null_gap_pct_all":     ("lt",      20.0),
    "commune_stats_populated": ("gt",      20),
}

# Checks that must pass for data to be considered production-ready
CRITICAL_CHECKS = {
    "raw_has_data",
    "clean_has_data",
    "score_range_valid",
    "scores_coverage",
}

# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def _build_engine():
    """Return a SQLAlchemy engine, or raise if unavailable."""
    from dotenv import load_dotenv
    from sqlalchemy import create_engine

    env_path = REPO_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)

    url = os.getenv("DATABASE_URL")
    if not url:
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        db   = os.getenv("POSTGRES_DB",   "re_cl")
        user = os.getenv("POSTGRES_USER", "re_cl_user")
        pwd  = os.getenv("POSTGRES_PASSWORD", "")
        url  = f"postgresql://{user}:{pwd}@{host}:{port}/{db}"

    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})


# ---------------------------------------------------------------------------
# Threshold evaluation
# ---------------------------------------------------------------------------

def _evaluate(value: float | None, op: str, threshold: Any) -> bool:
    """Return True if `value` satisfies the threshold condition."""
    if value is None:
        return False
    if op == "gt":
        return value > threshold
    if op == "lt":
        return value < threshold
    if op == "eq":
        return value == threshold
    if op == "between":
        lo, hi = threshold
        return lo <= value <= hi
    raise ValueError(f"Unknown operator: {op!r}")


def _threshold_label(op: str, threshold: Any) -> str:
    """Human-readable expectation string."""
    if op == "gt":
        return f"> {threshold}"
    if op == "lt":
        return f"< {threshold}"
    if op == "eq":
        return f"= {threshold}"
    if op == "between":
        lo, hi = threshold
        return f"between {lo} and {hi}"
    return str(threshold)


def _format_value(name: str, value: float | None) -> str:
    """Format the measured value for display."""
    if value is None:
        return "NULL"
    # Percentage checks
    pct_checks = {
        "clean_retention_pct", "valid_price_pct", "valid_coords_pct",
        "coords_in_rm_bbox", "features_coverage", "scores_coverage",
        "no_null_gap_pct_all",
    }
    if name in pct_checks:
        return f"{value:,.1f}%"
    # Score median
    if name == "median_score_sane":
        return f"{value:.3f}"
    # Integer counts — format with comma separator
    return f"{int(value):,}"


# ---------------------------------------------------------------------------
# Run checks
# ---------------------------------------------------------------------------

class CheckResult:
    __slots__ = ("name", "value", "passed", "critical", "op", "threshold", "error")

    def __init__(
        self,
        name: str,
        value: float | None,
        passed: bool,
        critical: bool,
        op: str,
        threshold: Any,
        error: str | None = None,
    ):
        self.name = name
        self.value = value
        self.passed = passed
        self.critical = critical
        self.op = op
        self.threshold = threshold
        self.error = error

    @property
    def status(self) -> str:
        if self.error:
            return "ERROR"
        if self.passed:
            return "PASS"
        if self.critical:
            return "FAIL"
        return "WARN"


def run_checks(engine, only_critical: bool = False) -> list[CheckResult]:
    from sqlalchemy import text

    results: list[CheckResult] = []

    names = list(CHECKS.keys())
    if only_critical:
        names = [n for n in names if n in CRITICAL_CHECKS]

    for name in names:
        sql = CHECKS[name]
        op, threshold = THRESHOLDS[name]
        critical = name in CRITICAL_CHECKS
        # Each check gets its own connection so a failed query (which aborts
        # the Postgres transaction) does not poison subsequent checks.
        try:
            with engine.connect() as conn:
                raw = conn.execute(text(sql)).scalar()
            value = float(raw) if raw is not None else None
            passed = _evaluate(value, op, threshold)
            results.append(CheckResult(
                name=name,
                value=value,
                passed=passed,
                critical=critical,
                op=op,
                threshold=threshold,
            ))
        except Exception as exc:
            # Trim lengthy SQLAlchemy backtraces — keep first line only
            error_msg = str(exc).split("\n")[0]
            results.append(CheckResult(
                name=name,
                value=None,
                passed=False,
                critical=critical,
                op=op,
                threshold=threshold,
                error=error_msg,
            ))

    return results


# ---------------------------------------------------------------------------
# Output: human-readable
# ---------------------------------------------------------------------------

STATUS_WIDTH  = 4   # PASS / FAIL / WARN / ERR
NAME_WIDTH    = 30
VALUE_WIDTH   = 14


def _print_report(results: list[CheckResult], ts: str) -> None:
    total    = len(results)
    n_pass   = sum(1 for r in results if r.status == "PASS")
    n_warn   = sum(1 for r in results if r.status == "WARN")
    n_fail   = sum(1 for r in results if r.status in ("FAIL", "ERROR"))
    n_crit_fail = sum(1 for r in results if r.status in ("FAIL", "ERROR") and r.critical)

    width = 60
    print("=" * width)
    print("RE_CL DATA VALIDATION REPORT")
    print(ts)
    print("=" * width)
    print()

    for r in results:
        label_val  = _format_value(r.name, r.value)
        label_exp  = _threshold_label(r.op, r.threshold)
        crit_tag   = " [CRITICAL]" if r.critical else ""

        if r.error:
            print(f"{'ERR':<{STATUS_WIDTH}}  {r.name:<{NAME_WIDTH}}  ERROR: {r.error}")
        else:
            suffix = ""
            if r.status in ("WARN", "FAIL"):
                suffix = f"  <- {'CRITICAL FAILURE' if r.critical else 'below threshold'}"
            print(
                f"{r.status:<{STATUS_WIDTH}}  {r.name:<{NAME_WIDTH}}  "
                f"{label_val:>{VALUE_WIDTH}}  (expected {label_exp}){suffix}"
            )

    print()
    print(f"RESULT: {n_pass}/{total} PASS,  {n_warn}/{total} WARN,  {n_fail}/{total} FAIL")
    print()

    if n_crit_fail == 0:
        print("Data is: READY FOR PRODUCTION  (all critical checks pass)")
    else:
        print(f"Data is: NOT READY  ({n_crit_fail} critical failure(s) detected)")

    print()


# ---------------------------------------------------------------------------
# Output: JSON
# ---------------------------------------------------------------------------

def _build_json(results: list[CheckResult], ts: str) -> dict:
    n_pass      = sum(1 for r in results if r.status == "PASS")
    n_warn      = sum(1 for r in results if r.status == "WARN")
    n_fail      = sum(1 for r in results if r.status in ("FAIL", "ERROR"))
    n_crit_fail = sum(1 for r in results if r.status in ("FAIL", "ERROR") and r.critical)

    return {
        "generated_at": ts,
        "summary": {
            "total":           len(results),
            "pass":            n_pass,
            "warn":            n_warn,
            "fail":            n_fail,
            "critical_fails":  n_crit_fail,
            "ready_for_production": n_crit_fail == 0,
        },
        "checks": [
            {
                "name":      r.name,
                "status":    r.status,
                "critical":  r.critical,
                "value":     r.value,
                "operator":  r.op,
                "threshold": r.threshold,
                "error":     r.error,
            }
            for r in results
        ],
    }


def _save_json(payload: dict) -> Path:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPORTS_DIR / "validation_report.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RE_CL data quality validation across pipeline tables.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--critical",
        action="store_true",
        help="Run only critical checks (raw_has_data, clean_has_data, score_range_valid, scores_coverage).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON and save to data/exports/validation_report.json.",
    )
    parser.add_argument(
        "--exit-code",
        action="store_true",
        help="Exit with code 1 if any critical check fails (useful for CI pipelines).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- Connect to DB ---
    try:
        from sqlalchemy import text  # noqa: F401 — ensure sqlalchemy is installed
        engine = _build_engine()
        # Probe connection before running any check
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except ImportError as exc:
        msg = f"ERROR: missing Python package -- {exc}\n  Run: pip install -r requirements.txt"
        if args.json_output:
            payload = {
                "generated_at": ts,
                "error": msg,
                "summary": {"ready_for_production": False},
                "checks": [],
            }
            print(json.dumps(payload, indent=2))
        else:
            print(msg)
        return 1
    except Exception as exc:
        msg = (
            f"ERROR: cannot connect to database -- {exc}\n"
            "  Start Docker first: cd re_cl && docker-compose up -d"
        )
        if args.json_output:
            payload = {
                "generated_at": ts,
                "error": str(exc),
                "summary": {"ready_for_production": False},
                "checks": [],
            }
            print(json.dumps(payload, indent=2))
        else:
            print(msg)
        return 1

    # --- Run checks ---
    results = run_checks(engine, only_critical=args.critical)
    engine.dispose()

    # --- Output ---
    if args.json_output:
        payload = _build_json(results, ts)
        out_path = _save_json(payload)
        print(json.dumps(payload, indent=2, default=str))
        print(f"\n# Report saved to: {out_path}", file=sys.stderr)
    else:
        _print_report(results, ts)

    # --- Exit code ---
    if args.exit_code:
        has_critical_fail = any(
            r.status in ("FAIL", "ERROR") and r.critical for r in results
        )
        return 1 if has_critical_fail else 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
