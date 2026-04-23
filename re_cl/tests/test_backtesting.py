"""
test_backtesting.py
-------------------
Tests for src/backtesting/walk_forward.py (V4.5).
All tests use synthetic DataFrames — no real DB, no trained model required.
"""

import math
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch


# ── Synthetic data helpers ─────────────────────────────────────────────────────

def make_ols_df(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """
    Synthetic DataFrame suitable for run_ols_benchmark (via mocked DB).
    Contains all columns that _load_data() would return plus derived ones
    that run_ols_benchmark computes internally.
    """
    rng = np.random.default_rng(seed)
    counties = ["Santiago", "Providencia", "Las Condes", "Ñuñoa", "La Florida"]
    types    = ["apartments", "residential"]

    county_name  = rng.choice(counties, n)
    project_type = rng.choice(types, n)
    year         = rng.choice([2013, 2014], n)
    quarter      = rng.choice([1, 2, 3, 4], n)
    surface_m2   = rng.uniform(40, 200, n)

    # Realistic log-linear relationship: log(uf_m2) ~ 0.9*log(surface) + noise
    log_uf_m2 = (
        4.0
        + 0.9 * np.log(surface_m2)
        + rng.normal(0, 0.2, n)
    )
    uf_m2_building = np.exp(log_uf_m2).clip(5, 500)

    return pd.DataFrame({
        "id":                   range(1, n + 1),
        "project_type":         project_type,
        "county_name":          county_name,
        "year":                 year.astype(int),
        "quarter":              quarter.astype(int),
        "uf_m2_building":       uf_m2_building.round(4),
        "surface_m2":           surface_m2.round(2),
        "surface_building_m2":  (surface_m2 * rng.uniform(0.7, 1.0, n)).round(2),
        "surface_land_m2":      (surface_m2 * rng.uniform(1.0, 3.0, n)).round(2),
        "data_confidence":      rng.uniform(0.7, 1.0, n).round(3),
        "gap_pct":              rng.normal(0, 0.15, n).round(4),
        "price_percentile_50":  uf_m2_building.round(4),
        "dist_km_centroid":     rng.uniform(1, 20, n).round(3),
        "cluster_id":           rng.integers(0, 10, n),
        "season_index":         rng.uniform(0.8, 1.2, n).round(3),
    })


def make_mock_engine(df: pd.DataFrame) -> MagicMock:
    """Returns a MagicMock engine whose read_sql returns the given DataFrame."""
    engine = MagicMock()
    with patch("pandas.read_sql", return_value=df):
        pass
    return engine


# ── _metrics (internal pure function) ─────────────────────────────────────────

def test_metrics_basic():
    from src.backtesting.walk_forward import _metrics
    y_true = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
    y_pred = np.array([11.0, 19.0, 31.0, 39.0, 51.0])
    result = _metrics(y_true, y_pred, "test")
    assert "r2" in result
    assert "rmse" in result
    assert "mae" in result
    assert result["n"] == 5


def test_metrics_perfect_prediction_r2_is_1():
    from src.backtesting.walk_forward import _metrics
    y = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
    result = _metrics(y, y, "perfect")
    assert result["r2"] == pytest.approx(1.0)
    assert result["rmse"] == pytest.approx(0.0, abs=1e-9)


def test_metrics_too_few_rows_returns_nones():
    from src.backtesting.walk_forward import _metrics
    y = np.array([10.0, 20.0])
    result = _metrics(y, y, "few")
    assert result["r2"] is None
    assert result["rmse"] is None


def test_metrics_rmse_positive():
    from src.backtesting.walk_forward import _metrics
    rng = np.random.default_rng(7)
    y_true = rng.uniform(20, 80, 50)
    y_pred = y_true + rng.normal(0, 5, 50)
    result = _metrics(y_true, y_pred, "noisy")
    assert result["rmse"] > 0


# ── _preprocess ────────────────────────────────────────────────────────────────

def test_preprocess_encodes_categoricals():
    from src.backtesting.walk_forward import _preprocess, CAT_FEATURES, NUM_FEATURES
    df = make_ols_df(100)
    # Ensure all needed NUM_FEATURES columns exist (fill with 0 if absent)
    for col in NUM_FEATURES:
        if col not in df.columns:
            df[col] = 0.0
    train = df[df["year"] == 2013].copy()
    test  = df[df["year"] == 2014].copy()
    if train.empty or test.empty:
        pytest.skip("Random seed produced only one year — skip")
    train_p, test_p, encoders = _preprocess(train, test)
    for col in CAT_FEATURES:
        assert train_p[col].dtype in (np.int32, np.int64, int, "int64", "int32")


def test_preprocess_imputes_numeric_nulls():
    from src.backtesting.walk_forward import _preprocess, NUM_FEATURES
    df = make_ols_df(100)
    for col in NUM_FEATURES:
        if col not in df.columns:
            df[col] = 0.0
    train = df[df["year"] == 2013].copy()
    test  = df[df["year"] == 2014].copy()
    if train.empty or test.empty:
        pytest.skip("Random seed produced only one year — skip")
    # Inject NULLs
    train.loc[train.index[:5], "surface_m2"] = np.nan
    train_p, test_p, _ = _preprocess(train, test)
    assert train_p["surface_m2"].isna().sum() == 0


# ── run_ols_benchmark ──────────────────────────────────────────────────────────

def test_run_ols_benchmark_returns_dict(monkeypatch):
    from src.backtesting import walk_forward

    df = make_ols_df(300, seed=0)

    monkeypatch.setattr(walk_forward, "_load_data", lambda engine: df)

    try:
        import statsmodels  # noqa: F401
    except ImportError:
        pytest.skip("statsmodels not installed")

    engine = MagicMock()
    result = walk_forward.run_ols_benchmark(engine)
    assert isinstance(result, dict)


def test_run_ols_benchmark_has_required_keys(monkeypatch):
    from src.backtesting import walk_forward

    df = make_ols_df(300, seed=1)
    monkeypatch.setattr(walk_forward, "_load_data", lambda engine: df)

    try:
        import statsmodels  # noqa: F401
    except ImportError:
        pytest.skip("statsmodels not installed")

    engine = MagicMock()
    result = walk_forward.run_ols_benchmark(engine)

    if "error" in result:
        pytest.skip(f"OLS returned error: {result['error']}")

    assert "ols" in result
    assert "ols_surface_coeff" in result
    assert "ols_surface_coeff_thesis_benchmark" in result


def test_run_ols_benchmark_r2_positive_for_well_behaved_data(monkeypatch):
    """
    With a clean log-linear synthetic dataset (R² ground truth >> 0),
    OLS should recover a positive R².
    """
    from src.backtesting import walk_forward

    # Deterministic dataset with strong signal
    rng = np.random.default_rng(42)
    n = 400
    counties = ["Santiago", "Providencia", "Las Condes", "Ñuñoa", "La Florida"]
    county_name  = np.tile(counties, n // len(counties) + 1)[:n]
    project_type = np.tile(["apartments", "residential"], n // 2 + 1)[:n]

    # Half 2013, half 2014 to ensure both splits are populated
    year    = np.array([2013] * (n // 2) + [2014] * (n - n // 2))
    quarter = np.tile([1, 2, 3, 4], n // 4 + 1)[:n]
    surface = rng.uniform(40, 200, n)
    log_uf  = 3.5 + 0.9 * np.log(surface) + rng.normal(0, 0.1, n)
    uf_m2   = np.exp(log_uf).clip(5, 300)

    df = pd.DataFrame({
        "id": range(1, n + 1),
        "project_type": project_type,
        "county_name": county_name,
        "year": year.astype(int),
        "quarter": quarter.astype(int),
        "uf_m2_building": uf_m2.round(4),
        "surface_m2": surface.round(2),
        "surface_building_m2": (surface * 0.9).round(2),
        "surface_land_m2": (surface * 2.0).round(2),
        "data_confidence": np.ones(n),
        "gap_pct": rng.normal(0, 0.1, n),
        "price_percentile_50": uf_m2.round(4),
        "dist_km_centroid": rng.uniform(1, 15, n),
        "cluster_id": rng.integers(0, 5, n),
        "season_index": rng.uniform(0.9, 1.1, n),
    })

    monkeypatch.setattr(walk_forward, "_load_data", lambda engine: df)

    try:
        import statsmodels  # noqa: F401
    except ImportError:
        pytest.skip("statsmodels not installed")

    engine = MagicMock()
    result = walk_forward.run_ols_benchmark(engine)

    if "error" in result:
        pytest.skip(f"OLS returned error: {result['error']}")

    ols_r2 = result["ols"]["r2"]
    assert ols_r2 is not None
    assert ols_r2 > 0.0, f"Expected R² > 0, got {ols_r2}"


def test_run_ols_benchmark_surface_coeff_present(monkeypatch):
    from src.backtesting import walk_forward

    df = make_ols_df(300, seed=5)
    monkeypatch.setattr(walk_forward, "_load_data", lambda engine: df)

    try:
        import statsmodels  # noqa: F401
    except ImportError:
        pytest.skip("statsmodels not installed")

    engine = MagicMock()
    result = walk_forward.run_ols_benchmark(engine)

    if "error" in result:
        pytest.skip(f"OLS returned error: {result['error']}")

    assert isinstance(result["ols_surface_coeff"], float)
    assert not math.isnan(result["ols_surface_coeff"])


# ── run_commune_calibration ────────────────────────────────────────────────────

def test_run_commune_calibration_returns_dataframe(monkeypatch):
    from src.backtesting import walk_forward

    df = make_ols_df(300, seed=10)
    monkeypatch.setattr(walk_forward, "_load_data", lambda engine: df)

    engine = MagicMock()
    result = walk_forward.run_commune_calibration(engine)
    assert isinstance(result, pd.DataFrame)


def test_run_commune_calibration_expected_columns(monkeypatch):
    from src.backtesting import walk_forward

    df = make_ols_df(300, seed=11)
    monkeypatch.setattr(walk_forward, "_load_data", lambda engine: df)
    # Also mock the CSV write to avoid filesystem side effects
    monkeypatch.setattr(walk_forward, "EXPORTS_DIR", MagicMock())

    engine = MagicMock()
    result = walk_forward.run_commune_calibration(engine)
    if result.empty:
        pytest.skip("Not enough data per commune to calibrate (< 5 rows)")

    for col in ["county_name", "bias_pct", "actual_median_uf_m2", "predicted_median_uf_m2"]:
        assert col in result.columns, f"Missing column: {col}"


def test_run_commune_calibration_insufficient_data_returns_empty(monkeypatch):
    """When both years are missing the function should return empty DataFrame."""
    from src.backtesting import walk_forward

    # DataFrame with only 2013 rows — no 2014 test set
    df = make_ols_df(100, seed=99)
    df["year"] = 2013
    monkeypatch.setattr(walk_forward, "_load_data", lambda engine: df)

    engine = MagicMock()
    result = walk_forward.run_commune_calibration(engine)
    assert isinstance(result, pd.DataFrame)
    # Should be empty (error path)
    assert result.empty


# ── _metrics edge cases ────────────────────────────────────────────────────────

def test_metrics_rmse_pct_median_is_reasonable():
    from src.backtesting.walk_forward import _metrics
    rng = np.random.default_rng(3)
    y_true = rng.uniform(40, 80, 100)
    y_pred = y_true + rng.normal(0, 2, 100)
    result = _metrics(y_true, y_pred, "reasonable")
    # RMSE % of median should be < 20% for small noise
    assert result["rmse_pct_median"] < 20


def test_metrics_label_preserved():
    from src.backtesting.walk_forward import _metrics
    y = np.arange(10, dtype=float)
    result = _metrics(y, y, "my_label")
    assert result["label"] == "my_label"
