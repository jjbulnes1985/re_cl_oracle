"""Tests for src/features/price_features.py"""
import numpy as np
import pandas as pd
import pytest


def test_gap_pct_basic(sample_transactions):
    from src.features.price_features import compute_gap_pct
    df = compute_gap_pct(sample_transactions.copy())
    assert "gap_pct" in df.columns
    assert "gap_pct_raw" in df.columns


def test_gap_pct_null_where_invalid(sample_transactions):
    from src.features.price_features import compute_gap_pct
    df = compute_gap_pct(sample_transactions.copy())
    # Row 0 has null real_value_uf → gap_pct should be NaN
    assert pd.isna(df.loc[0, "gap_pct"])
    # Row 1 has null calculated_value_uf → gap_pct should be NaN
    assert pd.isna(df.loc[1, "gap_pct"])


def test_gap_pct_winsorized(sample_transactions):
    """Winsorized range must be narrower than or equal to the raw range."""
    from src.features.price_features import compute_gap_pct
    df = compute_gap_pct(sample_transactions.copy())
    valid_raw = df["gap_pct_raw"].dropna()
    valid_win = df["gap_pct"].dropna()
    # Winsorized min >= raw min (or equal), max <= raw max (or equal)
    assert valid_win.min() >= valid_raw.min() - 1e-9
    assert valid_win.max() <= valid_raw.max() + 1e-9
    # Winsorized range must be strictly <= raw range (since we clip at p1/p99)
    assert (valid_win.max() - valid_win.min()) <= (valid_raw.max() - valid_raw.min()) + 1e-9


def test_percentiles_columns(sample_transactions):
    from src.features.price_features import compute_gap_pct, compute_percentiles
    df = compute_gap_pct(sample_transactions.copy())
    df = compute_percentiles(df)
    for col in ["price_percentile_25", "price_percentile_50", "price_percentile_75"]:
        assert col in df.columns, f"Missing column: {col}"


def test_percentiles_ordering(sample_transactions):
    from src.features.price_features import compute_gap_pct, compute_percentiles
    df = compute_gap_pct(sample_transactions.copy())
    df = compute_percentiles(df)
    valid = df[["price_percentile_25", "price_percentile_50", "price_percentile_75"]].dropna()
    assert (valid["price_percentile_25"] <= valid["price_percentile_50"]).all()
    assert (valid["price_percentile_50"] <= valid["price_percentile_75"]).all()
