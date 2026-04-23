"""
test_osm_features.py
--------------------
Tests for src/features/osm_features.py (V4.2).
All tests are purely in-memory — no HTTP calls, no DB.
"""

import numpy as np
import pandas as pd
import pytest
from sklearn.neighbors import BallTree


# ── _build_overpass_query ──────────────────────────────────────────────────────

def test_build_overpass_query_returns_string():
    from src.features.osm_features import _build_overpass_query, SANTIAGO_BBOX
    result = _build_overpass_query(SANTIAGO_BBOX, [("amenity", "school")])
    assert isinstance(result, str)


def test_build_overpass_query_contains_amenity_type():
    from src.features.osm_features import _build_overpass_query, SANTIAGO_BBOX
    result = _build_overpass_query(SANTIAGO_BBOX, [("amenity", "hospital")])
    assert "hospital" in result


def test_build_overpass_query_contains_bbox_coords():
    from src.features.osm_features import _build_overpass_query, SANTIAGO_BBOX
    s, w, n, e = SANTIAGO_BBOX
    result = _build_overpass_query(SANTIAGO_BBOX, [("leisure", "park")])
    assert str(s) in result
    assert str(e) in result


def test_build_overpass_query_multiple_tags():
    from src.features.osm_features import _build_overpass_query, SANTIAGO_BBOX
    tags = [("amenity", "school"), ("amenity", "college"), ("amenity", "university")]
    result = _build_overpass_query(SANTIAGO_BBOX, tags)
    assert "school" in result
    assert "college" in result
    assert "university" in result


def test_build_overpass_query_json_out():
    from src.features.osm_features import _build_overpass_query, SANTIAGO_BBOX
    result = _build_overpass_query(SANTIAGO_BBOX, [("amenity", "school")])
    assert "[out:json]" in result
    assert "out center" in result


# ── _build_tree / _nearest_km ──────────────────────────────────────────────────

def _make_tree_and_query():
    """Helper: 3 fixed points + 1 query point."""
    coords = [
        {"lat": -33.44, "lon": -70.65},
        {"lat": -33.50, "lon": -70.70},
        {"lat": -33.38, "lon": -70.60},
    ]
    query_point = np.radians([[-33.44, -70.65]])   # exact match → dist ~ 0
    return coords, query_point


def test_build_tree_returns_balltree():
    from src.features.osm_features import _build_tree
    coords, _ = _make_tree_and_query()
    tree = _build_tree(coords)
    assert isinstance(tree, BallTree)


def test_build_tree_returns_none_for_empty():
    from src.features.osm_features import _build_tree
    assert _build_tree([]) is None


def test_nearest_km_returns_float_distances():
    from src.features.osm_features import _build_tree, _nearest_km
    coords, query = _make_tree_and_query()
    tree = _build_tree(coords)
    dists = _nearest_km(tree, query)
    assert dists.shape == (1,)
    assert isinstance(float(dists[0]), float)


def test_nearest_km_exact_point_is_zero():
    from src.features.osm_features import _build_tree, _nearest_km
    coords, query = _make_tree_and_query()
    tree = _build_tree(coords)
    dists = _nearest_km(tree, query)
    assert dists[0] == pytest.approx(0.0, abs=1e-6)


def test_nearest_km_none_tree_returns_nan():
    from src.features.osm_features import _nearest_km
    query = np.radians([[-33.44, -70.65]])
    dists = _nearest_km(None, query)
    assert np.isnan(dists[0])


# ── _count_within_km ──────────────────────────────────────────────────────────

def test_count_within_km_returns_integers():
    from src.features.osm_features import _build_tree, _count_within_km
    coords, query = _make_tree_and_query()
    tree = _build_tree(coords)
    counts = _count_within_km(tree, query, radius_km=1.0)
    assert counts.dtype in (np.int32, np.int64, int)


def test_count_within_km_large_radius_finds_all():
    from src.features.osm_features import _build_tree, _count_within_km
    coords = [
        {"lat": -33.44, "lon": -70.65},
        {"lat": -33.45, "lon": -70.66},
    ]
    # Query from midpoint, very large radius — should find both
    query = np.radians([[-33.445, -70.655]])
    tree = _build_tree(coords)
    counts = _count_within_km(tree, query, radius_km=100.0)
    assert counts[0] == 2


def test_count_within_km_zero_radius_finds_none():
    from src.features.osm_features import _build_tree, _count_within_km
    coords = [{"lat": -33.50, "lon": -70.70}]
    query = np.radians([[-33.44, -70.65]])   # distant point
    tree = _build_tree(coords)
    counts = _count_within_km(tree, query, radius_km=0.001)
    assert counts[0] == 0


