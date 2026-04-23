"""
test_commune_context.py
-----------------------
Tests for src/features/commune_context.py (V4.2 / V5.2 / V5.3 additions):
  - load_ine_census()
  - load_crime_index()
  - enrich_with_commune_context()

Uses the real CSV files in data/processed/ — no DB, no HTTP.
"""

import pandas as pd
import pytest


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def simple_df() -> pd.DataFrame:
    return pd.DataFrame({
        "county_name": ["Las Condes", "La Pintana", "Unknown Commune"],
        "opportunity_score": [0.8, 0.3, 0.5],
    })


# ── load_ine_census ────────────────────────────────────────────────────────────

def test_load_ine_census_returns_dataframe():
    from src.features.commune_context import load_ine_census
    # Clear any cached result from previous test runs
    load_ine_census.cache_clear()
    df = load_ine_census()
    assert isinstance(df, pd.DataFrame)


def test_load_ine_census_expected_columns():
    from src.features.commune_context import load_ine_census
    load_ine_census.cache_clear()
    df = load_ine_census()
    for col in ["county_name", "densidad_norm", "educacion_score", "hacinamiento_score"]:
        assert col in df.columns, f"Missing column: {col}"


def test_load_ine_census_values_in_0_1_range():
    from src.features.commune_context import load_ine_census
    load_ine_census.cache_clear()
    df = load_ine_census()
    if df.empty:
        pytest.skip("INE census CSV not found — skipping range test")
    for col in ["densidad_norm", "educacion_score", "hacinamiento_score"]:
        assert df[col].between(0, 1).all(), (
            f"{col} has values outside [0, 1]: {df[col].describe()}"
        )


def test_load_ine_census_no_nulls_in_scores():
    from src.features.commune_context import load_ine_census
    load_ine_census.cache_clear()
    df = load_ine_census()
    if df.empty:
        pytest.skip("INE census CSV not found")
    for col in ["educacion_score", "hacinamiento_score", "densidad_norm"]:
        assert df[col].notna().all(), f"{col} has unexpected NaNs"


def test_load_ine_census_las_condes_high_education():
    """Las Condes has the highest pct_educacion_superior — should score near 1."""
    from src.features.commune_context import load_ine_census
    load_ine_census.cache_clear()
    df = load_ine_census()
    if df.empty:
        pytest.skip("INE census CSV not found")
    row = df[df["county_name"] == "Las Condes"]
    if row.empty:
        pytest.skip("Las Condes not in INE census CSV")
    # Should be well above the midpoint
    assert float(row["educacion_score"].iloc[0]) > 0.5


def test_load_ine_census_la_pintana_lower_education_than_las_condes():
    from src.features.commune_context import load_ine_census
    load_ine_census.cache_clear()
    df = load_ine_census()
    if df.empty:
        pytest.skip("INE census CSV not found")
    lc = df[df["county_name"] == "Las Condes"]
    lp = df[df["county_name"] == "La Pintana"]
    if lc.empty or lp.empty:
        pytest.skip("One or both communes not in INE census CSV")
    assert float(lc["educacion_score"].iloc[0]) > float(lp["educacion_score"].iloc[0])


# ── load_crime_index ───────────────────────────────────────────────────────────

def test_load_crime_index_returns_dataframe():
    from src.features.commune_context import load_crime_index
    load_crime_index.cache_clear()
    df = load_crime_index()
    assert isinstance(df, pd.DataFrame)


def test_load_crime_index_expected_columns():
    from src.features.commune_context import load_crime_index
    load_crime_index.cache_clear()
    df = load_crime_index()
    for col in ["county_name", "crime_index"]:
        assert col in df.columns, f"Missing column: {col}"


def test_load_crime_index_values_in_0_1_range():
    from src.features.commune_context import load_crime_index
    load_crime_index.cache_clear()
    df = load_crime_index()
    if df.empty:
        pytest.skip("Crime CSV not found")
    assert df["crime_index"].between(0, 1).all(), (
        f"crime_index out of range: {df['crime_index'].describe()}"
    )


def test_load_crime_index_las_condes_higher_than_la_pintana():
    """Crime index is inverted: safer = higher. Las Condes is safer."""
    from src.features.commune_context import load_crime_index
    load_crime_index.cache_clear()
    df = load_crime_index()
    if df.empty:
        pytest.skip("Crime CSV not found")
    lc = df[df["county_name"] == "Las Condes"]
    lp = df[df["county_name"] == "La Pintana"]
    if lc.empty or lp.empty:
        pytest.skip("One or both communes not in crime CSV")
    assert float(lc["crime_index"].iloc[0]) > float(lp["crime_index"].iloc[0])


# ── enrich_with_commune_context ───────────────────────────────────────────────

