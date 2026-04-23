"""
test_predict.py
---------------
Tests for POST /predict endpoint.
Model is fully mocked — no real pkl files or DB required.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)

# ── Shared payload ─────────────────────────────────────────────────────────────

VALID_PAYLOAD = {
    "project_type": "Departamento",
    "county_name": "Las Condes",
    "surface_m2": 80.0,
    "surface_building_m2": 75.0,
    "construction_year": 2005,
    "year": 2014,
    "quarter": 4,
    "dist_metro_km": 0.8,
    "dist_school_km": 0.5,
    "amenities_500m": 10,
}


def _mock_model():
    """Return a mock (model, encoders) tuple that predicts 85.0 UF/m²."""
    mock_model = MagicMock()
    mock_model.predict.return_value = [85.0]

    mock_encoders = {}
    for feat in ["project_type", "county_name", "construction_year_bucket", "city_zone"]:
        le = MagicMock()
        le.transform.return_value = [0]
        mock_encoders[feat] = le

    return mock_model, mock_encoders


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_predict_returns_503_when_no_model():
    """When get_model returns (None, None) the endpoint must respond 503."""
    with patch("src.api.routes.predict.get_model", return_value=(None, None)):
        resp = client.post("/predict", json=VALID_PAYLOAD)
    assert resp.status_code == 503
    assert "Model not loaded" in resp.json()["detail"]


def test_predict_valid_request_returns_200():
    """A well-formed request with a loaded model must return HTTP 200."""
    with patch("src.api.routes.predict.get_model", return_value=_mock_model()):
        resp = client.post("/predict", json=VALID_PAYLOAD)
    assert resp.status_code == 200


def test_predict_response_has_required_fields():
    """Response JSON must contain all required PredictResponse fields."""
    with patch("src.api.routes.predict.get_model", return_value=_mock_model()):
        resp = client.post("/predict", json=VALID_PAYLOAD)
    body = resp.json()
    for field in ("predicted_uf_m2", "predicted_uf_total", "confidence", "note"):
        assert field in body, f"Missing field: {field}"


def test_predict_uf_total_equals_m2_times_surface():
    """predicted_uf_total must equal predicted_uf_m2 × surface_building_m2."""
    with patch("src.api.routes.predict.get_model", return_value=_mock_model()):
        resp = client.post("/predict", json=VALID_PAYLOAD)
    body = resp.json()
    surface = VALID_PAYLOAD["surface_building_m2"]
    expected_total = round(body["predicted_uf_m2"] * surface, 2)
    assert abs(body["predicted_uf_total"] - expected_total) < 0.01


def test_predict_high_confidence_for_known_commune():
    """Las Condes with construction_year and surface > 30 m² → confidence 'high'."""
    payload = {**VALID_PAYLOAD, "county_name": "Las Condes", "surface_m2": 80.0, "construction_year": 2005}
    with patch("src.api.routes.predict.get_model", return_value=_mock_model()):
        resp = client.post("/predict", json=payload)
    assert resp.json()["confidence"] == "high"


def test_predict_low_confidence_when_no_construction_year():
    """Omitting construction_year should yield confidence != 'high' (low or medium)."""
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "construction_year"}
    with patch("src.api.routes.predict.get_model", return_value=_mock_model()):
        resp = client.post("/predict", json=payload)
    assert resp.json()["confidence"] != "high"


def test_predict_uses_surface_building_m2_when_provided():
    """When surface_building_m2 is given, predicted_uf_total uses that value."""
    payload = {**VALID_PAYLOAD, "surface_m2": 100.0, "surface_building_m2": 75.0}
    with patch("src.api.routes.predict.get_model", return_value=_mock_model()):
        resp = client.post("/predict", json=payload)
    body = resp.json()
    # 85.0 × 75.0 = 6375.0
    assert abs(body["predicted_uf_total"] - round(body["predicted_uf_m2"] * 75.0, 2)) < 0.01


def test_predict_defaults_surface_building_from_surface_m2():
    """When surface_building_m2 is absent, surface_m2 is used for uf_total."""
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "surface_building_m2"}
    payload["surface_m2"] = 90.0
    with patch("src.api.routes.predict.get_model", return_value=_mock_model()):
        resp = client.post("/predict", json=payload)
    body = resp.json()
    expected_total = round(body["predicted_uf_m2"] * 90.0, 2)
    assert abs(body["predicted_uf_total"] - expected_total) < 0.01
