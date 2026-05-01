"""
main.py
-------
FastAPI application entrypoint for RE_CL opportunity detection API.

Usage:
    uvicorn src.api.main:app --reload --port 8000

Docs available at:
    http://localhost:8000/docs     (Swagger UI)
    http://localhost:8000/redoc    (ReDoc)
"""

import os
from collections import defaultdict
from contextlib import asynccontextmanager
from time import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routes import properties, scores, profiles
from src.api.routes.alerts import router as alerts_router
from src.api.routes.analytics import router as analytics_router
from src.api.routes.auth import router as auth_router
from src.api.routes.opportunity import router as opportunity_router
from src.api.routes.predict import router as predict_router
from src.api.routes.saved_searches import router as searches_router
from src.api.middleware.stale_data import stale_data_middleware

MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0")

tags_metadata = [
    {"name": "properties", "description": "Scored property listings, detail, search, comparables, and commune data."},
    {"name": "scores", "description": "Model scores — top opportunities, summaries, and individual score lookup."},
    {"name": "profiles", "description": "Scoring profiles — list built-in profiles and re-score with custom weights."},
    {"name": "analytics", "description": "Price trends and score distribution analytics."},
    {"name": "alerts", "description": "Opportunity alerts — thresholds, config, and test triggers."},
    {"name": "auth", "description": "JWT authentication — register, login, token refresh, and current user."},
    {"name": "searches", "description": "Saved search filters per authenticated user."},
    {"name": "predict", "description": "ML price prediction — predict expected UF/m² for any property attributes (no DB required)."},
    {"name": "meta", "description": "Health check and API root."},
]

# ── In-memory rate limiter ────────────────────────────────────────────────────

_rate_counts: dict = defaultdict(list)
RATE_LIMIT_CALLS = 100  # per window
RATE_LIMIT_WINDOW = 60  # seconds

_RATE_LIMIT_SKIP_PATHS = {"/health", "/openapi.json", "/docs", "/redoc"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    yield


app = FastAPI(
    title="RE_CL — Oportunidades Inmobiliarias RM",
    description=(
        "API para detección de inmuebles subvalorados en la Región Metropolitana de Santiago. "
        f"Modelo: {MODEL_VERSION} | Fuente: CBR RM 2013-2014"
    ),
    version=MODEL_VERSION,
    lifespan=lifespan,
    openapi_tags=tags_metadata,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://localhost:80", "http://localhost",
        "http://127.0.0.1:3000", "http://127.0.0.1:80", "http://127.0.0.1",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
    expose_headers=[
        "X-Total-Count",
        "X-Page",
        "X-Page-Size",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-Data-Age-Days",
        "X-Data-Stale",
    ],
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in _RATE_LIMIT_SKIP_PATHS:
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    # Exempt pytest TestClient from rate limiting so full test suites don't hit 429
    if client_ip == "testclient":
        return await call_next(request)

    # Per-user rate limiting: authenticated requests get their own bucket
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            from jose import jwt as _jwt
            from src.api.routes.auth import SECRET_KEY
            payload = _jwt.decode(auth_header[7:], SECRET_KEY, algorithms=["HS256"])
            uid = payload.get("sub")
            if uid:
                client_ip = f"user:{uid}"
        except Exception:
            pass  # Fall back to IP-based limiting

    now = time()
    window_start = now - RATE_LIMIT_WINDOW

    # Clean old entries
    _rate_counts[client_ip] = [t for t in _rate_counts[client_ip] if t > window_start]

    if len(_rate_counts[client_ip]) >= RATE_LIMIT_CALLS:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded: {RATE_LIMIT_CALLS} requests per {RATE_LIMIT_WINDOW}s"},
        )

    _rate_counts[client_ip].append(now)

    response = await call_next(request)
    remaining = RATE_LIMIT_CALLS - len(_rate_counts[client_ip])
    response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT_CALLS)
    response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
    return response

app.middleware("http")(stale_data_middleware)

app.include_router(properties.router)
app.include_router(scores.router)
app.include_router(profiles.router)
app.include_router(alerts_router)
app.include_router(analytics_router)
app.include_router(auth_router)
app.include_router(searches_router)
app.include_router(predict_router)
app.include_router(opportunity_router, prefix="/opportunity", tags=["opportunity"])


@app.get("/health", tags=["meta"])
def health():
    """Health check endpoint."""
    return {"status": "ok", "model_version": MODEL_VERSION}


@app.get("/", tags=["meta"])
def root():
    """API root — links to docs."""
    return {
        "name": "RE_CL API",
        "version": MODEL_VERSION,
        "docs": "/docs",
        "endpoints": ["/properties", "/scores", "/profiles", "/alerts", "/health"],
    }
