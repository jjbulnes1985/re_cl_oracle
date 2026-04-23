"""Tests for src/features/temporal_features.py"""
import pandas as pd
import pytest


def test_quarter_dummies(sample_transactions):
    from src.features.temporal_features import compute_temporal_features
    df = compute_temporal_features(sample_transactions.copy())
    for col in ["quarter_q1", "quarter_q2", "quarter_q3", "quarter_q4"]:
        assert col in df.columns
    # Each row sums to exactly 1 across dummies
    dummy_sum = df[["quarter_q1", "quarter_q2", "quarter_q3", "quarter_q4"]].sum(axis=1)
    assert (dummy_sum == 1).all()


def test_season_index_range(sample_transactions):
    from src.features.temporal_features import compute_temporal_features
    df = compute_temporal_features(sample_transactions.copy())
    assert "season_index" in df.columns
    assert df["season_index"].between(0.0, 1.0).all()


def test_season_index_values(sample_transactions):
    from src.features.temporal_features import compute_temporal_features
    df = compute_temporal_features(sample_transactions.copy())
    # Q1 → 0.0, Q2 → 0.333, Q3 → 0.667, Q4 → 1.0
    for q, expected in [(1, 0.0), (2, 1/3), (3, 2/3), (4, 1.0)]:
        rows = df[df["quarter"] == q]["season_index"]
        assert (abs(rows - expected) < 1e-6).all(), f"Q{q} season_index expected {expected}"
