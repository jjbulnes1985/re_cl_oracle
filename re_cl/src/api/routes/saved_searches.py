"""
saved_searches.py
-----------------
CRUD endpoints for user-saved search filters.

Endpoints:
  GET    /searches           — list current user's searches
  POST   /searches           — create a new saved search
  DELETE /searches/{id}      — delete a saved search (owner only)
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.api.db import get_engine
from src.api.routes.auth import get_current_user

# ── Pydantic models ───────────────────────────────────────────────────────────

class SavedSearchCreate(BaseModel):
    name: str
    filters: dict


class SavedSearchOut(BaseModel):
    id: int
    name: str
    filters: dict
    created_at: datetime


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_postgres(engine: Engine) -> bool:
    return engine.dialect.name == "postgresql"


def _parse_filters(value) -> dict:
    """Return dict whether value is already a dict (PG JSONB) or a JSON string (SQLite)."""
    if isinstance(value, dict):
        return value
    return json.loads(value)


# ── Router ────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/searches", tags=["searches"])


@router.get("", response_model=list[SavedSearchOut])
def list_searches(
    current_user: dict = Depends(get_current_user),
    engine: Engine = Depends(get_engine),
):
    """List all saved searches for the authenticated user."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, name, filters, created_at "
                "FROM saved_searches "
                "WHERE user_id = :uid "
                "ORDER BY created_at DESC"
            ),
            {"uid": current_user["id"]},
        ).fetchall()

    return [
        SavedSearchOut(id=r[0], name=r[1], filters=_parse_filters(r[2]), created_at=r[3])
        for r in rows
    ]


@router.post("", response_model=SavedSearchOut, status_code=status.HTTP_201_CREATED)
def create_search(
    body: SavedSearchCreate,
    current_user: dict = Depends(get_current_user),
    engine: Engine = Depends(get_engine),
):
    """Save a new search filter set for the authenticated user."""
    filters_json = json.dumps(body.filters)

    if _is_postgres(engine):
        # PostgreSQL: use RETURNING for a single round-trip
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO saved_searches (user_id, name, filters) "
                    "VALUES (:uid, :name, :filters::jsonb) "
                    "RETURNING id, name, filters, created_at"
                ),
                {"uid": current_user["id"], "name": body.name, "filters": filters_json},
            ).fetchone()
        return SavedSearchOut(
            id=row[0], name=row[1], filters=_parse_filters(row[2]), created_at=row[3]
        )
    else:
        # SQLite (tests): insert then fetch by lastrowid
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    "INSERT INTO saved_searches (user_id, name, filters) "
                    "VALUES (:uid, :name, :filters)"
                ),
                {"uid": current_user["id"], "name": body.name, "filters": filters_json},
            )
            new_id = result.lastrowid
            row = conn.execute(
                text("SELECT id, name, filters, created_at FROM saved_searches WHERE id = :id"),
                {"id": new_id},
            ).fetchone()
        return SavedSearchOut(
            id=row[0], name=row[1], filters=_parse_filters(row[2]), created_at=row[3]
        )


@router.delete("/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_search(
    search_id: int,
    current_user: dict = Depends(get_current_user),
    engine: Engine = Depends(get_engine),
):
    """Delete a saved search. Returns 404 if not found, 403 if not the owner."""
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT user_id FROM saved_searches WHERE id = :sid"),
            {"sid": search_id},
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search not found")

        if row[0] != current_user["id"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your search")

        conn.execute(
            text("DELETE FROM saved_searches WHERE id = :sid"),
            {"sid": search_id},
        )
