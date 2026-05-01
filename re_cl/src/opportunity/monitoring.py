"""
monitoring.py — A6 Monitoring Agent

Detecta drift en el modelo y genera alertas. Comparar:
  - Distribución de scores actual vs snapshot anterior
  - Cobertura de comunas (DI nuevas)
  - Confianza de valoración (decay si datos muy viejos)
  - Outliers nuevos en gap_pct

Run:
  py src/opportunity/monitoring.py                  # genera reporte
  py src/opportunity/monitoring.py --save-snapshot  # guarda baseline para comparar
  py src/opportunity/monitoring.py --alert-threshold 0.05  # alertar si >5% drift
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()

SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / "data" / "monitoring"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _build_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    return "postgresql://{user}:{pwd}@{host}:{port}/{db}".format(
        user=os.getenv("POSTGRES_USER", "re_cl_user"),
        pwd=os.getenv("POSTGRES_PASSWORD", ""),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        db=os.getenv("POSTGRES_DB", "re_cl"),
    )


def collect_metrics(engine) -> dict:
    """Recolecta métricas actuales del sistema."""
    with engine.connect() as conn:
        # Score distribution
        score_dist = conn.execute(text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE opportunity_score >= 0.85) AS excellent,
                COUNT(*) FILTER (WHERE opportunity_score >= 0.70 AND opportunity_score < 0.85) AS very_good,
                COUNT(*) FILTER (WHERE opportunity_score >= 0.55 AND opportunity_score < 0.70) AS good,
                COUNT(*) FILTER (WHERE opportunity_score >= 0.40 AND opportunity_score < 0.55) AS regular,
                COUNT(*) FILTER (WHERE opportunity_score < 0.40) AS low,
                AVG(opportunity_score)::FLOAT AS avg,
                STDDEV(opportunity_score)::FLOAT AS std
            FROM opportunity.scores WHERE use_case = 'as_is'
        """)).fetchone()

        # Commune coverage (last 30 days)
        commune_coverage = conn.execute(text("""
            SELECT COUNT(DISTINCT county_name) AS communes,
                   COUNT(*) AS rows_30d
            FROM transactions_clean
            WHERE inscription_date >= NOW() - INTERVAL '30 days'
        """)).fetchone()

        # DI progress
        di_progress = conn.execute(text("""
            SELECT COUNT(DISTINCT county_name) AS done_communes,
                   COUNT(*) AS rows_total
            FROM transactions_raw
            WHERE data_source = 'data_inmobiliaria'
        """)).fetchone()

        # Valuation confidence
        val_conf = conn.execute(text("""
            SELECT AVG(confidence)::FLOAT AS avg_confidence,
                   COUNT(*) FILTER (WHERE confidence < 0.5)::FLOAT / NULLIF(COUNT(*), 0) AS pct_low_conf
            FROM opportunity.valuations WHERE method = 'triangulated'
        """)).fetchone()

        # Top comunas activity
        top_communes = conn.execute(text("""
            SELECT c.county_name, COUNT(*) AS n,
                   AVG(s.opportunity_score)::FLOAT AS avg_score
            FROM opportunity.candidates c
            JOIN opportunity.scores s ON s.candidate_id = c.id AND s.use_case = 'as_is'
            GROUP BY c.county_name
            ORDER BY n DESC LIMIT 10
        """)).fetchall()

        # Model info
        model_info = conn.execute(text("""
            SELECT version, trained_at, metrics
            FROM opportunity.model_versions
            ORDER BY trained_at DESC LIMIT 1
        """)).fetchone()

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "score_distribution": dict(score_dist._mapping) if score_dist else {},
        "commune_activity_30d": dict(commune_coverage._mapping) if commune_coverage else {},
        "di_progress": dict(di_progress._mapping) if di_progress else {},
        "valuation_confidence": dict(val_conf._mapping) if val_conf else {},
        "top_communes": [dict(r._mapping) for r in top_communes],
        "model": dict(model_info._mapping) if model_info else {},
    }


