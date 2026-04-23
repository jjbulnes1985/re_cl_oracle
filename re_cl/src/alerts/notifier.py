"""
notifier.py
-----------
Alert system for high-opportunity properties.

Detects newly scored properties above the alert threshold and notifies via:
  1. Console (always)
  2. JSON report saved to data/exports/alerts_YYYY-MM-DD.json
  3. Email (if ALERT_EMAIL_TO is configured in .env)
  4. Windows desktop notification (if running on Windows + plyer installed)

Tracks already-alerted properties in data/exports/.alerts_seen.json
to avoid duplicate notifications.

Thresholds (configurable via env vars):
  ALERT_MIN_SCORE=0.75        # minimum opportunity score
  ALERT_MIN_GAP_PCT=-0.15     # max gap% (negative = undervalued by ≥15%)
  ALERT_MIN_CONFIDENCE=0.65   # minimum data confidence

Usage:
    python src/alerts/notifier.py
    python src/alerts/notifier.py --dry-run
    python src/alerts/notifier.py --threshold 0.80
    python src/alerts/notifier.py --last-hours 24
"""

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# ── Config ────────────────────────────────────────────────────────────────────

MODEL_VERSION     = os.getenv("MODEL_VERSION",      "v1.0")
ALERT_MIN_SCORE   = float(os.getenv("ALERT_MIN_SCORE",   "0.75"))
ALERT_MIN_GAP     = float(os.getenv("ALERT_MIN_GAP_PCT", "-0.15"))
ALERT_MIN_CONF    = float(os.getenv("ALERT_MIN_CONFIDENCE", "0.65"))
EXPORTS_DIR       = Path(os.getenv("EXPORTS_DIR",    "data/exports"))
SEEN_FILE         = EXPORTS_DIR / ".alerts_seen.json"

# Webhook config (optional)
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")

# Email config (optional)
SMTP_HOST         = os.getenv("SMTP_HOST",         "smtp.gmail.com")
SMTP_PORT         = int(os.getenv("SMTP_PORT",     "587"))
SMTP_USER         = os.getenv("SMTP_USER",         "")
SMTP_PASSWORD     = os.getenv("SMTP_PASSWORD",     "")
ALERT_EMAIL_TO    = os.getenv("ALERT_EMAIL_TO",    "")
ALERT_EMAIL_FROM  = os.getenv("ALERT_EMAIL_FROM",  SMTP_USER)


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


# ── Seen IDs tracking ─────────────────────────────────────────────────────────

def load_seen_ids() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            return set()
    return set()


def save_seen_ids(ids: set) -> None:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(ids)))


# ── Query high-opportunity properties ────────────────────────────────────────

def fetch_high_opportunities(engine, min_score: float, last_hours: int = None) -> pd.DataFrame:
    time_filter = ""
    if last_hours:
        cutoff = datetime.utcnow() - timedelta(hours=last_hours)
        time_filter = f"AND ms.scored_at >= '{cutoff.isoformat()}'"

    query = text(f"""
        SELECT
            ms.id            AS score_id,
            ms.opportunity_score,
            ms.undervaluation_score,
            ms.gap_pct,
            ms.data_confidence,
            ms.predicted_uf_m2,
            ms.actual_uf_m2,
            ms.shap_top_features,
            ms.source,
            ms.scored_at,
            COALESCE(tc.county_name, sl.county_name)       AS county_name,
            COALESCE(tc.project_type_norm, sl.project_type) AS project_type,
            COALESCE(tc.real_value_uf, sl.price_uf)         AS price_uf,
            COALESCE(tc.surface_m2, sl.surface_m2)          AS surface_m2,
            sl.url
        FROM model_scores ms
        LEFT JOIN transactions_clean tc ON tc.id = ms.clean_id AND ms.source = 'cbr'
        LEFT JOIN scraped_listings    sl ON sl.id = ms.clean_id AND ms.source = 'scraped'
        WHERE ms.model_version = :v
          AND ms.opportunity_score >= :min_score
          AND ms.gap_pct <= :max_gap
          AND ms.data_confidence >= :min_conf
          {time_filter}
        ORDER BY ms.opportunity_score DESC
        LIMIT 200
    """)

    df = pd.read_sql(query, engine, params={
        "v":        MODEL_VERSION,
        "min_score": min_score,
        "max_gap":   ALERT_MIN_GAP,
        "min_conf":  ALERT_MIN_CONF,
    })
    return df


# ── Format alerts ─────────────────────────────────────────────────────────────

