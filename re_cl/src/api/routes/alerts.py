"""
alerts.py
---------
FastAPI router for opportunity alerts and alert configuration.

Endpoints:
  GET  /alerts/opportunities  — Top properties above alert thresholds
  GET  /alerts/config         — Current alert config (from env vars)
  POST /alerts/test           — Trigger a safe console test alert
"""

import os
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.api.db import get_engine

router = APIRouter(prefix="/alerts", tags=["alerts"])

# Default thresholds read from env at startup (same as the standalone notifier script)
_DEFAULT_MIN_SCORE      = float(os.getenv("ALERT_MIN_SCORE",      "0.75"))
_DEFAULT_MIN_GAP_PCT    = float(os.getenv("ALERT_MIN_GAP_PCT",    "-0.15"))
_DEFAULT_MIN_CONFIDENCE = float(os.getenv("ALERT_MIN_CONFIDENCE", "0.65"))


# ── Models ────────────────────────────────────────────────────────────────────

class OpportunityAlert(BaseModel):
    score_id: int
    county_name: Optional[str] = None
    project_type: Optional[str] = None
    opportunity_score: float
    gap_pct: Optional[float] = None
    data_confidence: Optional[float] = None
    uf_m2_building: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class AlertConfig(BaseModel):
    min_score: float
    min_gap_pct: float
    min_confidence: float
    email_enabled: bool
    desktop_enabled: bool


class TestAlertResponse(BaseModel):
    status: str
    channel: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/opportunities", response_model=List[OpportunityAlert])
def get_opportunity_alerts(
    min_score: float = Query(
        default=_DEFAULT_MIN_SCORE,
        description="Minimum opportunity score (0–1)",
        ge=0.0,
        le=1.0,
    ),
    min_gap_pct: float = Query(
        default=_DEFAULT_MIN_GAP_PCT,
        description="Maximum gap_pct (negative = undervalued; e.g. -0.15 means ≥15% undervalued)",
    ),
    min_confidence: float = Query(
        default=_DEFAULT_MIN_CONFIDENCE,
        description="Minimum data_confidence (0–1)",
        ge=0.0,
        le=1.0,
    ),
    limit: int = Query(default=20, ge=1, le=200, description="Max rows returned"),
    engine: Engine = Depends(get_engine),
):
    """
    Return top opportunity properties matching alert thresholds.

    Queries v_opportunities (join of model_scores + transactions_clean).
    Useful for webhooks, scheduled notifications, or monitoring dashboards.
    """
    query = text("""
        SELECT
            score_id,
            county_name,
            project_type,
            opportunity_score,
            gap_pct,
            data_confidence,
            uf_m2_building,
            latitude,
            longitude
        FROM v_opportunities
        WHERE opportunity_score >= :min_score
          AND (gap_pct IS NULL OR gap_pct <= :min_gap_pct)
          AND data_confidence >= :min_confidence
          AND latitude IS NOT NULL
        ORDER BY opportunity_score DESC
        LIMIT :limit
    """)

    with engine.connect() as conn:
        rows = conn.execute(query, {
            "min_score":    min_score,
            "min_gap_pct":  min_gap_pct,
            "min_confidence": min_confidence,
            "limit":        limit,
        }).mappings().all()

    return [dict(row) for row in rows]


@router.get("/config", response_model=AlertConfig)
def get_alert_config():
    """
    Return current alert configuration from environment variables.

    Reflects the same thresholds used by the standalone notifier script.
    """
    return AlertConfig(
        min_score=float(os.getenv("ALERT_MIN_SCORE", "0.75")),
        min_gap_pct=float(os.getenv("ALERT_MIN_GAP_PCT", "-0.15")),
        min_confidence=float(os.getenv("ALERT_MIN_CONFIDENCE", "0.65")),
        email_enabled=bool(os.getenv("SMTP_HOST")),
        desktop_enabled=True,
    )


@router.post("/test", response_model=TestAlertResponse)
def trigger_test_alert():
    """
    Trigger a safe console test alert.

    Always writes to console only — never sends email or desktop notification.
    Safe to call from production without side effects.
    """
    from src.alerts.notifier import send_alert

    send_alert(
        title="TEST: RE_CL Alert System",
        body="This is a test alert triggered from the API endpoint /alerts/test.",
        level="info",
    )
    return TestAlertResponse(status="sent", channel="console")
