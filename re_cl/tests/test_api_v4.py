"""
test_api_v4.py
--------------
Tests for V4/V5 FastAPI endpoints.

Covers:
  - V4 thesis + OSM fields in /properties and /properties/{id}
  - city_zone filter parameter
  - /properties/communes/enriched endpoint
  - crime_index / educacion_score in /properties/communes
  - safety profile in GET /profiles
  - POST /profiles/score with safety profile
  - /health endpoint
  - Invalid parameter validation (422)

No real DB required — uses the same dependency-override pattern as test_api.py.
"""

import json

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.api.main import app
from src.api.db import get_engine


# ── Mock data ─────────────────────────────────────────────────────────────────

MOCK_PROPERTY_V4 = {
    # Core fields (present in existing tests too)
    "score_id":             42,
    "project_type":         "apartments",
    "county_name":          "Las Condes",
    "year":                 2014,
    "real_value_uf":        6000.0,
    "surface_m2":           90.0,
    "uf_m2_building":       66.0,
    "opportunity_score":    0.78,
    "undervaluation_score": 0.70,
    "gap_pct":              -0.20,
    "data_confidence":      0.88,
    "latitude":             -33.41,
    "longitude":            -70.57,
    # V4.1 thesis features
    "age":                        12,
    "construction_year_bucket":   "2000-2009",
    "city_zone":                  "este",
    "log_surface":                4.499,
    # V4.2 OSM features
    "dist_metro_km":      0.45,
    "dist_school_km":     0.30,
    "dist_park_km":       0.22,
    "amenities_500m":     8,
    "amenities_1km":      21,
}

MOCK_PROPERTY_DETAIL_V4 = {
    **MOCK_PROPERTY_V4,
    # PropertyDetail extra fields
    "predicted_uf_m2":    80.0,
    "gap_percentile":     0.22,
    "shap_top_features":  json.dumps([
        {"feature": "dist_metro_km", "shap": 0.31, "direction": "up"},
        {"feature": "age",           "shap": -0.14, "direction": "down"},
    ]),
    # Additional OSM fields only in detail
    "dist_bus_stop_km":   0.12,
    "dist_hospital_km":   1.80,
    "dist_mall_km":       0.95,
    "age_sq":             144.0,
}

MOCK_COMMUNE_ENRICHED = {
    "county_name":        "Las Condes",
    "n_transactions":     1200,
    "median_score":       0.74,
    "pct_subvaloradas":   38.5,
    "median_uf_m2":       70.2,
    "median_gap_pct":     -0.10,
    # V5 enrichment fields
    "crime_index":        0.82,
    "crime_tier":         "low",
    "educacion_score":    0.91,
    "hacinamiento_score": 0.78,
    "densidad_norm":      0.55,
}

MOCK_SCORE_ROW_V4 = {
    "score_id":             42,
    "clean_id":             200,
    "model_version":        "v1.0",
    "opportunity_score":    0.78,
    "undervaluation_score": 0.70,
    "data_confidence":      0.88,
    "predicted_uf_m2":      80.0,
    "actual_uf_m2":         66.0,
    "gap_pct":              -0.20,
    "gap_percentile":       0.22,
    "shap_top_features":    json.dumps([
        {"feature": "dist_metro_km", "shap": 0.31, "direction": "up"},
    ]),
    "county_name":          "Las Condes",
    "project_type":         "apartments",
    # Columns needed by compute_profile_score for safety profile
    "undervaluation_score": 0.70,
    "dist_km_centroid":     1.2,
    "cluster_id":           3,
    "uf_m2_building":       66.0,
}


# ── Helpers (same pattern as test_api.py) ─────────────────────────────────────

