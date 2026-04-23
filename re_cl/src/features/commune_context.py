"""
commune_context.py
------------------
Loads and enriches per-commune contextual data for scoring dimensions:
  - growth_index: demographic + economic growth (0–1)
  - metro_access: number of metro stations in commune (proxy for accessibility)
  - commercial_activity: normalized commercial activity index (0–1)
  - densidad_norm: population density normalized (0–1)       [V5.2 INE Census]
  - educacion_score: % higher education normalized (0–1)     [V5.2 INE Census]
  - hacinamiento_score: overcrowding inverted (0=worst,1=best) [V5.2 INE Census]
  - crime_index: CEAD crime index inverted (0=highest,1=safest) [V5.3 CEAD]

Data sources:
  - data/processed/commune_growth_index.csv  (INE 2017/2022 + SII + Metro)
  - data/processed/commune_ine_census.csv    (INE Censo 2017 estimates — V5.2)
  - data/processed/commune_crime_index.csv   (CEAD 2013-2016 estimates — V5.3)

Usage:
    from src.features.commune_context import load_commune_growth, enrich_with_commune_context

    # Load growth table
    growth_df = load_commune_growth()

    # Enrich a DataFrame that has 'county_name'
    df = enrich_with_commune_context(df)
    # → adds growth_score, commercial_score, metro_location_score,
    #         densidad_norm, educacion_score, hacinamiento_score, crime_index
"""

import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

# ---------------------------------------------------------------------------
# File paths (overrideable via env vars)
# ---------------------------------------------------------------------------
_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"

GROWTH_CSV = Path(os.getenv(
    "COMMUNE_GROWTH_CSV",
    _DATA_DIR / "commune_growth_index.csv"
))

INE_CENSUS_CSV = Path(os.getenv(
    "COMMUNE_INE_CENSUS_CSV",
    _DATA_DIR / "commune_ine_census.csv"
))

CRIME_INDEX_CSV = Path(os.getenv(
    "COMMUNE_CRIME_CSV",
    _DATA_DIR / "commune_crime_index.csv"
))

# ---------------------------------------------------------------------------
# Normalization: fuzzy match for common spelling variants
# ---------------------------------------------------------------------------
COUNTY_ALIASES = {
    "nuñoa":         "Ñuñoa",
    "ñunoa":         "Ñuñoa",
    "las condes":    "Las Condes",
    "providencia":   "Providencia",
    "vitacura":      "Vitacura",
    "la florida":    "La Florida",
    "maipu":         "Maipú",
    "maipú":         "Maipú",
    "puente alto":   "Puente Alto",
    "la reina":      "La Reina",
    "san miguel":    "San Miguel",
    "san bernardo":  "San Bernardo",
    "lo barnechea":  "Lo Barnechea",
    "quilicura":     "Quilicura",
    "pudahuel":      "Pudahuel",
    "penalolen":     "Peñalolén",
    "peñalolen":     "Peñalolén",
    "colina":        "Colina",
    "lampa":         "Lampa",
    "huechuraba":    "Huechuraba",
}


def normalize_county_name(name: str) -> str:
    """Normalize commune name for fuzzy matching."""
    if not isinstance(name, str):
        return name
    key = name.strip().lower()
    return COUNTY_ALIASES.get(key, name.strip())


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_commune_growth() -> pd.DataFrame:
    """
    Load commune growth index CSV.
    Returns DataFrame with: county_name, growth_index, growth_pct_5y,
    commercial_activity_index, metro_stations.
    Falls back to empty DataFrame if file not found.
    """
    if not GROWTH_CSV.exists():
        logger.warning(f"Commune growth data not found: {GROWTH_CSV}. growth_score will default to 0.5.")
        return pd.DataFrame(columns=["county_name", "growth_index"])

    df = pd.read_csv(GROWTH_CSV)

    # Deduplicate (Pudahuel appears twice in CSV — keep highest growth_index)
    df = df.sort_values("growth_index", ascending=False).drop_duplicates("county_name")

    # Normalize county names
    df["county_name"] = df["county_name"].str.strip()

    logger.info(f"Loaded commune growth data: {len(df)} communes")
    return df[["county_name", "growth_index", "growth_pct_5y",
               "commercial_activity_index", "metro_stations"]].copy()


