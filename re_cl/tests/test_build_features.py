"""Integration tests for src/features/build_features.py"""
import pandas as pd
import pytest


def test_merge_feature_dfs_columns(sample_transactions):
    """merge_feature_dfs should produce a DataFrame with all feature columns."""
    from src.features.price_features import compute_gap_pct, compute_percentiles
    from src.features.spatial_features import compute_centroid_distance, compute_dbscan_clusters
    from src.features.temporal_features import compute_temporal_features
    from src.features.build_features import merge_feature_dfs

    price_df   = compute_percentiles(compute_gap_pct(sample_transactions.copy()))
    spatial_df = compute_dbscan_clusters(
                   compute_centroid_distance(sample_transactions.copy()),
                   min_clusters=1, eps_km=5.0, min_samples=3)
    temporal_df = compute_temporal_features(sample_transactions.copy())

    merged = merge_feature_dfs(price_df, spatial_df, temporal_df)

    expected_cols = [
        "clean_id", "gap_pct", "gap_pct_raw",
        "price_percentile_25", "price_percentile_50", "price_percentile_75",
        "dist_km_centroid", "cluster_id",
        "quarter_q1", "quarter_q2", "quarter_q3", "quarter_q4", "season_index",
    ]
    for col in expected_cols:
        assert col in merged.columns, f"Missing column after merge: {col}"


def test_merge_no_duplicate_clean_ids(sample_transactions):
    """Each clean_id must appear exactly once in the merged DataFrame."""
    from src.features.price_features import compute_gap_pct, compute_percentiles
    from src.features.spatial_features import compute_centroid_distance, compute_dbscan_clusters
    from src.features.temporal_features import compute_temporal_features
    from src.features.build_features import merge_feature_dfs

    price_df    = compute_percentiles(compute_gap_pct(sample_transactions.copy()))
    spatial_df  = compute_dbscan_clusters(
                    compute_centroid_distance(sample_transactions.copy()),
                    min_clusters=1, eps_km=5.0, min_samples=3)
    temporal_df = compute_temporal_features(sample_transactions.copy())

    merged = merge_feature_dfs(price_df, spatial_df, temporal_df)
    assert merged["clean_id"].nunique() == len(merged), "Duplicate clean_ids in merged DataFrame"