def test_enrich_adds_growth_score(simple_df):
    from src.features.commune_context import enrich_with_commune_context, load_commune_growth, load_ine_census, load_crime_index
    load_commune_growth.cache_clear()
    load_ine_census.cache_clear()
    load_crime_index.cache_clear()
    result = enrich_with_commune_context(simple_df.copy())
    assert "growth_score" in result.columns


def test_enrich_adds_educacion_score(simple_df):
    from src.features.commune_context import enrich_with_commune_context, load_commune_growth, load_ine_census, load_crime_index
    load_commune_growth.cache_clear()
    load_ine_census.cache_clear()
    load_crime_index.cache_clear()
    result = enrich_with_commune_context(simple_df.copy())
    assert "educacion_score" in result.columns


def test_enrich_adds_crime_index(simple_df):
    from src.features.commune_context import enrich_with_commune_context, load_commune_growth, load_ine_census, load_crime_index
    load_commune_growth.cache_clear()
    load_ine_census.cache_clear()
    load_crime_index.cache_clear()
    result = enrich_with_commune_context(simple_df.copy())
    assert "crime_index" in result.columns


def test_enrich_preserves_row_count(simple_df):
    from src.features.commune_context import enrich_with_commune_context, load_commune_growth, load_ine_census, load_crime_index
    load_commune_growth.cache_clear()
    load_ine_census.cache_clear()
    load_crime_index.cache_clear()
    result = enrich_with_commune_context(simple_df.copy())
    assert len(result) == len(simple_df)


def test_enrich_scores_in_0_1_range(simple_df):
    from src.features.commune_context import enrich_with_commune_context, load_commune_growth, load_ine_census, load_crime_index
    load_commune_growth.cache_clear()
    load_ine_census.cache_clear()
    load_crime_index.cache_clear()
    result = enrich_with_commune_context(simple_df.copy())
    for col in ["growth_score", "educacion_score", "crime_index"]:
        if col in result.columns:
            assert result[col].between(0, 1).all(), (
                f"{col} has values outside [0, 1]"
            )


def test_enrich_unknown_commune_defaults_to_0_5(simple_df):
    """Rows with an unrecognised commune should fall back to 0.5 defaults."""
    from src.features.commune_context import enrich_with_commune_context, load_commune_growth, load_ine_census, load_crime_index
    load_commune_growth.cache_clear()
    load_ine_census.cache_clear()
    load_crime_index.cache_clear()
    result = enrich_with_commune_context(simple_df.copy())
    unknown_row = result[result["county_name"] == "Unknown Commune"].iloc[0]
    assert unknown_row["growth_score"] == pytest.approx(0.5)
    assert unknown_row["educacion_score"] == pytest.approx(0.5)
    assert unknown_row["crime_index"] == pytest.approx(0.5)


def test_enrich_las_condes_higher_education_than_la_pintana(simple_df):
    from src.features.commune_context import enrich_with_commune_context, load_commune_growth, load_ine_census, load_crime_index
    load_commune_growth.cache_clear()
    load_ine_census.cache_clear()
    load_crime_index.cache_clear()
    result = enrich_with_commune_context(simple_df.copy())
    edu_lc = float(result[result["county_name"] == "Las Condes"]["educacion_score"].iloc[0])
    edu_lp = float(result[result["county_name"] == "La Pintana"]["educacion_score"].iloc[0])
    assert edu_lc > edu_lp


def test_enrich_la_pintana_lower_crime_index_than_las_condes(simple_df):
    """
    crime_index is inverted (safer = higher).
    La Pintana (alto crime) should have a lower crime_index than Las Condes (bajo).
    """
    from src.features.commune_context import enrich_with_commune_context, load_commune_growth, load_ine_census, load_crime_index
    load_commune_growth.cache_clear()
    load_ine_census.cache_clear()
    load_crime_index.cache_clear()
    result = enrich_with_commune_context(simple_df.copy())
    ci_lc = float(result[result["county_name"] == "Las Condes"]["crime_index"].iloc[0])
    ci_lp = float(result[result["county_name"] == "La Pintana"]["crime_index"].iloc[0])
    assert ci_lp < ci_lc


def test_enrich_raises_without_county_name_column():
    from src.features.commune_context import enrich_with_commune_context
    df_no_county = pd.DataFrame({"opportunity_score": [0.5, 0.8]})
    with pytest.raises(ValueError, match="county_name"):
        enrich_with_commune_context(df_no_county)


def test_enrich_does_not_mutate_input(simple_df):
    from src.features.commune_context import enrich_with_commune_context, load_commune_growth, load_ine_census, load_crime_index
    load_commune_growth.cache_clear()
    load_ine_census.cache_clear()
    load_crime_index.cache_clear()
    original_cols = set(simple_df.columns)
    _ = enrich_with_commune_context(simple_df)
    assert set(simple_df.columns) == original_cols