def compare_with_baseline(current: dict, baseline_path: Path, threshold: float) -> list[dict]:
    """Compara métricas actuales con snapshot anterior. Genera alertas."""
    if not baseline_path.exists():
        return []

    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except Exception:
        return [{"severity": "warn", "category": "snapshot", "msg": f"No se pudo leer baseline {baseline_path.name}"}]

    alerts = []
    cur_avg = current["score_distribution"].get("avg") or 0
    base_avg = baseline["score_distribution"].get("avg") or 0
    if base_avg > 0:
        drift = abs(cur_avg - base_avg) / base_avg
        if drift > threshold:
            alerts.append({
                "severity": "high" if drift > threshold * 2 else "medium",
                "category": "score_drift",
                "msg": f"Avg score moved {drift*100:.1f}% (current={cur_avg:.3f}, baseline={base_avg:.3f})"
            })

    cur_total = current["score_distribution"].get("total") or 0
    base_total = baseline["score_distribution"].get("total") or 0
    if base_total > 0:
        growth = (cur_total - base_total) / base_total
        if abs(growth) > 0.1:
            alerts.append({
                "severity": "medium" if growth > 0 else "low",
                "category": "candidate_volume",
                "msg": f"Candidate count changed {growth*100:+.1f}% (current={cur_total:,}, baseline={base_total:,})"
            })

    cur_di = current["di_progress"].get("done_communes") or 0
    base_di = baseline["di_progress"].get("done_communes") or 0
    if cur_di > base_di:
        alerts.append({
            "severity": "low",
            "category": "di_progress",
            "msg": f"DI completed {cur_di - base_di} new commune(s) since baseline ({base_di}→{cur_di}/40)"
        })

    cur_conf = current["valuation_confidence"].get("avg_confidence") or 0
    base_conf = baseline["valuation_confidence"].get("avg_confidence") or 0
    if base_conf > 0 and cur_conf < base_conf * 0.9:
        alerts.append({
            "severity": "medium",
            "category": "confidence_drop",
            "msg": f"Valuation confidence dropped {(1 - cur_conf/base_conf)*100:.1f}% (current={cur_conf:.2f}, baseline={base_conf:.2f})"
        })

    return alerts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save-snapshot", action="store_true", help="Save current state as baseline")
    parser.add_argument("--alert-threshold", type=float, default=0.05, help="Drift threshold (5% default)")
    parser.add_argument("--baseline", type=str, default="baseline.json")
    args = parser.parse_args()

    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info("=" * 60)
    logger.info("A6 MONITORING — Drift detection + alerts")
    logger.info("=" * 60)

    metrics = collect_metrics(engine)

    # Save report (always)
    report_path = SNAPSHOT_DIR / f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    logger.info(f"Report: {report_path}")

    # Print summary
    sd = metrics["score_distribution"]
    logger.info(f"Score distribution: total={sd.get('total'):,} | excellent={sd.get('excellent'):,} | "
                f"very_good={sd.get('very_good'):,} | avg={sd.get('avg'):.3f}")
    di = metrics["di_progress"]
    logger.info(f"DI progress: {di.get('done_communes')}/40 communes, {di.get('rows_total'):,} rows")
    vc = metrics["valuation_confidence"]
    logger.info(f"Valuation confidence: avg={vc.get('avg_confidence'):.2f}, "
                f"pct_low={vc.get('pct_low_conf')*100:.1f}%")

    # Compare with baseline
    baseline_path = SNAPSHOT_DIR / args.baseline
    if baseline_path.exists():
        alerts = compare_with_baseline(metrics, baseline_path, args.alert_threshold)
        if alerts:
            logger.info("")
            logger.info(f"ALERTS ({len(alerts)}):")
            for a in alerts:
                icon = "🔴" if a["severity"] == "high" else "🟡" if a["severity"] == "medium" else "🟢"
                logger.info(f"  {icon} [{a['category']}] {a['msg']}")
        else:
            logger.info("No drift detected — system stable")
    else:
        logger.info(f"No baseline at {baseline_path.name}. Run with --save-snapshot to create one.")

    # Save snapshot if requested
    if args.save_snapshot:
        baseline_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        logger.info(f"Baseline saved: {baseline_path}")

    logger.info("=" * 60)


if __name__ == "__main__":
    main()