@lru_cache(maxsize=1)
def load_ine_census() -> pd.DataFrame:
    """
    Load INE Census 2017 enrichment data per commune.

    Returns DataFrame with normalized columns:
      - county_name
      - densidad_hab_km2   (raw)
      - densidad_norm      (0–1, log-scaled)
      - pct_educacion_superior (raw fraction)
      - educacion_score    (0–1, direct normalization)
      - hacinamiento_index (raw fraction, higher = worse)
      - hacinamiento_score (0–1, inverted: 1 = best / lowest overcrowding)
      - median_age
      - pct_propietarios
      - pct_hogares_monoparentales

    Source: data/processed/commune_ine_census.csv
    NOTE: Values are estimates based on public INE Censo 2017 data.
    """
    if not INE_CENSUS_CSV.exists():
        logger.warning(
            f"INE Census data not found: {INE_CENSUS_CSV}. "
            "Census enrichment features will default to 0.5."
        )
        return pd.DataFrame(columns=["county_name", "densidad_norm",
                                     "educacion_score", "hacinamiento_score"])

    df = pd.read_csv(INE_CENSUS_CSV, comment="#")
    df["county_name"] = df["county_name"].str.strip()

    # --- densidad_norm: log-scaled to reduce effect of extreme outliers ---
    max_log_dens = np.log1p(df["densidad_hab_km2"].max())
    if max_log_dens > 0:
        df["densidad_norm"] = (np.log1p(df["densidad_hab_km2"]) / max_log_dens).clip(0, 1)
    else:
        df["densidad_norm"] = 0.5

    # --- educacion_score: direct min-max normalization ---
    edu_min = df["pct_educacion_superior"].min()
    edu_max = df["pct_educacion_superior"].max()
    if edu_max > edu_min:
        df["educacion_score"] = (
            (df["pct_educacion_superior"] - edu_min) / (edu_max - edu_min)
        ).clip(0, 1)
    else:
        df["educacion_score"] = 0.5

    # --- hacinamiento_score: inverted (lower overcrowding → higher score) ---
    hac_min = df["hacinamiento_index"].min()
    hac_max = df["hacinamiento_index"].max()
    if hac_max > hac_min:
        df["hacinamiento_score"] = (
            1.0 - (df["hacinamiento_index"] - hac_min) / (hac_max - hac_min)
        ).clip(0, 1)
    else:
        df["hacinamiento_score"] = 0.5

    logger.info(f"Loaded INE Census data: {len(df)} communes")
    return df[["county_name", "densidad_hab_km2", "densidad_norm",
               "pct_educacion_superior", "educacion_score",
               "hacinamiento_index", "hacinamiento_score",
               "median_age", "pct_propietarios",
               "pct_hogares_monoparentales"]].copy()


@lru_cache(maxsize=1)
def load_crime_index() -> pd.DataFrame:
    """
    Load CEAD crime index per commune.

    Returns DataFrame with:
      - county_name
      - crime_index          (0–1 inverted: 0=highest crime, 1=safest)
      - robbery_rate_per_10k
      - assault_rate_per_10k
      - crime_tier           (alto / medio / bajo)

    Source: data/processed/commune_crime_index.csv
    NOTE: Values are estimates based on public CEAD Chile reports (2013-2016).
    """
    if not CRIME_INDEX_CSV.exists():
        logger.warning(
            f"Crime index data not found: {CRIME_INDEX_CSV}. "
            "crime_index will default to 0.5."
        )
        return pd.DataFrame(columns=["county_name", "crime_index", "crime_tier"])

    df = pd.read_csv(CRIME_INDEX_CSV, comment="#")
    df["county_name"] = df["county_name"].str.strip()

    logger.info(f"Loaded CEAD crime index data: {len(df)} communes")
    return df[["county_name", "crime_index",
               "robbery_rate_per_10k", "assault_rate_per_10k",
               "crime_tier"]].copy()


# ---------------------------------------------------------------------------
# Enrichment function
# ---------------------------------------------------------------------------

