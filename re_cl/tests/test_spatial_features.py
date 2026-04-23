"""Tests for src/features/spatial_features.py"""
import pandas as pd
import pytest


def test_dist_km_centroid_column(sample_transactions):
    from src.features.spatial_features import compute_centroid_distance
    df = compute_centroid_distance(sample_transactions.copy())
    assert "dist_km_centroid" in df.columns


def test_dist_km_centroid_units(sample_transactions):
    """Distances in RM should be < 60 km from commune centroid."""
    from src.features.spatial_features import compute_centroid_distance
    df = compute_centroid_distance(sample_transactions.copy())
    valid = df["dist_km_centroid"].dropna()
    assert (valid >= 0).all()
    assert (valid < 60).all(), f"Max dist = {valid.max():.1f} km, expected < 60"


def test_dist_km_null_for_invalid_coords(sample_transactions):
    """Row 2 has has_valid_coords=False → dist_km_centroid must be NaN."""
    from src.features.spatial_features import compute_centroid_distance
    df = compute_centroid_distance(sample_transactions.copy())
    assert pd.isna(df.loc[2, "dist_km_centroid"])


def test_dbscan_cluster_id_column(sample_transactions):
    """DBSCAN with relaxed params for 100-point synthetic fixture (sparse data)."""
    from src.features.spatial_features import compute_dbscan_clusters
    # eps=5km, min_samples=3: finds clusters in sparse 100-row fixture
    # Production uses eps=0.5km, min_samples=10 (1M real points are denser)
    df = compute_dbscan_clusters(
        sample_transactions.copy(), min_clusters=1, eps_km=5.0, min_samples=3
    )
    assert "cluster_id" in df.columns
    assert df["cluster_id"].notna().any()
