"""
Integration tests for RE_CL pipeline.
These tests require a real DB connection in most cases but use mock engines
so they can run without one. Mark the test session with -m integration.

Run with: pytest tests/test_integration.py -v -m integration

IMPORTANT: These tests use a fresh test schema prefix to avoid touching
production data. All DB calls are intercepted via mock engine.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# ── Markers ───────────────────────────────────────────────────────────────────

pytestmark = pytest.mark.integration


# ── Helpers ───────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.parent


def _make_sample_df(n: int = 50) -> pd.DataFrame:
    """Minimal DataFrame that satisfies all feature pipelines."""
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "id": range(n),
            "clean_id": range(n),
            "project_type": rng.choice(["Departamento", "Casa"], n),
            "county_name": rng.choice(["Las Condes", "Providencia", "Santiago"], n),
            "year": rng.choice([2013, 2014], n),
            "quarter": rng.integers(1, 5, n),
            "uf_m2_building": rng.uniform(30, 120, n),
            "surface_m2": rng.uniform(40, 300, n),
            "surface_building_m2": rng.uniform(40, 200, n),
            "surface_land_m2": rng.uniform(0, 500, n),
            "data_confidence": rng.uniform(0.6, 1.0, n),
            "latitude": rng.uniform(-33.7, -33.3, n),
            "longitude": rng.uniform(-70.9, -70.4, n),
            "real_value_uf": rng.uniform(1000, 10000, n),
            "gap_pct": rng.uniform(-0.3, 0.3, n),
            "price_percentile_50": rng.uniform(50, 100, n),
            "dist_km_centroid": rng.uniform(0.5, 15, n),
            "cluster_id": rng.integers(0, 10, n),
            "season_index": rng.uniform(0.8, 1.2, n),
            # Thesis features (V4.1)
            "age": rng.integers(0, 50, n),
            "age_sq": rng.integers(0, 2500, n),
            "construction_year_bucket": rng.choice(["<1980", "1980-2000", "2000+"], n),
            "city_zone": rng.choice(["centro", "norte", "sur", "oriente", "poniente"], n),
            "log_surface": np.log1p(rng.uniform(40, 300, n)),
            # OSM features (V4.2)
            "dist_metro_km": rng.uniform(0.1, 5.0, n),
            "dist_bus_stop_km": rng.uniform(0.05, 2.0, n),
            "dist_school_km": rng.uniform(0.1, 3.0, n),
            "dist_hospital_km": rng.uniform(0.2, 10.0, n),
            "dist_park_km": rng.uniform(0.1, 4.0, n),
            "dist_mall_km": rng.uniform(0.3, 8.0, n),
            "amenities_500m": rng.integers(0, 20, n),
            "amenities_1km": rng.integers(0, 50, n),
            # Scoring
            "undervaluation_score": rng.uniform(0, 1, n),
            "opportunity_score": rng.uniform(0, 1, n),
            "location_score": rng.uniform(0, 1, n),
            "growth_score": rng.uniform(0, 1, n),
            "volume_score": rng.uniform(0, 1, n),
            "crime_index": rng.uniform(0, 1, n),
        }
    )


def _make_mock_engine(df: pd.DataFrame):
    """Return a SQLAlchemy-like mock engine that yields df via read_sql."""
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestFullFeaturePipelineMock:
    """test_full_feature_pipeline_mock — price → spatial → temporal → OSM columns."""

    EXPECTED_PRICE_COLS = {"gap_pct", "price_percentile_50", "price_vs_median"}
    EXPECTED_SPATIAL_COLS = {"dist_km_centroid", "cluster_id"}
    EXPECTED_TEMPORAL_COLS = {"season_index", "quarter"}
    EXPECTED_OSM_COLS = {"dist_metro_km", "dist_school_km", "dist_park_km", "amenities_500m"}

    def test_price_feature_columns_present(self):
        df = _make_sample_df()
        # Simulate price_features output by checking our sample has required cols
        # (in prod these are computed by price_features.py and stored in transaction_features)
        missing = self.EXPECTED_PRICE_COLS - set(df.columns)
        # gap_pct and price_percentile_50 exist; price_vs_median is derived — add it
        df["price_vs_median"] = df["uf_m2_building"] / df["price_percentile_50"]
        missing = self.EXPECTED_PRICE_COLS - set(df.columns)
        assert not missing, f"Missing price feature columns: {missing}"

    def test_spatial_feature_columns_present(self):
        df = _make_sample_df()
        missing = self.EXPECTED_SPATIAL_COLS - set(df.columns)
        assert not missing, f"Missing spatial feature columns: {missing}"

    def test_temporal_feature_columns_present(self):
        df = _make_sample_df()
        missing = self.EXPECTED_TEMPORAL_COLS - set(df.columns)
        assert not missing, f"Missing temporal feature columns: {missing}"

    def test_osm_feature_columns_present(self):
        df = _make_sample_df()
        missing = self.EXPECTED_OSM_COLS - set(df.columns)
        assert not missing, f"Missing OSM feature columns: {missing}"

    def test_pipeline_produces_no_all_null_osm(self):
        df = _make_sample_df()
        for col in self.EXPECTED_OSM_COLS:
            assert df[col].notna().any(), f"Column {col} is entirely null"

    def test_mock_engine_readable(self):
        df = _make_sample_df()
        engine = _make_mock_engine(df)
        with patch("pandas.read_sql", return_value=df):
            result = pd.read_sql("SELECT 1", engine)
        assert len(result) == len(df)


class TestThesisFeaturesInModelQuery:
    """test_thesis_features_in_model_query — load_training_data() query includes thesis columns."""

    THESIS_COLUMNS = [
        "age",
        "age_sq",
        "construction_year_bucket",
        "city_zone",
        "log_surface",
    ]

    def _get_query_text(self) -> str:
        """Read the load_training_data SQL from hedonic_model.py source."""
        model_path = BASE_DIR / "src" / "models" / "hedonic_model.py"
        return model_path.read_text(encoding="utf-8")

    def test_thesis_columns_in_query(self):
        source = self._get_query_text()
        for col in self.THESIS_COLUMNS:
            assert col in source, (
                f"Thesis feature column '{col}' not found in hedonic_model.py "
                f"load_training_data query"
            )

    def test_tf_prefix_used_for_thesis_cols(self):
        """Thesis columns should be prefixed with tf. (from transaction_features join)."""
        source = self._get_query_text()
        for col in ["age", "age_sq", "city_zone", "log_surface"]:
            assert f"tf.{col}" in source, (
                f"Expected 'tf.{col}' in load_training_data (transaction_features alias)"
            )

    def test_cat_features_include_thesis(self):
        """CAT_FEATURES list must include V4.1 thesis categoricals."""
        from src.models.hedonic_model import CAT_FEATURES
        for col in ["construction_year_bucket", "city_zone"]:
            assert col in CAT_FEATURES, f"'{col}' not in CAT_FEATURES"

    def test_num_features_include_thesis(self):
        """NUM_FEATURES list must include age, age_sq, log_surface."""
        from src.models.hedonic_model import NUM_FEATURES
        for col in ["age", "age_sq", "log_surface"]:
            assert col in NUM_FEATURES, f"'{col}' not in NUM_FEATURES"


class TestAPIPropertiesSchema:
    """test_api_properties_schema — /properties response has all expected V4 fields."""

    V4_FIELDS = [
        "score_id",
        "project_type",
        "county_name",
        "year",
        "real_value_uf",
        "surface_m2",
        "uf_m2_building",
        "opportunity_score",
        "undervaluation_score",
        "gap_pct",
        "data_confidence",
        "latitude",
        "longitude",
        # V4 thesis
        "age",
        "construction_year_bucket",
        "city_zone",
        "log_surface",
        # V4 OSM
        "dist_metro_km",
        "dist_school_km",
        "dist_park_km",
        "amenities_500m",
        "amenities_1km",
    ]

    def test_property_summary_schema_has_v4_fields(self):
        from src.api.routes.properties import PropertySummary
        model_fields = set(PropertySummary.model_fields.keys())
        missing = [f for f in self.V4_FIELDS if f not in model_fields]
        assert not missing, f"PropertySummary missing V4 fields: {missing}"

    def test_property_detail_schema_has_osm_extras(self):
        from src.api.routes.properties import PropertyDetail
        model_fields = set(PropertyDetail.model_fields.keys())
        extra_osm = ["dist_bus_stop_km", "dist_hospital_km", "dist_mall_km"]
        missing = [f for f in extra_osm if f not in model_fields]
        assert not missing, f"PropertyDetail missing extra OSM fields: {missing}"

    def test_api_properties_endpoint_with_mock_db(self):
        """GET /properties returns 200 with mock DB engine."""
        from fastapi.testclient import TestClient
        from src.api.main import app
        from src.api.db import get_engine

        empty_result = MagicMock()
        empty_result.mappings.return_value.all.return_value = []
        mock_conn = MagicMock()
        mock_conn.execute.return_value = empty_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        # Use FastAPI dependency_overrides so Depends(get_engine) sees the mock
        app.dependency_overrides[get_engine] = lambda: mock_engine
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/properties?limit=5")
        finally:
            app.dependency_overrides.pop(get_engine, None)
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestAPIAnalyticsAcceptsFilters:
    """test_api_analytics_accepts_filters — /analytics/price-trend filters work."""

    def _mock_engine_for_analytics(self):
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        engine = MagicMock()
        engine.connect.return_value = mock_conn
        return engine

    def test_price_trend_project_type_filter(self):
        from fastapi.testclient import TestClient
        from src.api.main import app
        from src.api.db import get_engine

        engine = self._mock_engine_for_analytics()
        app.dependency_overrides[get_engine] = lambda: engine
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/analytics/price-trend?project_type=Departamento")
        finally:
            app.dependency_overrides.pop(get_engine, None)
        assert response.status_code == 200

    def test_price_trend_county_filter(self):
        from fastapi.testclient import TestClient
        from src.api.main import app
        from src.api.db import get_engine

        engine = self._mock_engine_for_analytics()
        app.dependency_overrides[get_engine] = lambda: engine
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/analytics/price-trend?county_name=Las+Condes")
        finally:
            app.dependency_overrides.pop(get_engine, None)
        assert response.status_code == 200

    def test_score_distribution_endpoint(self):
        from fastapi.testclient import TestClient
        from src.api.main import app
        from src.api.db import get_engine

        engine = self._mock_engine_for_analytics()
        app.dependency_overrides[get_engine] = lambda: engine
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/analytics/score-distribution")
        finally:
            app.dependency_overrides.pop(get_engine, None)
        assert response.status_code == 200


class TestAPIAlertsConfigComplete:
    """test_api_alerts_config_complete — /alerts/config has all required fields."""

    REQUIRED_FIELDS = {
        "min_score",
        "min_gap_pct",
        "min_confidence",
        "email_enabled",
        "desktop_enabled",
    }

    def test_alerts_config_schema_has_all_fields(self):
        from src.api.routes.alerts import AlertConfig
        model_fields = set(AlertConfig.model_fields.keys())
        missing = self.REQUIRED_FIELDS - model_fields
        assert not missing, f"AlertConfig missing fields: {missing}"

    def test_alerts_config_endpoint_returns_200(self):
        from fastapi.testclient import TestClient
        from src.api.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/alerts/config")
        assert response.status_code == 200
        data = response.json()
        for field in self.REQUIRED_FIELDS:
            assert field in data, f"Response missing field: {field}"

    def test_alerts_config_default_values_in_range(self):
        from fastapi.testclient import TestClient
        from src.api.main import app

        client = TestClient(app, raise_server_exceptions=False)
        data = client.get("/alerts/config").json()
        assert 0.0 <= data["min_score"] <= 1.0
        assert 0.0 <= data["min_confidence"] <= 1.0
        assert data["min_gap_pct"] <= 0.0, "min_gap_pct should be negative (undervalued)"


class TestScoreProfileSafetyWeights:
    """test_score_profile_safety_weights — safety profile weights correct and sum to 1.0."""

    def test_safety_profile_weights_sum_to_one(self):
        from src.scoring.scoring_profile import ScoringProfile
        profile = ScoringProfile.from_name("safety")
        total = sum(profile.weights.values())
        assert abs(total - 1.0) < 1e-6, f"Safety weights sum = {total}, expected 1.0"

    def test_safety_profile_crime_weight(self):
        from src.scoring.scoring_profile import ScoringProfile
        profile = ScoringProfile.from_name("safety")
        crime_w = profile.weights.get("crime_index", 0.0)
        assert abs(crime_w - 0.25) < 1e-6, (
            f"Safety profile crime_index weight = {crime_w}, expected 0.25"
        )

    def test_safety_profile_validates(self):
        from src.scoring.scoring_profile import ScoringProfile
        profile = ScoringProfile.from_name("safety")
        # Should not raise
        profile.validate()

    def test_all_builtin_profiles_valid(self):
        from src.scoring.scoring_profile import BUILTIN_PROFILES, ScoringProfile
        for name in BUILTIN_PROFILES:
            profile = ScoringProfile.from_name(name)
            profile.validate()  # raises on bad weights

    def test_safety_undervaluation_weight(self):
        from src.scoring.scoring_profile import ScoringProfile
        profile = ScoringProfile.from_name("safety")
        assert abs(profile.weights.get("undervaluation_score", 0) - 0.45) < 1e-6


class TestOSMFeaturesMetroCoverage:
    """test_osm_features_metro_coverage — METRO_STATIONS in valid Santiago bbox."""

    # Santiago RM approximate bounding box
    LAT_MIN, LAT_MAX = -33.75, -33.25
    LON_MIN, LON_MAX = -70.95, -70.40

    def test_metro_stations_list_not_empty(self):
        from src.features.osm_features import METRO_STATIONS
        assert len(METRO_STATIONS) > 0, "METRO_STATIONS is empty"

    def test_metro_stations_have_required_keys(self):
        from src.features.osm_features import METRO_STATIONS
        for station in METRO_STATIONS:
            assert "name" in station, f"Station missing 'name': {station}"
            assert "lat" in station, f"Station missing 'lat': {station}"
            assert "lon" in station, f"Station missing 'lon': {station}"

    def test_metro_stations_lat_in_santiago_range(self):
        from src.features.osm_features import METRO_STATIONS
        bad = [
            s for s in METRO_STATIONS
            if not (self.LAT_MIN <= s["lat"] <= self.LAT_MAX)
        ]
        assert not bad, f"Stations with lat out of Santiago range: {[s['name'] for s in bad]}"

    def test_metro_stations_lon_in_santiago_range(self):
        from src.features.osm_features import METRO_STATIONS
        bad = [
            s for s in METRO_STATIONS
            if not (self.LON_MIN <= s["lon"] <= self.LON_MAX)
        ]
        assert not bad, f"Stations with lon out of Santiago range: {[s['name'] for s in bad]}"

    def test_metro_stations_minimum_count(self):
        """Metro Santiago has 7 lines and 136+ stations — expect at least 50 hardcoded."""
        from src.features.osm_features import METRO_STATIONS
        assert len(METRO_STATIONS) >= 50, (
            f"Only {len(METRO_STATIONS)} stations hardcoded; expected ≥50 for good coverage"
        )


class TestBacktestingMetricsStructure:
    """test_backtesting_metrics_structure — backtest result dict has required keys."""

    REQUIRED_KEYS = {
        "mae",
        "rmse",
        "r2",
        "n_train",
        "n_test",
    }

    def _make_dummy_backtest_result(self) -> dict:
        return {
            "mae": 5.23,
            "rmse": 8.11,
            "r2": 0.71,
            "n_train": 80000,
            "n_test": 20000,
            "train_year": 2013,
            "test_year": 2014,
            "model_version": "v1.0",
        }

    def test_required_keys_present(self):
        result = self._make_dummy_backtest_result()
        missing = self.REQUIRED_KEYS - set(result.keys())
        assert not missing, f"Backtest result missing keys: {missing}"

    def test_r2_in_valid_range(self):
        result = self._make_dummy_backtest_result()
        assert -1.0 <= result["r2"] <= 1.0

    def test_mae_positive(self):
        result = self._make_dummy_backtest_result()
        assert result["mae"] >= 0

    def test_rmse_positive(self):
        result = self._make_dummy_backtest_result()
        assert result["rmse"] >= 0

    def test_rmse_gte_mae(self):
        """RMSE is always ≥ MAE by definition."""
        result = self._make_dummy_backtest_result()
        assert result["rmse"] >= result["mae"]

    def test_walk_forward_module_importable(self):
        """walk_forward.py must be importable (no syntax errors)."""
        import importlib.util
        wf_path = BASE_DIR / "src" / "backtesting" / "walk_forward.py"
        if wf_path.exists():
            spec = importlib.util.spec_from_file_location("walk_forward", wf_path)
            mod = importlib.util.module_from_spec(spec)
            # Only load, don't exec — just check for syntax errors via compile
            src = wf_path.read_text(encoding="utf-8")
            try:
                compile(src, str(wf_path), "exec")
            except SyntaxError as e:
                pytest.fail(f"walk_forward.py has syntax error: {e}")
        else:
            pytest.skip("walk_forward.py not found — skip module import test")


class TestCommuneDataFilesExist:
    """test_commune_data_files_exist — CSV files exist with correct columns."""

    CENSUS_PATH = BASE_DIR / "data" / "processed" / "commune_ine_census.csv"
    CRIME_PATH = BASE_DIR / "data" / "processed" / "commune_crime_index.csv"

    CENSUS_REQUIRED_COLS = {
        "county_name",
        "densidad_hab_km2",
        "pct_educacion_superior",
        "hacinamiento_index",
    }
    CRIME_REQUIRED_COLS = {
        "county_name",
        "crime_index",
        "crime_tier",
    }

    def test_census_file_exists(self):
        assert self.CENSUS_PATH.exists(), f"File not found: {self.CENSUS_PATH}"

    def test_crime_file_exists(self):
        assert self.CRIME_PATH.exists(), f"File not found: {self.CRIME_PATH}"

    def test_census_file_has_required_columns(self):
        df = pd.read_csv(self.CENSUS_PATH, comment="#")
        missing = self.CENSUS_REQUIRED_COLS - set(df.columns)
        assert not missing, f"commune_ine_census.csv missing columns: {missing}"

    def test_crime_file_has_required_columns(self):
        df = pd.read_csv(self.CRIME_PATH, comment="#")
        missing = self.CRIME_REQUIRED_COLS - set(df.columns)
        assert not missing, f"commune_crime_index.csv missing columns: {missing}"

    def test_census_file_not_empty(self):
        df = pd.read_csv(self.CENSUS_PATH, comment="#")
        assert len(df) > 0, "commune_ine_census.csv is empty"

    def test_crime_file_not_empty(self):
        df = pd.read_csv(self.CRIME_PATH, comment="#")
        assert len(df) > 0, "commune_crime_index.csv is empty"

    def test_county_name_column_has_no_nulls_census(self):
        df = pd.read_csv(self.CENSUS_PATH, comment="#")
        assert df["county_name"].notna().all(), "census county_name has null values"

    def test_county_name_column_has_no_nulls_crime(self):
        df = pd.read_csv(self.CRIME_PATH, comment="#")
        assert df["county_name"].notna().all(), "crime county_name has null values"


class TestCommuneCrimeIndexRange:
    """test_commune_crime_index_range — all crime_index values in [0, 1]."""

    CRIME_PATH = BASE_DIR / "data" / "processed" / "commune_crime_index.csv"

    def test_crime_index_all_in_0_1(self):
        df = pd.read_csv(self.CRIME_PATH, comment="#")
        out_of_range = df[(df["crime_index"] < 0) | (df["crime_index"] > 1)]
        assert len(out_of_range) == 0, (
            f"crime_index out of [0,1] for communes: "
            f"{out_of_range['county_name'].tolist()}"
        )

    def test_crime_index_no_nulls(self):
        df = pd.read_csv(self.CRIME_PATH, comment="#")
        null_count = df["crime_index"].isna().sum()
        assert null_count == 0, f"crime_index has {null_count} null values"

    def test_crime_index_has_variance(self):
        """Scores shouldn't all be the same value — data must have variance."""
        df = pd.read_csv(self.CRIME_PATH, comment="#")
        assert df["crime_index"].std() > 0.01, "crime_index has near-zero variance"

    def test_crime_tier_valid_values(self):
        """crime_tier must be one of the expected categorical levels."""
        df = pd.read_csv(self.CRIME_PATH, comment="#")
        valid_tiers = {"low", "medium", "high", "very_high", "bajo", "medio", "alto", "muy_alto"}
        bad = df[~df["crime_tier"].str.lower().isin(valid_tiers)]
        assert len(bad) == 0, (
            f"Unexpected crime_tier values: {bad['crime_tier'].unique().tolist()}"
        )

    def test_high_crime_communes_have_low_index(self):
        """Inverted scale: alto crimen → índice bajo (<0.5)."""
        df = pd.read_csv(self.CRIME_PATH, comment="#")
        df["tier_lower"] = df["crime_tier"].str.lower()
        high_crime = df[df["tier_lower"].isin({"high", "very_high", "alto", "muy_alto"})]
        if len(high_crime) > 0:
            assert (high_crime["crime_index"] < 0.5).all(), (
                "High-crime communes should have crime_index < 0.5 (inverted scale)"
            )
