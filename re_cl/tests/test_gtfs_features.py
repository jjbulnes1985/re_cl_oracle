"""
test_gtfs_features.py
---------------------
Tests for src/features/gtfs_features.py.
All tests are purely in-memory — no HTTP calls, no DB.
"""

import io
import pickle
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import requests


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_stops_df(n=5) -> pd.DataFrame:
    """Return a minimal GTFS stops DataFrame inside Santiago bbox."""
    return pd.DataFrame({
        "stop_id":   [f"T{i}" for i in range(n)],
        "stop_name": [f"Paradero {i}" for i in range(n)],
        "lat":       np.linspace(-33.4, -33.6, n),
        "lon":       np.linspace(-70.5, -70.7, n),
    })


def _make_gtfs_zip(stops_csv: str) -> bytes:
    """Pack stops_csv string into an in-memory GTFS zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("stops.txt", stops_csv)
    return buf.getvalue()


SAMPLE_STOPS_CSV = (
    "stop_id,stop_name,stop_lat,stop_lon\n"
    "T1,Paradero 1,-33.44,-70.65\n"
    "T2,Paradero 2,-33.50,-70.70\n"
    "T3,Paradero 3,-33.38,-70.60\n"
)


# ── TestLoadGTFSStops ──────────────────────────────────────────────────────────

class TestLoadGTFSStops:

    def test_load_from_cache_when_exists(self, monkeypatch, tmp_path):
        """Cache file present + force_refresh=False → returns pickled df, no HTTP."""
        import src.features.gtfs_features as gtfs_mod

        stub_df = _make_stops_df()
        cache_file = tmp_path / "gtfs_stops.pkl"
        cache_file.write_bytes(pickle.dumps(stub_df))

        monkeypatch.setattr(gtfs_mod, "_cache_path", lambda: cache_file)

        # Ensure requests.get is never called
        with patch("requests.get") as mock_get:
            result = gtfs_mod.load_gtfs_stops(force_refresh=False)
            mock_get.assert_not_called()

        assert result is not None
        assert list(result.columns) == list(stub_df.columns)
        assert len(result) == len(stub_df)

    def test_download_when_no_cache(self, monkeypatch, tmp_path):
        """No cache file → downloads zip, parses stops.txt, returns correct columns."""
        import src.features.gtfs_features as gtfs_mod

        cache_file = tmp_path / "gtfs_stops.pkl"
        monkeypatch.setattr(gtfs_mod, "_cache_path", lambda: cache_file)

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.content = _make_gtfs_zip(SAMPLE_STOPS_CSV)

        with patch("requests.get", return_value=fake_response):
            result = gtfs_mod.load_gtfs_stops(force_refresh=False)

        assert result is not None
        assert set(result.columns) >= {"stop_id", "stop_name", "lat", "lon"}

    def test_filters_to_santiago_bbox(self, monkeypatch, tmp_path):
        """Stops outside Santiago bbox are filtered out."""
        import src.features.gtfs_features as gtfs_mod

        cache_file = tmp_path / "gtfs_stops.pkl"
        monkeypatch.setattr(gtfs_mod, "_cache_path", lambda: cache_file)

        # Mix: 2 inside bbox, 2 outside (lat -35, lon -72)
        csv = (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "IN1,Inside 1,-33.44,-70.65\n"
            "IN2,Inside 2,-33.50,-70.60\n"
            "OUT1,Outside lat,-35.00,-70.65\n"
            "OUT2,Outside lon,-33.44,-72.00\n"
        )

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.content = _make_gtfs_zip(csv)

        with patch("requests.get", return_value=fake_response):
            result = gtfs_mod.load_gtfs_stops(force_refresh=True)

        assert result is not None
        assert len(result) == 2
        assert set(result["stop_id"]) == {"IN1", "IN2"}

    def test_returns_none_on_download_error(self, monkeypatch, tmp_path):
        """requests.RequestException during download → returns None."""
        import src.features.gtfs_features as gtfs_mod

        cache_file = tmp_path / "gtfs_stops.pkl"
        monkeypatch.setattr(gtfs_mod, "_cache_path", lambda: cache_file)

        with patch("requests.get", side_effect=requests.RequestException("timeout")):
            result = gtfs_mod.load_gtfs_stops(force_refresh=True)

        assert result is None

    def test_cache_used_when_force_refresh_false(self, monkeypatch, tmp_path):
        """Cache present, force_refresh=False → pd.read_pickle path used (pickle.load)."""
        import src.features.gtfs_features as gtfs_mod

        stub_df = _make_stops_df(3)
        cache_file = tmp_path / "gtfs_stops.pkl"
        cache_file.write_bytes(pickle.dumps(stub_df))

        monkeypatch.setattr(gtfs_mod, "_cache_path", lambda: cache_file)

        with patch("requests.get") as mock_get:
            result = gtfs_mod.load_gtfs_stops(force_refresh=False)
            mock_get.assert_not_called()

        assert result is not None
        assert len(result) == 3


# ── TestComputeGTFSFeatures ────────────────────────────────────────────────────

class TestComputeGTFSFeatures:

    def _sample_properties(self, n=5) -> pd.DataFrame:
        return pd.DataFrame({
            "id":        list(range(n)),
            "latitude":  np.linspace(-33.40, -33.60, n),
            "longitude": np.linspace(-70.50, -70.70, n),
        })

    def test_adds_dist_gtfs_bus_km_column(self):
        """Result DataFrame must contain 'dist_gtfs_bus_km'."""
        from src.features.gtfs_features import compute_gtfs_features

        df = self._sample_properties(5)
        stops = _make_stops_df(3)
        result = compute_gtfs_features(df, stops)
        assert "dist_gtfs_bus_km" in result.columns

    def test_distances_are_non_negative(self):
        """All computed distances must be >= 0."""
        from src.features.gtfs_features import compute_gtfs_features

        df = self._sample_properties(5)
        stops = _make_stops_df(3)
        result = compute_gtfs_features(df, stops)
        valid = result["dist_gtfs_bus_km"].dropna()
        assert (valid >= 0).all()

    def test_nearest_stop_is_correct(self):
        """Property placed exactly at a stop location → distance < 0.01 km."""
        from src.features.gtfs_features import compute_gtfs_features

        stops = _make_stops_df(3)
        # Place one property exactly at the first stop
        df = pd.DataFrame({
            "id":        [0],
            "latitude":  [float(stops["lat"].iloc[0])],
            "longitude": [float(stops["lon"].iloc[0])],
        })
        result = compute_gtfs_features(df, stops)
        assert float(result["dist_gtfs_bus_km"].iloc[0]) < 0.01

    def test_handles_empty_properties_df(self):
        """Empty input DataFrame → returns empty DataFrame without error."""
        from src.features.gtfs_features import compute_gtfs_features

        df = pd.DataFrame(columns=["id", "latitude", "longitude"])
        stops = _make_stops_df(3)
        result = compute_gtfs_features(df, stops)
        assert len(result) == 0

    def test_returns_same_number_of_rows(self):
        """Output has the same number of rows as input."""
        from src.features.gtfs_features import compute_gtfs_features

        df = self._sample_properties(7)
        stops = _make_stops_df(4)
        result = compute_gtfs_features(df, stops)
        assert len(result) == len(df)

    def test_distances_are_finite(self):
        """No NaN or inf values in dist_gtfs_bus_km for valid-coordinate rows."""
        from src.features.gtfs_features import compute_gtfs_features

        df = self._sample_properties(5)
        stops = _make_stops_df(3)
        result = compute_gtfs_features(df, stops)
        valid = result["dist_gtfs_bus_km"].dropna()
        assert np.isfinite(valid.values).all()

    def test_distance_plausible_range(self):
        """All distances for Santiago RM properties are < 50 km."""
        from src.features.gtfs_features import compute_gtfs_features

        df = self._sample_properties(8)
        stops = _make_stops_df(5)
        result = compute_gtfs_features(df, stops)
        valid = result["dist_gtfs_bus_km"].dropna()
        assert (valid < 50.0).all()


# ── TestRun (mocked DB) ────────────────────────────────────────────────────────

class TestRun:

    def test_run_skips_when_stops_is_none(self, monkeypatch):
        """If load_gtfs_stops returns None, no SQL should be executed."""
        import src.features.gtfs_features as gtfs_mod

        monkeypatch.setattr(gtfs_mod, "load_gtfs_stops", lambda **kw: None)

        mock_engine = MagicMock()
        # run() should return early — engine.connect() must never be called
        gtfs_mod.run(connection=mock_engine, skip_cache=False)
        mock_engine.connect.assert_not_called()

    def test_run_queries_transaction_features(self, monkeypatch):
        """When stops are available, run() should issue a SELECT against transaction_features."""
        import src.features.gtfs_features as gtfs_mod

        stops = _make_stops_df(3)
        monkeypatch.setattr(gtfs_mod, "load_gtfs_stops", lambda force_refresh=False: stops)

        # Build a fake DataFrame that pd.read_sql would return
        fake_df = pd.DataFrame({
            "id":        [1, 2],
            "latitude":  [-33.44, -33.50],
            "longitude": [-70.65, -70.70],
        })

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_engine.begin.return_value = mock_conn

        with patch("pandas.read_sql", return_value=fake_df):
            gtfs_mod.run(connection=mock_engine, skip_cache=False)

        # engine.connect() must have been called (SELECT phase)
        mock_engine.connect.assert_called()

    def test_run_dry_run_no_db_update(self, monkeypatch, tmp_path):
        """main(dry_run=True) computes stats but never calls engine.begin (no UPDATE)."""
        import src.features.gtfs_features as gtfs_mod

        stops = _make_stops_df(3)
        monkeypatch.setattr(gtfs_mod, "load_gtfs_stops", lambda force_refresh=False: stops)

        fake_sample = pd.DataFrame({
            "id":        [1, 2, 3],
            "latitude":  [-33.44, -33.50, -33.46],
            "longitude": [-70.65, -70.70, -70.63],
        })

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine.connect.return_value = mock_conn

        with patch("pandas.read_sql", return_value=fake_sample), \
             patch("src.features.gtfs_features.create_engine", return_value=mock_engine):
            gtfs_mod.main(dry_run=True, force_refresh=False)

        # In dry_run mode, engine.begin() (the UPDATE path) must NOT be called
        mock_engine.begin.assert_not_called()


# ── TestIntegration (module-level constants) ───────────────────────────────────

class TestIntegration:

    def test_gtfs_cache_file_path_is_string(self):
        """GTFS_CACHE_FILE constant must be a non-empty string ending in .pkl."""
        from src.features.gtfs_features import GTFS_CACHE_FILE

        assert isinstance(GTFS_CACHE_FILE, str)
        assert GTFS_CACHE_FILE.endswith(".pkl")

    def test_gtfs_url_is_http(self):
        """GTFS_URL must begin with 'http'."""
        from src.features.gtfs_features import GTFS_URL

        assert isinstance(GTFS_URL, str)
        assert GTFS_URL.startswith("http")

    def test_feature_name_correct(self):
        """compute_gtfs_features produces a column named exactly 'dist_gtfs_bus_km'."""
        from src.features.gtfs_features import compute_gtfs_features

        df = pd.DataFrame({
            "id":        [1],
            "latitude":  [-33.44],
            "longitude": [-70.65],
        })
        stops = _make_stops_df(2)
        result = compute_gtfs_features(df, stops)
        assert "dist_gtfs_bus_km" in result.columns
        # No similarly-named variants should be present
        assert "dist_bus_stop_km" not in result.columns
        assert "dist_gtfs_km" not in result.columns
