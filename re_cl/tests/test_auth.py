"""
test_auth.py
------------
Tests for JWT auth (/auth) and saved searches (/searches) endpoints.

Uses an in-memory SQLite DB so no live PostgreSQL is needed.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.api.db import get_engine

# ── In-memory SQLite engine for tests ────────────────────────────────────────
# StaticPool ensures all connections share the same in-memory DB instance,
# so tables created at setup time are visible to all route handlers.

_TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Create the two tables needed (SQLite-compatible DDL)
_SETUP_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS saved_searches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id),
    name       TEXT NOT NULL,
    filters    TEXT NOT NULL DEFAULT '{}',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

with _TEST_ENGINE.begin() as _conn:
    for stmt in _SETUP_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            _conn.execute(text(stmt))


def _override_engine() -> Engine:
    return _TEST_ENGINE


@pytest.fixture(autouse=True)
def _ensure_override():
    """Set the SQLite engine override for auth tests and restore prior state
    after each test so other modules are not affected."""
    prev = app.dependency_overrides.get(get_engine)
    app.dependency_overrides[get_engine] = _override_engine
    yield
    if prev is not None:
        app.dependency_overrides[get_engine] = prev
    else:
        app.dependency_overrides.pop(get_engine, None)


client = TestClient(app)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _register(email: str = "user@example.com", password: str = "password123") -> dict:
    resp = client.post("/auth/register", json={"email": email, "password": password})
    return resp


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Auth tests ────────────────────────────────────────────────────────────────

def test_register_creates_token():
    resp = _register("reg1@example.com")
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_register_duplicate_email_409():
    _register("dup@example.com")
    resp = _register("dup@example.com")
    assert resp.status_code == 409


def test_register_short_password_422():
    resp = client.post("/auth/register", json={"email": "short@example.com", "password": "abc"})
    assert resp.status_code == 422


def test_login_valid_credentials_returns_token():
    _register("login_ok@example.com", "mypassword")
    resp = client.post("/auth/login", json={"email": "login_ok@example.com", "password": "mypassword"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password_401():
    _register("wrong_pw@example.com", "correctpass")
    resp = client.post("/auth/login", json={"email": "wrong_pw@example.com", "password": "wrongpass"})
    assert resp.status_code == 401


def test_login_unknown_email_401():
    resp = client.post("/auth/login", json={"email": "nobody@example.com", "password": "anything"})
    assert resp.status_code == 401


def test_me_with_valid_token():
    resp = _register("me_valid@example.com", "password123")
    token = resp.json()["access_token"]
    resp2 = client.get("/auth/me", headers=_auth_header(token))
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["email"] == "me_valid@example.com"
    assert "id" in data


def test_me_without_token_401():
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_with_invalid_token_401():
    resp = client.get("/auth/me", headers=_auth_header("this.is.not.valid"))
    assert resp.status_code == 401


# ── Saved searches tests ──────────────────────────────────────────────────────

def _register_and_token(email: str) -> str:
    resp = _register(email, "password123")
    return resp.json()["access_token"]


def test_create_saved_search():
    token = _register_and_token("create_search@example.com")
    resp = client.post(
        "/searches",
        json={"name": "Las Condes cheap", "filters": {"county": "Las Condes", "max_price": 5000}},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Las Condes cheap"
    assert data["filters"]["county"] == "Las Condes"
    assert "id" in data


def test_list_saved_searches():
    token = _register_and_token("list_search@example.com")
    headers = _auth_header(token)
    client.post("/searches", json={"name": "Search A", "filters": {}}, headers=headers)
    client.post("/searches", json={"name": "Search B", "filters": {"zone": "este"}}, headers=headers)

    resp = client.get("/searches", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    names = [i["name"] for i in items]
    assert "Search A" in names
    assert "Search B" in names


def test_delete_saved_search():
    token = _register_and_token("delete_search@example.com")
    headers = _auth_header(token)

    create_resp = client.post(
        "/searches",
        json={"name": "To delete", "filters": {}},
        headers=headers,
    )
    search_id = create_resp.json()["id"]

    del_resp = client.delete(f"/searches/{search_id}", headers=headers)
    assert del_resp.status_code == 204

    list_resp = client.get("/searches", headers=headers)
    ids = [i["id"] for i in list_resp.json()]
    assert search_id not in ids


# ── Token refresh tests ───────────────────────────────────────────────────────

def test_refresh_returns_new_token():
    resp = _register("refresh1@example.com")
    token = resp.json()["access_token"]
    refresh_resp = client.post("/auth/refresh", headers=_auth_header(token))
    assert refresh_resp.status_code == 200
    data = refresh_resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert isinstance(data["access_token"], str) and len(data["access_token"]) > 0


def test_refresh_without_token_401():
    resp = client.post("/auth/refresh")
    assert resp.status_code == 401


def test_refresh_token_is_valid():
    resp = _register("refresh2@example.com")
    original_token = resp.json()["access_token"]
    refresh_resp = client.post("/auth/refresh", headers=_auth_header(original_token))
    new_token = refresh_resp.json()["access_token"]
    me_resp = client.get("/auth/me", headers=_auth_header(new_token))
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "refresh2@example.com"