def test_count_within_km_none_tree_returns_zeros():
    from src.features.osm_features import _count_within_km
    query = np.radians([[-33.44, -70.65], [-33.50, -70.70]])
    counts = _count_within_km(None, query, radius_km=1.0)
    assert list(counts) == [0, 0]


# ── compute_osm_features — empty / no-coords DataFrames ───────────────────────

def test_compute_osm_features_empty_df_returns_correct_columns():
    from src.features.osm_features import compute_osm_features
    empty_df = pd.DataFrame(columns=["id", "latitude", "longitude"])
    result = compute_osm_features(empty_df)
    expected_cols = {
        "id", "dist_metro_km", "dist_bus_stop_km", "dist_school_km",
        "dist_hospital_km", "dist_park_km", "dist_mall_km",
        "amenities_500m", "amenities_1km",
    }
    assert expected_cols == set(result.columns)


def test_compute_osm_features_empty_df_is_empty():
    from src.features.osm_features import compute_osm_features
    empty_df = pd.DataFrame(columns=["id", "latitude", "longitude"])
    result = compute_osm_features(empty_df)
    assert len(result) == 0


def test_compute_osm_features_null_coords_returns_nan_dists():
    """DataFrame with null coordinates → all dist_* columns are NaN."""
    from src.features.osm_features import compute_osm_features
    df = pd.DataFrame({
        "id": [1, 2, 3],
        "latitude": [None, None, None],
        "longitude": [None, None, None],
        "has_valid_coords": [False, False, False],
    })
    result = compute_osm_features(df)
    for col in ["dist_metro_km", "dist_bus_stop_km", "dist_school_km",
                "dist_hospital_km", "dist_park_km", "dist_mall_km"]:
        assert result[col].isna().all(), f"{col} should be all NaN"


# ── Metro distance using hardcoded METRO_STATIONS ─────────────────────────────

def test_metro_stations_list_nonempty():
    from src.features.osm_features import METRO_STATIONS
    assert len(METRO_STATIONS) > 0


def test_metro_stations_have_lat_lon():
    from src.features.osm_features import METRO_STATIONS
    for st in METRO_STATIONS:
        assert "lat" in st and "lon" in st
        assert isinstance(st["lat"], (int, float))
        assert isinstance(st["lon"], (int, float))


def test_metro_distance_near_universidad_de_chile():
    """
    A point at Universidad de Chile station (lat=-33.4412, lon=-70.6497)
    should have dist_metro_km < 0.5 km using the hardcoded list.
    """
    from src.features.osm_features import METRO_STATIONS, _build_tree, _nearest_km

    metro_tree = _build_tree(METRO_STATIONS)
    # Coords of Universidad de Chile station
    query = np.radians([[-33.4412, -70.6497]])
    dist = _nearest_km(metro_tree, query)
    assert dist[0] < 0.5, (
        f"Expected dist < 0.5 km to nearest metro station, got {dist[0]:.4f} km"
    )


def test_metro_distance_far_point_is_larger():
    """A point far from any station should return a larger distance."""
    from src.features.osm_features import METRO_STATIONS, _build_tree, _nearest_km

    metro_tree = _build_tree(METRO_STATIONS)
    # Somewhere in the cordillera, far from the metro network
    query_near = np.radians([[-33.4412, -70.6497]])
    query_far  = np.radians([[-33.75, -70.05]])
    dist_near = _nearest_km(metro_tree, query_near)[0]
    dist_far  = _nearest_km(metro_tree, query_far)[0]
    assert dist_far > dist_near


# ── compute_osm_features — metro computed without HTTP ────────────────────────

def test_compute_osm_features_metro_column_filled_for_valid_coords(monkeypatch):
    """
    Patch fetch_all_poi_trees so no HTTP call is made.
    dist_metro_km should still be filled because it uses the hardcoded list.
    """
    from src.features.osm_features import compute_osm_features
    import src.features.osm_features as osm_mod

    # Return empty trees for all Overpass-based categories
    monkeypatch.setattr(osm_mod, "fetch_all_poi_trees", lambda bbox: {
        "bus_stop": None, "school": None, "hospital": None,
        "park": None, "mall": None,
    })

    df = pd.DataFrame({
        "id": [1, 2],
        "latitude":  [-33.4412, -33.50],
        "longitude": [-70.6497, -70.70],
        "has_valid_coords": [True, True],
    })
    result = compute_osm_features(df)

    # Metro distance should be non-NaN for both rows
    assert result["dist_metro_km"].notna().all()
    # The row near Universidad de Chile should be < 0.5 km
    assert float(result.loc[result["id"] == 1, "dist_metro_km"].iloc[0]) < 0.5
