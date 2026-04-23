"""
test_thesis_features.py
-----------------------
Tests for compute_thesis_features() added in V4.1 to src/features/price_features.py.
Uses a locally-defined synthetic DataFrame — no DB required.
"""

import math

import numpy as np
import pandas as pd
import pytest


def make_thesis_df() -> pd.DataFrame:
    return pd.DataFrame({
        "id": range(10),
        "county_name": [
            "Las Condes", "La Pintana", "Santiago", "Maipú", "Vitacura",
            "Ñuñoa", "Peñalolén", "Pudahuel", "Colina", "Unknown Commune",
        ],
        "surface_m2": [80.0, 60.0, 45.0, 100.0, 150.0, 70.0, 90.0, 55.0, 200.0, 80.0],
        "construction_year": [1958, 1975, 2005, None, 1990, 2012, 1965, 1985, 2000, 2010],
    })


# ── Column presence ────────────────────────────────────────────────────────────

def test_thesis_features_columns_present():
    from src.features.price_features import compute_thesis_features
    df = compute_thesis_features(make_thesis_df())
    for col in ["age", "age_sq", "construction_year_bucket", "city_zone", "log_surface"]:
        assert col in df.columns, f"Missing column: {col}"


# ── age computation ────────────────────────────────────────────────────────────

def test_age_equals_reference_minus_construction_year():
    from src.features.price_features import compute_thesis_features, AGE_REFERENCE_YEAR
    df = compute_thesis_features(make_thesis_df())
    # row 0: construction_year = 1958
    expected_age = AGE_REFERENCE_YEAR - 1958
    assert df.loc[0, "age"] == pytest.approx(expected_age)


def test_age_sq_is_age_squared():
    from src.features.price_features import compute_thesis_features
    df = compute_thesis_features(make_thesis_df())
    valid = df["age"].notna()
    assert (df.loc[valid, "age_sq"] == df.loc[valid, "age"] ** 2).all()


def test_age_null_when_construction_year_null():
    from src.features.price_features import compute_thesis_features
    df = compute_thesis_features(make_thesis_df())
    # row 3 has construction_year = None
    assert pd.isna(df.loc[3, "age"])
    assert pd.isna(df.loc[3, "age_sq"])


def test_age_non_negative():
    """age must be clipped to >= 0 (no negative ages from data-entry errors)."""
    from src.features.price_features import compute_thesis_features
    df = make_thesis_df().copy()
    # Inject a future year (data entry error)
    df.loc[0, "construction_year"] = 2020
    result = compute_thesis_features(df)
    assert result.loc[0, "age"] >= 0


# ── construction_year_bucket ───────────────────────────────────────────────────

def test_bucket_pre_1960():
    from src.features.price_features import construction_year_to_bucket
    assert construction_year_to_bucket(1958) == "pre_1960"
    assert construction_year_to_bucket(1960) == "pre_1960"


def test_bucket_2001_2006():
    from src.features.price_features import construction_year_to_bucket
    assert construction_year_to_bucket(2001) == "2001_2006"
    assert construction_year_to_bucket(2006) == "2001_2006"


def test_bucket_unknown_for_null():
    from src.features.price_features import construction_year_to_bucket
    assert construction_year_to_bucket(None) == "unknown"
    assert construction_year_to_bucket(float("nan")) == "unknown"


def test_bucket_column_matches_helper():
    from src.features.price_features import compute_thesis_features, construction_year_to_bucket
    df = compute_thesis_features(make_thesis_df())
    source = make_thesis_df()
    for i, row in source.iterrows():
        expected = construction_year_to_bucket(row["construction_year"])
        assert df.loc[i, "construction_year_bucket"] == expected


# ── city_zone ─────────────────────────────────────────────────────────────────

def test_city_zone_las_condes_is_este():
    from src.features.price_features import compute_thesis_features
    df = compute_thesis_features(make_thesis_df())
    assert df.loc[0, "city_zone"] == "este"   # Las Condes


def test_city_zone_la_pintana_is_sur():
    from src.features.price_features import compute_thesis_features
    df = compute_thesis_features(make_thesis_df())
    assert df.loc[1, "city_zone"] == "sur"    # La Pintana


def test_city_zone_unknown_commune_is_unknown():
    from src.features.price_features import compute_thesis_features
    df = compute_thesis_features(make_thesis_df())
    assert df.loc[9, "city_zone"] == "unknown"   # "Unknown Commune"


def test_city_zone_maipu_is_oeste():
    from src.features.price_features import compute_thesis_features
    df = compute_thesis_features(make_thesis_df())
    assert df.loc[3, "city_zone"] == "oeste"  # Maipú


# ── log_surface ────────────────────────────────────────────────────────────────

def test_log_surface_positive_when_surface_positive():
    from src.features.price_features import compute_thesis_features
    df = compute_thesis_features(make_thesis_df())
    assert (df["log_surface"] > 0).all()


def test_log_surface_equals_log1p():
    from src.features.price_features import compute_thesis_features
    df = compute_thesis_features(make_thesis_df())
    source = make_thesis_df()
    for i, row in source.iterrows():
        expected = math.log1p(row["surface_m2"])
        assert df.loc[i, "log_surface"] == pytest.approx(expected, rel=1e-6)


def test_log_surface_null_when_surface_missing():
    from src.features.price_features import compute_thesis_features
    df = make_thesis_df().drop(columns=["surface_m2"])
    result = compute_thesis_features(df)
    assert result["log_surface"].isna().all()


# ── Missing column fallbacks ───────────────────────────────────────────────────

def test_handles_missing_construction_year_column():
    from src.features.price_features import compute_thesis_features
    df = make_thesis_df().drop(columns=["construction_year"])
    result = compute_thesis_features(df)
    assert result["age"].isna().all()
    assert result["age_sq"].isna().all()
    assert (result["construction_year_bucket"] == "unknown").all()


def test_handles_missing_county_name_column():
    from src.features.price_features import compute_thesis_features
    df = make_thesis_df().drop(columns=["county_name"])
    result = compute_thesis_features(df)
    assert (result["city_zone"] == "unknown").all()


# ── Integration: works on sample_transactions fixture ─────────────────────────

def test_thesis_features_on_fixture(sample_transactions):
    """compute_thesis_features must not raise on the shared 100-row fixture."""
    from src.features.price_features import compute_thesis_features
    result = compute_thesis_features(sample_transactions.copy())
    assert len(result) == len(sample_transactions)
    assert "age" in result.columns
    assert result["age"].notna().sum() > 0
