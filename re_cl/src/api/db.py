"""
db.py
-----
Database engine singleton and FastAPI dependency for RE_CL API.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

load_dotenv()

MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0")


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


@lru_cache(maxsize=1)
def _engine_singleton() -> Engine:
    return create_engine(_build_db_url(), pool_pre_ping=True, pool_size=5, max_overflow=10)


def get_engine() -> Engine:
    """FastAPI dependency — returns the cached SQLAlchemy engine."""
    return _engine_singleton()