def format_alert_row(row: dict) -> str:
    score   = row.get("opportunity_score", 0)
    gap     = (row.get("gap_pct") or 0) * 100
    county  = row.get("county_name", "?")
    ptype   = row.get("project_type", "?")
    uf_m2   = row.get("actual_uf_m2") or row.get("price_uf", 0)
    pred    = row.get("predicted_uf_m2", 0)
    url     = row.get("url") or "N/A"
    source  = row.get("source", "cbr")

    drivers = ""
    if row.get("shap_top_features"):
        try:
            feats = json.loads(row["shap_top_features"])
            drivers = " | ".join(
                f"{f['feature']} {'+' if f['direction'] == 'up' else '-'}{abs(f['shap']):.3f}"
                for f in feats[:3]
            )
        except Exception:
            pass

    return (
        f"  [{source.upper()}] {county} · {ptype}\n"
        f"    Score: {score:.3f}  |  Gap: {gap:+.1f}%  |  UF/m²: {uf_m2:.1f} vs {pred:.1f} pred\n"
        f"    Drivers: {drivers or 'N/A'}\n"
        f"    URL: {url}"
    )


def build_email_html(alerts: list[dict]) -> str:
    rows = ""
    for a in alerts:
        gap   = (a.get("gap_pct") or 0) * 100
        score = a.get("opportunity_score", 0)
        url   = a.get("url", "")
        link  = f'<a href="{url}">{url[:60]}…</a>' if url and url != "N/A" else "—"
        rows += f"""
        <tr>
          <td>{a.get('county_name')}</td>
          <td>{a.get('project_type')}</td>
          <td><b>{score:.3f}</b></td>
          <td style="color:{'green' if gap < 0 else 'red'}">{gap:+.1f}%</td>
          <td>{a.get('actual_uf_m2', a.get('price_uf', '?')):.1f}</td>
          <td>{link}</td>
        </tr>"""

    return f"""
    <html><body>
    <h2>RE_CL — {len(alerts)} nuevas oportunidades inmobiliarias</h2>
    <p>Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Modelo: {MODEL_VERSION}</p>
    <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:sans-serif;font-size:13px">
      <thead style="background:#1e3a8a;color:white">
        <tr><th>Comuna</th><th>Tipo</th><th>Score</th><th>Gap%</th><th>UF/m²</th><th>Enlace</th></tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    <p style="font-size:11px;color:#666">Score mínimo: {ALERT_MIN_SCORE} | Gap máx: {ALERT_MIN_GAP*100:.0f}%</p>
    </body></html>"""


# ── Notification channels ────────────────────────────────────────────────────

def notify_console(new_alerts: list[dict]) -> None:
    logger.info("=" * 60)
    logger.info(f"ALERTAS RE_CL — {len(new_alerts)} nuevas oportunidades")
    logger.info("=" * 60)
    for a in new_alerts:
        logger.info(format_alert_row(a))
    logger.info("=" * 60)


def notify_json(new_alerts: list[dict]) -> Path:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today     = datetime.now().strftime("%Y-%m-%d")
    out_path  = EXPORTS_DIR / f"alerts_{today}.json"

    # Append to existing file if present
    existing = []
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text())
        except Exception:
            pass

    combined = existing + new_alerts
    out_path.write_text(json.dumps(combined, indent=2, default=str))
    logger.info(f"Alertas guardadas: {out_path} ({len(combined)} total hoy)")
    return out_path


def notify_email(new_alerts: list[dict]) -> bool:
    if not ALERT_EMAIL_TO or not SMTP_USER or not SMTP_PASSWORD:
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"RE_CL — {len(new_alerts)} nuevas oportunidades ({datetime.now().strftime('%Y-%m-%d')})"
        msg["From"]    = ALERT_EMAIL_FROM
        msg["To"]      = ALERT_EMAIL_TO

        text_body = "\n".join(format_alert_row(a) for a in new_alerts)
        html_body = build_email_html(new_alerts)

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(ALERT_EMAIL_FROM, ALERT_EMAIL_TO.split(","), msg.as_string())

        logger.info(f"Email enviado a {ALERT_EMAIL_TO}")
        return True
    except Exception as e:
        logger.warning(f"No se pudo enviar email: {e}")
        return False


def notify_desktop(new_alerts: list[dict]) -> bool:
    """Windows/macOS desktop notification via plyer (optional dep)."""
    try:
        from plyer import notification
        notification.notify(
            title=f"RE_CL — {len(new_alerts)} oportunidades nuevas",
            message=f"Top: {new_alerts[0]['county_name']} score={new_alerts[0]['opportunity_score']:.3f}" if new_alerts else "",
            app_name="RE_CL",
            timeout=10,
        )
        return True
    except ImportError:
        return False
    except Exception as e:
        logger.debug(f"Desktop notification failed: {e}")
        return False