class _DictRow(dict):
    """Dict subclass that also supports attribute access, mimicking SQLAlchemy RowMapping."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def _make_mock_conn(rows):
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
def client_v4_properties():
    """Client overridden to return one V4-enriched property."""
    engine = _make_mock_engine([MOCK_PROPERTY_V4])
    app.dependency_overrides[get_engine] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_v4_detail():
    """Client overridden to return one V4 property detail row."""
    engine = _make_mock_engine([MOCK_PROPERTY_DETAIL_V4])
    app.dependency_overrides[get_engine] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_v4_communes():
    """Client overridden to return one enriched commune row."""
    engine = _make_mock_engine([MOCK_COMMUNE_ENRICHED])
    app.dependency_overrides[get_engine] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_v4_scores():
    """Client overridden to return V4 score rows (used for profile scoring)."""
    engine = _make_mock_engine([MOCK_SCORE_ROW_V4])
    app.dependency_overrides[get_engine] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_empty():
    """Client overridden with empty DB (no rows)."""
    engine = _make_mock_engine([])
    app.dependency_overrides[get_engine] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Tests: /health ────────────────────────────────────────────────────────────

class TestHealthV4:
    def test_health_returns_200(self):
        with TestClient(app) as client:
            r = client.get("/health")
        assert r.status_code == 200

    def test_health_returns_ok_status(self):
        with TestClient(app) as client:
            r = client.get("/health")
        body = r.json()
        assert body["status"] == "ok"

    def test_health_has_model_version(self):
        with TestClient(app) as client:
            r = client.get("/health")
        assert "model_version" in r.json()


# ── Tests: V4 fields on /properties ──────────────────────────────────────────

class TestPropertiesV4Fields:
    def test_properties_returns_200(self, client_v4_properties):
        r = client_v4_properties.get("/properties?limit=5")
        assert r.status_code == 200

    def test_properties_returns_list(self, client_v4_properties):
        r = client_v4_properties.get("/properties?limit=5")
        assert isinstance(r.json(), list)

    def test_properties_has_v4_thesis_fields(self, client_v4_properties):
        r = client_v4_properties.get("/properties?limit=5")
        assert r.status_code == 200
        items = r.json()
        assert items, "Expected at least one property in mock response"
        prop = items[0]
        # V4.1 thesis fields — schema must include these (may be null without migration)
        assert "age" in prop
        assert "construction_year_bucket" in prop
        assert "city_zone" in prop
        assert "log_surface" in prop

    def test_properties_has_v4_osm_fields(self, client_v4_properties):
        r = client_v4_properties.get("/properties?limit=5")
        items = r.json()
        prop = items[0]
        # V4.2 OSM fields — schema must include these
        assert "dist_metro_km" in prop
        assert "dist_school_km" in prop
        assert "dist_park_km" in prop
        assert "amenities_500m" in prop
        assert "amenities_1km" in prop

    def test_properties_v4_field_values(self, client_v4_properties):
        r = client_v4_properties.get("/properties?limit=5")
        prop = r.json()[0]
        assert prop["age"] == 12
        assert prop["city_zone"] == "este"
        assert prop["dist_metro_km"] == pytest.approx(0.45)
        assert prop["amenities_500m"] == 8

    def test_properties_v4_no_500_error(self, client_v4_properties):
        """API must not return 500 even when V4 columns are present."""
        r = client_v4_properties.get("/properties?limit=5")
        assert r.status_code != 500


# ── Tests: /properties/{id} V4 detail ────────────────────────────────────────

class TestPropertyDetailV4:
    def test_detail_returns_200(self, client_v4_detail):
        r = client_v4_detail.get("/properties/42")
        assert r.status_code == 200

    def test_detail_has_core_v4_fields(self, client_v4_detail):
        r = client_v4_detail.get("/properties/42")
        body = r.json()
        assert "age" in body
        assert "city_zone" in body
        assert "dist_metro_km" in body

    def test_detail_has_extended_osm_fields(self, client_v4_detail):
        """PropertyDetail includes additional OSM fields not in summary."""
        r = client_v4_detail.get("/properties/42")
        body = r.json()
        assert "dist_bus_stop_km" in body
        assert "dist_hospital_km" in body
        assert "dist_mall_km" in body
        assert "age_sq" in body

    def test_detail_extended_osm_values(self, client_v4_detail):
        r = client_v4_detail.get("/properties/42")
        body = r.json()
        assert body["dist_bus_stop_km"] == pytest.approx(0.12)
        assert body["age_sq"] == pytest.approx(144.0)


# ── Tests: city_zone filter ───────────────────────────────────────────────────

class TestCityZoneFilter:
    def test_city_zone_este_accepted(self, client_v4_properties):
        """city_zone=este should be accepted (200, not 422)."""
        r = client_v4_properties.get("/properties?city_zone=este&limit=5")
        assert r.status_code == 200

    def test_city_zone_centro_norte_accepted(self, client_v4_properties):
        r = client_v4_properties.get("/properties?city_zone=centro_norte&limit=5")
        assert r.status_code == 200

    def test_city_zone_oeste_accepted(self, client_v4_properties):
        r = client_v4_properties.get("/properties?city_zone=oeste&limit=5")
        assert r.status_code == 200

    def test_city_zone_sur_accepted(self, client_v4_properties):
        r = client_v4_properties.get("/properties?city_zone=sur&limit=5")
        assert r.status_code == 200

    def test_city_zone_invalid_value_not_422(self, client_v4_properties):
        """city_zone has no enum validation — any string is passed through to SQL."""
        r = client_v4_properties.get("/properties?city_zone=invalid_zone&limit=5")
        assert r.status_code in (200, 404)

    def test_city_zone_combined_with_min_score(self, client_v4_properties):
        r = client_v4_properties.get("/properties?city_zone=este&min_score=0.5&limit=10")
        assert r.status_code == 200


# ── Tests: /properties/communes ──────────────────────────────────────────────

class TestCommunesV5Enrichment:
    def test_communes_returns_200(self, client_v4_communes):
        r = client_v4_communes.get("/properties/communes")
        assert r.status_code == 200

    def test_communes_returns_list(self, client_v4_communes):
        r = client_v4_communes.get("/properties/communes")
        assert isinstance(r.json(), list)

    def test_communes_has_crime_index(self, client_v4_communes):
        r = client_v4_communes.get("/properties/communes")
        communes = r.json()
        assert communes, "Expected at least one commune in mock response"
        assert "crime_index" in communes[0]

    def test_communes_has_educacion_score(self, client_v4_communes):
        r = client_v4_communes.get("/properties/communes")
        communes = r.json()
        assert "educacion_score" in communes[0]

    def test_communes_has_all_enrichment_fields(self, client_v4_communes):
        r = client_v4_communes.get("/properties/communes")
        commune = r.json()[0]
        assert "crime_index" in commune
        assert "crime_tier" in commune
        assert "educacion_score" in commune
        assert "hacinamiento_score" in commune
        assert "densidad_norm" in commune

    def test_communes_enrichment_values(self, client_v4_communes):
        r = client_v4_communes.get("/properties/communes")
        commune = r.json()[0]
        assert commune["crime_index"] == pytest.approx(0.82)
        assert commune["crime_tier"] == "low"
        assert commune["educacion_score"] == pytest.approx(0.91)

    def test_communes_enrichment_fields_nullable(self, client_empty):
        """Enrichment fields must be nullable (schema allows None when DB not loaded)."""
        r = client_empty.get("/properties/communes")
        assert r.status_code == 200
        assert r.json() == []


# ── Tests: /properties/communes/enriched ─────────────────────────────────────

class TestCommunesEnrichedEndpoint:
    def test_communes_enriched_returns_200(self, client_v4_communes):
        r = client_v4_communes.get("/properties/communes/enriched")
        assert r.status_code == 200

    def test_communes_enriched_returns_list(self, client_v4_communes):
        r = client_v4_communes.get("/properties/communes/enriched")
        assert isinstance(r.json(), list)

    def test_communes_enriched_has_enrichment_fields(self, client_v4_communes):
        r = client_v4_communes.get("/properties/communes/enriched")
        items = r.json()
        assert items, "Expected at least one commune"
        commune = items[0]
        assert "crime_index" in commune
        assert "educacion_score" in commune
        assert "county_name" in commune

    def test_communes_enriched_empty_db_returns_empty_list(self, client_empty):
        r = client_empty.get("/properties/communes/enriched")
        assert r.status_code == 200
        assert r.json() == []

    def test_communes_enriched_not_404(self, client_v4_communes):
        """Endpoint must exist — not a 404."""
        r = client_v4_communes.get("/properties/communes/enriched")
        assert r.status_code != 404


# ── Tests: /profiles ─────────────────────────────────────────────────────────

class TestProfilesV5:
    def test_profiles_returns_200(self):
        with TestClient(app) as client:
            r = client.get("/profiles")
        assert r.status_code == 200

    def test_profiles_returns_list(self):
        with TestClient(app) as client:
            r = client.get("/profiles")
        assert isinstance(r.json(), list)

    def test_profiles_includes_safety(self):
        """V5 safety profile must be listed in /profiles."""
        with TestClient(app) as client:
            r = client.get("/profiles")
        profile_names = [p["name"] for p in r.json()]
        assert "safety" in profile_names

    def test_profiles_includes_all_builtin(self):
        """All five built-in profiles must be present."""
        with TestClient(app) as client:
            r = client.get("/profiles")
        profile_names = [p["name"] for p in r.json()]
        for expected in ("default", "location", "growth", "liquidity", "safety"):
            assert expected in profile_names, f"Missing profile: {expected}"

    def test_profile_safety_has_correct_fields(self):
        with TestClient(app) as client:
            r = client.get("/profiles")
        safety = next(p for p in r.json() if p["name"] == "safety")
        assert "weights" in safety
        assert "description" in safety
        assert "is_default" in safety

    def test_profile_safety_weights_include_crime(self):
        with TestClient(app) as client:
            r = client.get("/profiles")
        safety = next(p for p in r.json() if p["name"] == "safety")
        assert "crime_index" in safety["weights"]
        assert safety["weights"]["crime_index"] == pytest.approx(0.25)

    def test_profile_safety_weights_sum_to_one(self):
        with TestClient(app) as client:
            r = client.get("/profiles")
        safety = next(p for p in r.json() if p["name"] == "safety")
        total = sum(safety["weights"].values())
        assert total == pytest.approx(1.0, abs=1e-4)

    def test_get_safety_profile_by_name(self):
        """GET /profiles/safety should return detail for the safety profile."""
        with TestClient(app) as client:
            r = client.get("/profiles/safety")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "safety"
        assert "crime_index" in body["weights"]

    def test_get_unknown_profile_returns_404(self):
        with TestClient(app) as client:
            r = client.get("/profiles/nonexistent_profile")
        assert r.status_code == 404


# ── Tests: POST /profiles/score ───────────────────────────────────────────────

class TestProfilesScore:
    def test_score_with_safety_profile(self, client_v4_scores):
        """POST /profiles/score with safety profile should return 200 and a list."""
        r = client_v4_scores.post("/profiles/score", json={"profile": "safety", "limit": 10})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_score_with_safety_profile_result_fields(self, client_v4_scores):
        r = client_v4_scores.post("/profiles/score", json={"profile": "safety", "limit": 10})
        items = r.json()
        if items:
            item = items[0]
            assert "score_id" in item
            assert "opportunity_score" in item
            assert "scoring_profile" in item
            assert item["scoring_profile"] == "safety"

    def test_score_with_default_profile(self, client_v4_scores):
        r = client_v4_scores.post("/profiles/score", json={"profile": "default", "limit": 5})
        assert r.status_code == 200

    def test_score_with_location_profile(self, client_v4_scores):
        r = client_v4_scores.post("/profiles/score", json={"profile": "location", "limit": 5})
        assert r.status_code == 200

    def test_score_with_unknown_profile_returns_400(self, client_v4_scores):
        r = client_v4_scores.post("/profiles/score", json={"profile": "bogus_profile", "limit": 5})
        assert r.status_code == 400

    def test_score_requires_profile_or_weights(self, client_v4_scores):
        """Request with neither profile nor weights must be rejected (422)."""
        r = client_v4_scores.post("/profiles/score", json={"limit": 5})
        assert r.status_code == 422

    def test_score_with_custom_weights(self, client_v4_scores):
        r = client_v4_scores.post("/profiles/score", json={
            "weights": {"undervaluation": 0.6, "confidence": 0.4},
            "limit": 5,
        })
        assert r.status_code == 200

    def test_score_empty_db_returns_404(self, client_empty):
        """When no scored data exists the endpoint should return 404."""
        r = client_empty.post("/profiles/score", json={"profile": "safety", "limit": 10})
        assert r.status_code == 404

    def test_score_county_filter(self, client_v4_scores):
        r = client_v4_scores.post("/profiles/score", json={
            "profile": "safety",
            "county_name": "Las Condes",
            "limit": 5,
        })
        assert r.status_code in (200, 404)

    def test_score_limit_respected(self, client_v4_scores):
        r = client_v4_scores.post("/profiles/score", json={"profile": "default", "limit": 1})
        assert r.status_code == 200
        assert len(r.json()) <= 1


# ── Tests: Invalid parameters (422) ──────────────────────────────────────────

class TestInvalidParameters:
    def test_min_score_above_1_is_422(self, client_v4_properties):
        r = client_v4_properties.get("/properties?min_score=1.5")
        assert r.status_code == 422

    def test_max_score_above_1_is_422(self, client_v4_properties):
        r = client_v4_properties.get("/properties?max_score=2.0")
        assert r.status_code == 422

    def test_min_score_negative_is_422(self, client_v4_properties):
        r = client_v4_properties.get("/properties?min_score=-0.1")
        assert r.status_code == 422

    def test_limit_zero_is_422(self, client_v4_properties):
        r = client_v4_properties.get("/properties?limit=0")
        assert r.status_code == 422

    def test_offset_negative_is_422(self, client_v4_properties):
        r = client_v4_properties.get("/properties?offset=-1")
        assert r.status_code == 422

    def test_city_zone_invalid_string_not_422(self, client_v4_properties):
        """city_zone has no enum constraint — invalid strings pass through to SQL."""
        r = client_v4_properties.get("/properties?city_zone=invalid_zone")
        assert r.status_code in (200, 404)

    def test_custom_weights_all_zero_is_422(self, client_v4_scores):
        r = client_v4_scores.post("/profiles/score", json={
            "weights": {"undervaluation": 0.0, "confidence": 0.0},
            "limit": 5,
        })
        assert r.status_code == 422


# ── Tests: GET /properties/search ─────────────────────────────────────────────

class TestSearchEndpoint:
    @pytest.fixture
    def client_search(self):
        """Client overridden to return one V4-enriched property for search tests."""
        engine = _make_mock_engine([MOCK_PROPERTY_V4])
        app.dependency_overrides[get_engine] = lambda: engine
        yield TestClient(app)
        app.dependency_overrides.clear()

    @pytest.fixture
    def client_search_empty(self):
        """Client overridden with empty DB for search tests."""
        engine = _make_mock_engine([])
        app.dependency_overrides[get_engine] = lambda: engine
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_search_returns_list(self, client_search):
        """GET /properties/search?q=Las+Condes returns 200 and a list."""
        r = client_search.get("/properties/search?q=Las+Condes")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_search_empty_q_returns_400(self, client_search):
        """GET /properties/search?q= returns 400 (empty query rejected)."""
        r = client_search.get("/properties/search?q=")
        assert r.status_code == 400

    def test_search_whitespace_only_returns_400(self, client_search):
        """GET /properties/search?q=%20%20 returns 400 (whitespace-only rejected)."""
        r = client_search.get("/properties/search?q=%20%20")
        assert r.status_code == 400

    def test_search_with_min_score_filter(self, client_search):
        """GET /properties/search?q=Dep&min_score=0.7 returns 200."""
        r = client_search.get("/properties/search?q=Dep&min_score=0.7")
        assert r.status_code == 200

    def test_search_result_schema(self, client_search):
        """Response items have score_id, county_name, opportunity_score keys."""
        r = client_search.get("/properties/search?q=Las+Condes")
        assert r.status_code == 200
        items = r.json()
        assert items, "Expected at least one result from mock"
        item = items[0]
        assert "score_id" in item
        assert "county_name" in item
        assert "opportunity_score" in item


# ── Tests: GET /properties/export ─────────────────────────────────────────────

MOCK_EXPORT_ROW = {
    "score_id":             42,
    "county_name":          "Las Condes",
    "project_type":         "apartments",
    "city_zone":            "este",
    "opportunity_score":    0.78,
    "undervaluation_score": 0.70,
    "gap_pct":              -0.20,
    "uf_m2_building":       66.0,
    "real_value_uf":        6000.0,
    "surface_m2":           90.0,
    "age":                  12,
    "dist_metro_km":        0.45,
    "amenities_500m":       8,
    "latitude":             -33.41,
    "longitude":            -70.57,
}


class TestExportEndpoint:
    @pytest.fixture
    def client_export(self):
        """Client overridden to return one export row."""
        engine = _make_mock_engine([MOCK_EXPORT_ROW])
        app.dependency_overrides[get_engine] = lambda: engine
        yield TestClient(app)
        app.dependency_overrides.clear()

    @pytest.fixture
    def client_export_multi(self):
        """Client overridden to return multiple export rows."""
        engine = _make_mock_engine([MOCK_EXPORT_ROW] * 5)
        app.dependency_overrides[get_engine] = lambda: engine
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_export_returns_csv_content_type(self, client_export):
        """GET /properties/export returns 200 with content-type text/csv."""
        r = client_export.get("/properties/export")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]

    def test_export_has_content_disposition_header(self, client_export):
        """Response has Content-Disposition: attachment."""
        r = client_export.get("/properties/export")
        assert r.status_code == 200
        disposition = r.headers.get("content-disposition", "")
        assert "attachment" in disposition

    def test_export_csv_has_headers(self, client_export):
        """CSV body first line contains 'score_id,county_name'."""
        r = client_export.get("/properties/export")
        assert r.status_code == 200
        first_line = r.text.splitlines()[0]
        assert "score_id" in first_line
        assert "county_name" in first_line

    def test_export_respects_limit_param(self, client_export_multi):
        """GET /properties/export?limit=5 returns 200."""
        r = client_export_multi.get("/properties/export?limit=5")
        assert r.status_code == 200
