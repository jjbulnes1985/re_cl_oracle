"""
stale_data.py
-------------
Middleware to detect and report stale model data.

Adds headers to API responses for /properties, /scores, and /analytics endpoints:
  X-Model-Version  : e.g. "v1.0"
  X-Data-Age-Days  : integer days since the most recent model_scores entry
  X-Data-Stale     : "true" if age > STALE_THRESHOLD_DAYS, else "false"

Configuration (env vars):
  STALE_THRESHOLD_DAYS  — days before data is considered stale (default: 30)
  MODEL_VERSION         — model version tag (default: "v1.0")

The middleware never raises an exception — if the DB is unreachable or the
query fails, the headers are simply omitted and the response is returned as-is.

Usage (in main.py):
    from src.api.middleware.stale_data import stale_data_middleware
    app.middleware("http")(stale_data_middleware)
"""

import os
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import text

STALE_THRESHOLD_DAYS = int(os.getenv("STALE_THRESHOLD_DAYS", "30"))

# Endpoints that get the freshness headers
_MONITORED_PREFIXES = ("/properties", "/scores", "/analytics")


async def stale_data_middleware(request: Request, call_next):
    """
    ASGI middleware that appends data-age headers to responses from
    /properties, /scores, and /analytics endpoints.

    The DB query is best-effort: any exception is silently swallowed so
    the middleware never breaks a live request.
    """
    response = await call_next(request)

    if not any(request.url.path.startswith(p) for p in _MONITORED_PREFIXES):
        return response

    try:
        from src.api.db import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT MAX(scored_at) FROM model_scores")
            ).scalar()

        if result is not None:
            # Normalise to UTC-aware datetime
            if result.tzinfo is None:
                result = result.replace(tzinfo=timezone.utc)

            age_days = (datetime.now(timezone.utc) - result).days
            is_stale = age_days > STALE_THRESHOLD_DAYS

            response.headers["X-Model-Version"] = os.getenv("MODEL_VERSION", "v1.0")
            response.headers["X-Data-Age-Days"] = str(age_days)
            response.headers["X-Data-Stale"] = "true" if is_stale else "false"

    except Exception:
        # Never fail a request because of a metadata lookup error.
        pass

    return response
