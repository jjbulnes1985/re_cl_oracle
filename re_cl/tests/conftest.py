"""
conftest.py
-----------
Shared pytest fixtures for RE_CL tests.
All fixtures use synthetic in-memory data — no real DB connection required.
"""

import numpy as np
import pandas as pd
import pytest


# ── Bounding box RM Santiago ───────────────────────────────────────────────────
RM_LAT = (-33.65, -33.30)
RM_LON = (-70.85, -70.45)

COMMUNES = ["Ñuñoa", "Santiago", "La Florida", "Providencia", "Maipú"]
TYPES    = ["apartments", "residential", "land", "retail", "residential"]


@pytest.fixture(scope="session")
def sample_transactions() -> pd.DataFrame:
    """
    100-row synthetic DataFrame mimicking transactions_clean schema.
    5 communes × 20 rows each. 2013-2014 data.
    """
    rng = np.random.default_rng(seed=42)
    n = 100

    # Assign commune and type in blocks of 20
    county_name    = np.repeat(COMMUNES, n // len(COMMUNES))
    project_type   = np.repeat(TYPES,    n // len(TYPES))

    # Realistic UF/m² ranges by type
    uf_m2 = np.where(
        project_type == "apartments", rng.uniform(35, 80, n),
        np.where(project_type == "residential", rng.uniform(20, 60, n),
        np.where(project_type == "land",         rng.uniform(5, 30, n),
                                                  rng.uniform(40, 120, n)))
    )

    # calculated_value_uf ~ real_value_uf * (1 ± noise), some subvalued
    noise = rng.normal(0, 0.15, n)
    real_value_uf = uf_m2 * rng.uniform(50, 120, n)  # surface 50-120 m²
    calc_value_uf = real_value_uf * (1 + noise)

    # Coordinates in RM
    latitudes  = rng.uniform(*RM_LAT, n)
    longitudes = rng.uniform(*RM_LON, n)

    year    = rng.choice([2013, 2014], n)
    quarter = rng.choice([1, 2, 3, 4], n)

    construction_year = rng.choice(
        [1950, 1965, 1975, 1985, 1995, 2005, 2010, 2015],
        n,
    ).astype("int64")

    df = pd.DataFrame({
        "id":                   range(1, n + 1),
        "raw_id":               range(1001, 1001 + n),
        "project_type":         project_type,
        "county_name":          county_name,
        "inscription_date":     pd.date_range("2013-01-01", periods=n, freq="3D"),
        "year":                 year.astype("int16"),
        "quarter":              quarter.astype("int16"),
        "real_value_uf":        real_value_uf.round(4),
        "calculated_value_uf":  calc_value_uf.round(4),
        "surface_m2":           rng.uniform(40, 200, n).round(2),
        "surface_building_m2":  rng.uniform(40, 180, n).round(2),
        "surface_land_m2":      rng.uniform(50, 500, n).round(2),
        "uf_m2_building":       uf_m2.round(4),
        "uf_m2_land":           (uf_m2 * 0.4).round(4),
        "latitude":             latitudes.round(8),
        "longitude":            longitudes.round(8),
        "has_valid_coords":     True,
        "has_valid_price":      True,
        "has_surface":          True,
        "is_outlier":           False,
        "data_confidence":      rng.uniform(0.6, 1.0, n).round(3),
        "construction_year":    pd.array(construction_year, dtype="Int64"),
    })

    # Introduce a few NULLs to test robustness
    df.loc[0, "real_value_uf"]       = None
    df.loc[1, "calculated_value_uf"] = None
    df.loc[2, "latitude"]            = None
    df.loc[2, "longitude"]           = None
    df.loc[2, "has_valid_coords"]    = False

    return df


@pytest.fixture(scope="session")
def price_features_df(sample_transactions) -> pd.DataFrame:
    """Pre-computed price features for use in integration tests."""
    from src.features.price_features import compute_gap_pct, compute_percentiles
    df = sample_transactions.copy()
    df = compute_gap_pct(df)
    df = compute_percentiles(df)
    return df
