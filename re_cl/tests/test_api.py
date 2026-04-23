"""
test_api.py
-----------
Tests for FastAPI endpoints using synthetic in-memory data.
No real database connection required — uses dependency overrides.
"""

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from src.api.main import app
from src.api.db import get_engine


# ── Mock data ─────────────────────────────────────────────────────────────────

MOCK_PROPERTY = {
    "score_id":             1,
    "project_type":         "apartments",
    "county_name":          "Ñuñoa",
    "year":                 2014,
    "real_value_uf":        4500.0,
    "surface_m2":           75.0,
    "uf_m2_building":       60.0,
    "opportunity_score":    0.82,
    "undervaluation_score": 0.75,
    "gap_pct":              -0.25,
    "gap_percentile":       0.18,
    "predicted_uf_m2":      80.0,
    "data_confidence":      0.91,
    "shap_top_features":    json.dumps([
        {"feature": "county_name", "shap": -0.42, "direction": "down"},
        {"feature": "surface_m2",  "shap":  0.18, "direction": "up"},
    ]),
    "latitude":             -33.45,
    "longitude":            -70.60,
}

MOCK_COMMUNE = {
    "county_name":       "Ñuñoa",
    "n_transactions":    850,
    "median_score":      0.71,
    "pct_subvaloradas":  42.3,
    "median_uf_m2":      58.4,
    "median_gap_pct":    -0.12,
}

MOCK_SCORE_ROW = {
    "score_id":             1,
    "clean_id":             101,
    "model_version":        "v1.0",
    "opportunity_score":    0.82,
    "undervaluation_score": 0.75,
    "data_confidence":      0.91,
    "predicted_uf_m2":      80.0,
    "actual_uf_m2":         60.0,
    "gap_pct":              -0.25,
    "gap_percentile":       0.18,
    "shap_top_features":    json.dumps([
        {"feature": "county_name", "shap": -0.42, "direction": "down"},
    ]),
    "county_name":          "Ñuñoa",
    "project_type":         "apartments",
}

MOCK_SUMMARY_ROW = {
    "total_scored":  5000,
    "mean_score":    0.61,
    "min_score":     0.10,
    "max_score":     0.98,
    "high_opp_count": 1200,
}


class _DictRow(dict):
    """Dict subclass that also supports attribute access, mimicking SQLAlchemy RowMapping."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def _make_mock_conn(rows):
    """Build a mock SQLAlchemy connection returning given rows as dict-like objects."""
    dict_rows = [_DictRow(r) for r in rows]
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value   = dict_rows
    mock_result.mappings.return_value.first.return_value = dict_rows[0] if dict_rows else None
    mock_conn = MagicMock()
    mock_conn.__enter__ = lambda s: mock_conn
    mock_conn.__exit__  = MagicMock(return_value=False)
    mock_conn.execute.return_value = mock_result
    return mock_conn


def _make_mock_engine(rows):
    mock_engine = MagicMock()
    mock_engine.connect.return_value = _make_mock_conn(rows)
    return mock_engine


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client_with_properties():
    """Client with engine overridden to return one mock property."""
    engine = _make_mock_engine([MOCK_PROPERTY])
    app.dependency_overrides[get_engine] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_with_communes():
    engine = _make_mock_engine([MOCK_COMMUNE])
    app.dependency_overrides[get_engine] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_with_scores():
    engine = _make_mock_engine([MOCK_SCORE_ROW])
    app.dependency_overrides[get_engine] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_with_summary():
    engine = _make_mock_engine([MOCK_SUMMARY_ROW])
    app.dependency_overrides[get_engine] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Tests: Meta ───────────────────────────────────────────────────────────────

class TestHealthAndRoot:
    def test_health_returns_ok(self):
        with TestClient(app) as client:
            r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_root_lists_endpoints(self):
        with TestClient(app) as client:
            r = client.get("/")
        assert r.status_code == 200
        body = r.json()
        assert "endpoints" in body
        assert "/properties" in body["endpoints"]
        assert "/scores" in body["endpoints"]


# ── Tests: /properties ────────────────────────────────────────────────────────

class TestPropertiesEndpoints:
    def test_list_properties_returns_200(self, client_with_properties):
        r = client_with_properties.get("/properties")
        assert r.status_code == 200

    def test_list_properties_returns_list(self, client_with_properties):
        r = client_with_properties.get("/properties")
        assert isinstance(r.json(), list)

    def test_list_properties_has_required_fields(self, client_with_properties):
        r = client_with_properties.get("/properties")
        if r.json():
            item = r.json()[0]
            assert "score_id" in item
            assert "opportunity_score" in item
            assert "county_name" in item

    def test_list_properties_filter_min_score(self, client_with_properties):
        r = client_with_properties.get("/properties?min_score=0.8")
        assert r.status_code == 200

    def test_list_properties_invalid_score_range(self, client_with_properties):
        r = client_with_properties.get("/properties?min_score=1.5")
        assert r.status_code == 422

    def test_list_properties_pagination(self, client_with_properties):
        r = client_with_properties.get("/properties?limit=10&offset=0")
        assert r.status_code == 200

    def test_get_property_by_id(self, client_with_properties):
        r = client_with_properties.get("/properties/1")
        assert r.status_code == 200
        body = r.json()
        assert body["score_id"] == 1
        assert body["county_name"] == "Ñuñoa"

    def test_get_communes(self, client_with_communes):
        r = client_with_communes.get("/properties/communes")
        assert r.status_code == 200
        communes = r.json()
        assert isinstance(communes, list)
        if communes:
            assert "county_name" in communes[0]
            assert "n_transactions" in communes[0]
            assert "pct_subvaloradas" in communes[0]


# ── Tests: /scores ────────────────────────────────────────────────────────────

class TestScoresEndpoints:
    def test_get_score_by_id(self, client_with_scores):
        r = client_with_scores.get("/scores/1")
        assert r.status_code == 200
        body = r.json()
        assert body["score_id"] == 1
        assert "opportunity_score" in body

    def test_score_detail_has_shap(self, client_with_scores):
        r = client_with_scores.get("/scores/1")
        assert r.status_code == 200
        body = r.json()
        if body.get("shap_top_features"):
            for feat in body["shap_top_features"]:
                assert "feature" in feat
                assert "shap" in feat
                assert "direction" in feat
                assert feat["direction"] in ("up", "down")

    def test_top_scores(self, client_with_scores):
        r = client_with_scores.get("/scores/top?n=5")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_top_scores_invalid_n(self, client_with_scores):
        r = client_with_scores.get("/scores/top?n=9999")
        assert r.status_code == 422

    def test_score_summary(self, client_with_summary):
        r = client_with_summary.get("/scores/summary")
        assert r.status_code == 200
        body = r.json()
        assert "total_scored" in body
        assert "mean_score" in body
        assert "high_opp_count" in body
        assert "model_version" in body

    def test_score_summary_value_ranges(self, client_with_summary):
        r = client_with_summary.get("/scores/summary")
        body = r.json()
        assert body["total_scored"] >= 0
        if body["mean_score"] is not None:
            assert 0.0 <= body["mean_score"] <= 1.0