# ── Webhook notification ──────────────────────────────────────────────────────

def send_webhook(title: str, body: str, level: str, url: str) -> bool:
    """
    POST a JSON alert payload to a configurable webhook URL.

    Payload schema:
        {"title": str, "body": str, "level": str,
         "timestamp": ISO8601, "source": "re_cl"}

    Returns True on HTTP 2xx, False on any error (never raises).
    """
    try:
        import requests  # soft dependency — already in requirements
        payload = {
            "title":     title,
            "body":      body,
            "level":     level,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source":    "re_cl",
        }
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
        logger.info(f"Webhook enviado a {url} — HTTP {resp.status_code}")
        return True
    except Exception as e:
        logger.warning(f"No se pudo enviar webhook a {url}: {e}")
        return False


# ── Generic send_alert (for API + programmatic use) ──────────────────────────

def send_alert(title: str, body: str, level: str = "info") -> None:
    """
    Send a single alert through available channels.

    Args:
        title:  Short alert title (shown in console header and email subject).
        body:   Alert body text.
        level:  Severity — "info", "warning", or "critical".
                Email is only sent for "warning" or "critical" (and only when
                SMTP_HOST + credentials are configured).

    Always logs to console. Email and desktop are best-effort.
    """
    # Console (always)
    log_fn = logger.warning if level in ("warning", "critical") else logger.info
    log_fn(f"[ALERT:{level.upper()}] {title} — {body}")

    # Email (only for warning/critical and when SMTP is configured)
    if level in ("warning", "critical") and SMTP_HOST and SMTP_USER and SMTP_PASSWORD and ALERT_EMAIL_TO:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"RE_CL [{level.upper()}] {title}"
            msg["From"]    = ALERT_EMAIL_FROM
            msg["To"]      = ALERT_EMAIL_TO
            msg.attach(MIMEText(f"{title}\n\n{body}", "plain"))
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(ALERT_EMAIL_FROM, ALERT_EMAIL_TO.split(","), msg.as_string())
            logger.info(f"Alert email enviado a {ALERT_EMAIL_TO}")
        except Exception as e:
            logger.warning(f"No se pudo enviar email de alerta: {e}")

    # Webhook (if ALERT_WEBHOOK_URL is configured)
    if ALERT_WEBHOOK_URL:
        send_webhook(title, body, level, ALERT_WEBHOOK_URL)

    # Desktop (optional dependency — plyer)
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=body[:256],
            app_name="RE_CL",
            timeout=8,
        )
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"Desktop notification failed: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False, threshold: float = None, last_hours: int = None) -> int:
    min_score = threshold or ALERT_MIN_SCORE
    engine    = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info(f"Buscando oportunidades (score≥{min_score}, gap≤{ALERT_MIN_GAP*100:.0f}%, conf≥{ALERT_MIN_CONF})")

    df = fetch_high_opportunities(engine, min_score=min_score, last_hours=last_hours)
    if df.empty:
        logger.info("Sin oportunidades que cumplan los criterios.")
        return 0

    seen_ids = load_seen_ids()
    new_rows = df[~df["score_id"].isin(seen_ids)]

    if new_rows.empty:
        logger.info(f"{len(df)} oportunidades encontradas, todas ya notificadas antes.")
        return 0

    new_alerts = new_rows.to_dict("records")
    logger.info(f"{len(new_alerts)} nuevas oportunidades (de {len(df)} totales)")

    if dry_run:
        notify_console(new_alerts)
        logger.info("[DRY RUN] No se guardaron ni enviaron alertas.")
        return len(new_alerts)

    # Notify through all channels
    notify_console(new_alerts)
    out_path = notify_json(new_alerts)
    notify_email(new_alerts)
    notify_desktop(new_alerts)

    # Mark as seen
    new_seen = seen_ids | set(new_rows["score_id"].tolist())
    save_seen_ids(new_seen)

    logger.info(f"{len(new_alerts)} alertas procesadas. Reporte: {out_path}")
    return len(new_alerts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",    action="store_true")
    parser.add_argument("--threshold",  type=float, default=None)
    parser.add_argument("--last-hours", type=int,   default=None,
                        help="Solo alertas de las últimas N horas")
    args = parser.parse_args()
    main(dry_run=args.dry_run, threshold=args.threshold, last_hours=args.last_hours)