def enrich_with_commune_context(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich a DataFrame with commune-level context features.

    Adds the following columns (all filled with sensible defaults for
    communes not found in the reference data):

    From commune_growth_index.csv:
      - growth_score          (0–1)
      - commercial_score      (0–1)
      - metro_location_score  (0–1, log-scaled metro stations)

    From commune_ine_census.csv (V5.2):
      - densidad_norm         (0–1, log-scaled population density)
      - educacion_score       (0–1, % higher education)
      - hacinamiento_score    (0–1 inverted, lower overcrowding = higher score)

    From commune_crime_index.csv (V5.3):
      - crime_index           (0–1 inverted, safer = higher)

    Input df must have a 'county_name' column.
    """
    if "county_name" not in df.columns:
        raise ValueError("enrich_with_commune_context: df must have 'county_name' column")

    df = df.copy()
    df["_county_norm"] = df["county_name"].apply(normalize_county_name)

    # --- 1. Growth / commercial / metro ---
    growth_df = load_commune_growth()
    if growth_df.empty:
        df["growth_score"]        = 0.5
        df["commercial_score"]    = 0.5
        df["metro_location_score"] = 0.3
    else:
        merged = df.merge(
            growth_df.rename(columns={"county_name": "_county_norm"}),
            on="_county_norm",
            how="left",
        )
        merged["growth_score"]     = merged["growth_index"].fillna(0.5)
        merged["commercial_score"] = merged["commercial_activity_index"].fillna(0.5)

        max_stations = growth_df["metro_stations"].max()
        if max_stations > 0:
            merged["metro_location_score"] = (
                np.log1p(merged["metro_stations"].fillna(0)) /
                np.log1p(max_stations)
            ).clip(0, 1)
        else:
            merged["metro_location_score"] = 0.3

        merged = merged.drop(columns=["growth_index", "commercial_activity_index",
                                       "metro_stations", "growth_pct_5y"],
                             errors="ignore")
        df = merged

    # --- 2. INE Census enrichment (V5.2) ---
    ine_df = load_ine_census()
    if ine_df.empty:
        df["densidad_norm"]      = 0.5
        df["educacion_score"]    = 0.5
        df["hacinamiento_score"] = 0.5
    else:
        df = df.merge(
            ine_df[["county_name", "densidad_norm", "educacion_score",
                    "hacinamiento_score", "median_age", "pct_propietarios",
                    "pct_hogares_monoparentales"]]
            .rename(columns={"county_name": "_county_norm"}),
            on="_county_norm",
            how="left",
        )
        df["densidad_norm"]      = df["densidad_norm"].fillna(0.5)
        df["educacion_score"]    = df["educacion_score"].fillna(0.5)
        df["hacinamiento_score"] = df["hacinamiento_score"].fillna(0.5)

    # --- 3. CEAD crime enrichment (V5.3) ---
    crime_df = load_crime_index()
    if crime_df.empty:
        df["crime_index"] = 0.5
        df["crime_tier"]  = "medio"
    else:
        df = df.merge(
            crime_df[["county_name", "crime_index", "crime_tier"]]
            .rename(columns={"county_name": "_county_norm"}),
            on="_county_norm",
            how="left",
        )
        df["crime_index"] = df["crime_index"].fillna(0.5)
        df["crime_tier"]  = df["crime_tier"].fillna("medio")

    # Drop temp column
    df = df.drop(columns=["_county_norm"], errors="ignore")

    logger.debug(f"Enriched {len(df):,} rows with commune context "
                 "(growth + INE census + CEAD crime)")
    return df


# ---------------------------------------------------------------------------
# Single-commune helpers
# ---------------------------------------------------------------------------

def get_growth_index(county_name: str) -> float:
    """Look up growth_index for a single commune. Returns 0.5 if not found."""
    growth_df = load_commune_growth()
    if growth_df.empty:
        return 0.5
    norm = normalize_county_name(county_name)
    row = growth_df[growth_df["county_name"] == norm]
    if row.empty:
        return 0.5
    return float(row.iloc[0]["growth_index"])


def get_crime_index(county_name: str) -> float:
    """Look up crime_index for a single commune. Returns 0.5 if not found."""
    crime_df = load_crime_index()
    if crime_df.empty:
        return 0.5
    norm = normalize_county_name(county_name)
    row = crime_df[crime_df["county_name"] == norm]
    if row.empty:
        return 0.5
    return float(row.iloc[0]["crime_index"])


def get_census_features(county_name: str) -> dict:
    """
    Return INE Census features for a single commune.
    Keys: densidad_norm, educacion_score, hacinamiento_score, median_age,
          pct_propietarios, pct_hogares_monoparentales.
    All default to 0.5 (or None for string fields) if not found.
    """
    ine_df = load_ine_census()
    defaults = {
        "densidad_norm": 0.5,
        "educacion_score": 0.5,
        "hacinamiento_score": 0.5,
        "median_age": None,
        "pct_propietarios": None,
        "pct_hogares_monoparentales": None,
    }
    if ine_df.empty:
        return defaults
    norm = normalize_county_name(county_name)
    row = ine_df[ine_df["county_name"] == norm]
    if row.empty:
        return defaults
    r = row.iloc[0]
    return {
        "densidad_norm":              float(r["densidad_norm"]),
        "educacion_score":            float(r["educacion_score"]),
        "hacinamiento_score":         float(r["hacinamiento_score"]),
        "median_age":                 float(r["median_age"]),
        "pct_propietarios":           float(r["pct_propietarios"]),
        "pct_hogares_monoparentales": float(r["pct_hogares_monoparentales"]),
    }
