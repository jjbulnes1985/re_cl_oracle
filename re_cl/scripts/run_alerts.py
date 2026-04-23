"""
run_alerts.py
-------------
Standalone CLI script — check v_opportunities and fire alerts.

Usage:
    py re_cl/scripts/run_alerts.py
    py re_cl/scripts/run_alerts.py --dry-run
    py re_cl/scripts/run_alerts.py --limit 10
    py re_cl/scripts/run_alerts.py --output json

Thresholds (env vars):
    ALERT_MIN_SCORE       default 0.75
    ALERT_MIN_GAP_PCT     default -0.15
    ALERT_MIN_CONFIDENCE  default 0.65

Outputs:
    Console summary always printed.
    --output json  →  data/exports/alerts_YYYY-MM-DD.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Make project root importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts.notifier import send_alert  # noqa: E402

# ── Config from env ────────────────────────────────────────────────────────────

ALERT_MIN_SCORE  = float(os.getenv("ALERT_MIN_SCORE",       "0.75"))
ALERT_MIN_GAP    = float(os.getenv("ALERT_MIN_GAP_PCT",     "-0.15"))
ALERT_MIN_CONF   = float(os.getenv("ALERT_MIN_CONFIDENCE",  "0.65"))
EXPORTS_DIR      = Path(os.getenv("EXPORTS_DIR",            "data/exports"))


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


def fetch_opportunities(limit: int) -> list[dict]:
    """Query v_opportunities and return rows above all thresholds."""
    from sqlalchemy import create_engine, text

    engine = create_engine(_build_db_url(), pool_pre_ping=True)
    query = text("""
        SELECT
            id,
            county_name,
            project_type_norm      AS project_type,
            opportunity_score,
            undervaluation_score,
            gap_pct,
            data_confidence,
            actual_uf_m2,
            predicted_uf_m2,
            source
        FROM v_opportunities
        WHERE opportunity_score  >= :min_score
          AND gap_pct            <= :max_gap
          AND data_confidence    >= :min_conf
        ORDER BY opportunity_score DESC
        LIMIT :lim
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {
            "min_score": ALERT_MIN_SCORE,
            "max_gap":   ALERT_MIN_GAP,
            "min_conf":  ALERT_MIN_CONF,
            "lim":       limit,
        }).mappings().all()
    return [dict(r) for r in rows]


def format_title(row: dict) -> str:
    return (
        f"Oportunidad RE_CL — {row.get('county_name', '?')} "
        f"(score={row.get('opportunity_score', 0):.3f})"
    )


def format_body(row: dict) -> str:
    gap    = (row.get("gap_pct") or 0) * 100
    uf_m2  = row.get("actual_uf_m2") or 0
    pred   = row.get("predicted_uf_m2") or 0
    ptype  = row.get("project_type", "?")
    source = row.get("source", "cbr").upper()
    return (
        f"[{source}] {ptype} | Gap: {gap:+.1f}% | "
        f"UF/m²: {uf_m2:.1f} vs {pred:.1f} pred | "
        f"Confianza: {row.get('data_confidence', 0):.2f}"
    )


def save_json(opportunities: list[dict]) -> Path:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today    = datetime.now().strftime("%Y-%m-%d")
    out_path = EXPORTS_DIR / f"alerts_{today}.json"

    existing: list = []
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text())
        except Exception:
            pass

    combined = existing + [
        {**o, "alerted_at": datetime.now(timezone.utc).isoformat()}
        for o in opportunities
    ]
    out_path.write_text(json.dumps(combined, indent=2, default=str))
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check v_opportunities and fire RE_CL alerts."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print opportunities but do not send alerts.",
    )
    parser.add_argument(
        "--limit", type=int, default=5, metavar="N",
        help="Maximum number of properties to alert on (default: 5).",
    )
    parser.add_argument(
        "--output", choices=["json"], default=None,
        help="Save results to data/exports/alerts_YYYY-MM-DD.json.",
    )
    args = parser.parse_args()

    print(
        f"[run_alerts] Thresholds — score≥{ALERT_MIN_SCORE} | "
        f"gap≤{ALERT_MIN_GAP*100:.0f}% | conf≥{ALERT_MIN_CONF} | limit={args.limit}"
    )

    try:
        opportunities = fetch_opportunities(args.limit)
    except Exception as exc:
        print(f"[run_alerts] ERROR connecting to DB: {exc}", file=sys.stderr)
        sys.exit(1)

    found = len(opportunities)
    print(f"[run_alerts] Found {found} opportunit{'y' if found == 1 else 'ies'}.")

    if found == 0:
        print("[run_alerts] Nothing to alert. Exiting.")
        return

    sent = 0
    for row in opportunities:
        title = format_title(row)
        body  = format_body(row)
        print(f"  • {title}")
        print(f"    {body}")

        if not args.dry_run:
            send_alert(title, body, level="warning")
            sent += 1

    if args.dry_run:
        print(f"\n[run_alerts] DRY RUN — Found {found} opportunities, 0 alerts sent.")
    else:
        print(f"\n[run_alerts] Found {found} opportunities, sent {sent} alerts.")

    if args.output == "json":
        out_path = save_json(opportunities)
        print(f"[run_alerts] Results saved to {out_path}")


if __name__ == "__main__":
    main()
