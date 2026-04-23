"""
test_clean.py
-------------
Tests for ingestion cleaning logic: scale detection, deduplication,
surface imputation, outlier detection, and data_confidence computation.
Uses synthetic DataFrames — no real DB required.
"""

import numpy as np
import pandas as pd
import pytest

from src.ingestion.clean_transactions import (
    detect_real_value_scale,
    deduplicate,
    impute_surface,
    detect_outliers,
    normalize_typology,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_base_df(n=60, seed=0) -> pd.DataFrame:
    """Synthetic DataFrame matching transactions_raw schema."""
    rng = np.random.default_rng(seed)
    types = ["apartments", "residential", "land"]
    communes = ["Ñuñoa", "Santiago", "La Florida", "Providencia", "Maipú"]
    year = rng.choice([2013, 2014], n)
    ptype = rng.choice(types, n)
    county = rng.choice(communes, n)
    uf_m2 = rng.uniform(20, 80, n)
    surface = rng.uniform(40, 180, n)
    calc_value = uf_m2 * surface
    real_value = calc_value * rng.uniform(0.85, 1.15, n)
    uf_value = rng.uniform(22800, 23700, n)

    return pd.DataFrame({
        "id_role":          [f"R{i:04d}" for i in range(n)],
        "inscription_date": pd.date_range("2013-01-01", periods=n, freq="5D"),
        "project_type_name": ptype,
        "project_type_norm": ptype,
        "county_name":       county,
        "year":              year,
        "real_value":        real_value.round(2),
        "calculated_value":  calc_value.round(2),
        "surface":           surface.round(2),
        "uf_m2_u":           uf_m2.round(4),
        "uf_value":          uf_value.round(2),
    })


# ── normalize_typology ────────────────────────────────────────────────────────

class TestNormalizeTypology:
    def test_known_types_map_correctly(self):
        assert normalize_typology("apartments") == "apartments"
        assert normalize_typology("residential") == "residential"
        assert normalize_typology("land") == "land"
        assert normalize_typology("retail") == "retail"

    def test_null_returns_unknown(self):
        assert normalize_typology(None) == "unknown"
        assert normalize_typology(float("nan")) == "unknown"

    def test_unknown_string_returns_unknown(self):
        assert normalize_typology("industrial") == "unknown"
        assert normalize_typology("") == "unknown"

    def test_case_insensitive(self):
        assert normalize_typology("Apartments") == "apartments"
        assert normalize_typology("LAND") == "land"


# ── detect_real_value_scale ───────────────────────────────────────────────────

class TestDetectRealValueScale:
    def test_uf_values_not_converted(self):
        """When Real_Value is already in UF, no conversion should happen."""
        df = _make_base_df(60)
        # real_value is ~1x calculated_value (UF-denominated)
        original = df["real_value"].copy()
        result = detect_real_value_scale(df)
        # Values should be unchanged (or very close)
        changed = (result["real_value"] - original).abs() > 1e-6
        assert changed.sum() == 0, f"{changed.sum()} values changed unexpectedly"

    def test_clp_values_are_converted(self):
        """When >50% of records have ratio > 500, values should be converted."""
        df = _make_base_df(60)
        # Multiply real_value by ~23000 to simulate CLP
        df["real_value"] = df["real_value"] * 23000
        original_max = df["real_value"].max()
        result = detect_real_value_scale(df)
        # After conversion, values should be much smaller
        assert result["real_value"].max() < original_max / 100

    def test_returns_dataframe_same_shape(self):
        df = _make_base_df(30)
        result = detect_real_value_scale(df)
        assert result.shape == df.shape

    def test_empty_df_handled(self):
        df = pd.DataFrame(columns=["real_value", "calculated_value", "uf_value"])
        result = detect_real_value_scale(df)
        assert len(result) == 0


# ── deduplicate ───────────────────────────────────────────────────────────────

class TestDeduplicate:
    def test_removes_exact_duplicates(self):
        df = _make_base_df(20)
        # Force duplicates
        df_dup = pd.concat([df.head(5), df.head(5)], ignore_index=True)
        result = deduplicate(df_dup)
        assert len(result) == len(df.head(5))

    def test_keeps_all_unique(self):
        df = _make_base_df(30)
        result = deduplicate(df)
        assert len(result) == len(df)

    def test_prefers_more_complete_row(self):
        """When two rows share (id_role, inscription_date), keep the more complete one."""
        df = pd.DataFrame({
            "id_role":          ["R001", "R001"],
            "inscription_date": [pd.Timestamp("2013-03-01")] * 2,
            "real_value":       [100.0, 100.0],
            "calculated_value": [95.0,  None],   # second row less complete
            "surface":          [80.0,  None],
            "uf_m2_u":          [1.25,  None],
            "uf_value":         [23000, 23000],
            "project_type_name": ["apartments", "apartments"],
            "project_type_norm": ["apartments", "apartments"],
            "county_name":      ["Ñuñoa", "Ñuñoa"],
            "year":             [2013, 2013],
        })
        result = deduplicate(df)
        assert len(result) == 1
        # Should keep the complete row (no nulls in key columns)
        assert pd.notna(result.iloc[0]["calculated_value"])


# ── impute_surface ────────────────────────────────────────────────────────────

class TestImputeSurface:
    def test_no_nulls_unchanged(self):
        df = _make_base_df(30)
        original = df["surface"].copy()
        result = impute_surface(df)
        assert result["surface"].equals(original)

    def test_nulls_are_filled(self):
        df = _make_base_df(40)
        null_idx = [5, 10, 20]
        df.loc[null_idx, "surface"] = None
        result = impute_surface(df)
        assert result.loc[null_idx, "surface"].notna().all()

    def test_imputed_flag_set(self):
        df = _make_base_df(40)
        df.loc[7, "surface"] = None
        result = impute_surface(df)
        assert result.loc[7, "surface_imputed"] is True or result.loc[7, "surface_imputed"] == True

    def test_non_null_rows_not_flagged(self):
        df = _make_base_df(30)
        df.loc[2, "surface"] = None
        result = impute_surface(df)
        non_null_mask = result.index != 2
        assert result.loc[non_null_mask, "surface_imputed"].eq(False).all()


# ── detect_outliers ───────────────────────────────────────────────────────────

class TestDetectOutliers:
    def test_extreme_prices_flagged(self):
        df = _make_base_df(80)
        # Insert extreme outlier
        df.loc[0, "uf_m2_u"] = 9999.0   # way above any type limit
        result = detect_outliers(df)
        assert "is_outlier" in result.columns
        assert result.loc[0, "is_outlier"] == True

    def test_normal_prices_not_flagged(self):
        df = _make_base_df(80, seed=5)
        result = detect_outliers(df)
        # With normal synthetic data, most should not be outliers
        assert result["is_outlier"].mean() < 0.2, "Too many rows flagged as outliers"

    def test_outliers_not_dropped(self):
        """detect_outliers marks but does NOT remove rows."""
        df = _make_base_df(40)
        df.loc[0, "uf_m2_u"] = 9999.0
        result = detect_outliers(df)
        assert len(result) == len(df)

    def test_is_outlier_column_boolean(self):
        df = _make_base_df(30)
        result = detect_outliers(df)
        assert result["is_outlier"].dtype in (bool, object, "bool")
        # All values are boolean-ish
        assert set(result["is_outlier"].unique()).issubset({True, False, None})
