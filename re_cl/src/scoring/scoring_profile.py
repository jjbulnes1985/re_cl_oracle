"""
scoring_profile.py
------------------
Configurable scoring profiles for opportunity score computation.

Allows clients to weight different dimensions of the opportunity score
according to their investment thesis:

  DEFAULT:   undervaluation 70% | confidence 30%

  LOCATION:  undervaluation 40% | location 40% | confidence 20%
             (prioritizes spatial premium / accessibility)

  GROWTH:    undervaluation 35% | population_growth 35% | confidence 30%
             (prioritizes communes with demographic tailwinds)

  LIQUIDITY: undervaluation 50% | volume 30% | confidence 20%
             (prioritizes high-transaction-volume areas → easier exit)

  SAFETY:    undervaluation 45% | crime_index 25% | confidence 20% | growth_score 10%
             (prioritizes low-crime communes with quality of life signals)

  CUSTOM:    user-defined weights (must sum to 1.0)

Each profile specifies:
  - weights: dict {dimension → float}  (sum must equal 1.0)
  - description: human-readable explanation
  - required_columns: columns that must exist in the input DataFrame

Dimensions available:
  - undervaluation_score : how much below predicted price (0-1)
  - data_confidence      : data completeness / reliability (0-1)
  - location_score       : spatial score (proximity to metro, services) (0-1)
  - growth_score         : commune population / economic growth proxy (0-1)
  - volume_score         : transaction volume percentile in the area (0-1)
  - crime_index          : CEAD safety index inverted (0=high crime, 1=safest) (0-1)
  - census_score         : composite INE census score (education + density + overcrowding) (0-1)

Usage:
    from src.scoring.scoring_profile import ScoringProfile, compute_profile_score

    profile = ScoringProfile.from_name("location")
    df = compute_profile_score(df, profile)
    # df now has 'opportunity_score' column computed with location weights
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np
import pandas as pd
from loguru import logger


# ── Built-in profiles ─────────────────────────────────────────────────────────

BUILTIN_PROFILES: Dict[str, dict] = {
    "default": {
        "description": "Balance estándar: subvaloración 70%, confianza 30%.",
        "weights": {
            "undervaluation_score": 0.70,
            "data_confidence":      0.30,
        },
    },
    "location": {
        "description": (
            "Prioriza ubicación: subvaloración 40%, score de ubicación 40%, confianza 20%. "
            "Ideal para estrategias de valor por accesibilidad y zona."
        ),
        "weights": {
            "undervaluation_score": 0.40,
            "location_score":       0.40,
            "data_confidence":      0.20,
        },
    },
    "growth": {
        "description": (
            "Prioriza crecimiento demográfico: subvaloración 35%, crecimiento 35%, confianza 30%. "
            "Ideal para comprar en comunas con expansión de población y actividad económica."
        ),
        "weights": {
            "undervaluation_score": 0.35,
            "growth_score":         0.35,
            "data_confidence":      0.30,
        },
    },
    "liquidity": {
        "description": (
            "Prioriza liquidez: subvaloración 50%, volumen de transacciones 30%, confianza 20%. "
            "Ideal para inversores que necesitan salida rápida."
        ),
        "weights": {
            "undervaluation_score": 0.50,
            "volume_score":         0.30,
            "data_confidence":      0.20,
        },
    },
    "safety": {
        "description": (
            "Prioriza seguridad y calidad de vida: subvaloración 45%, índice de criminalidad 25%, "
            "confianza 20%, crecimiento comunal 10%. "
            "Ideal para comprar en comunas seguras con buena infraestructura social."
        ),
        "weights": {
            "undervaluation_score": 0.45,
            "crime_index":          0.25,
            "data_confidence":      0.20,
            "growth_score":         0.10,
        },
    },
}


# ── Scoring Profile dataclass ─────────────────────────────────────────────────

@dataclass
class ScoringProfile:
    name:        str
    description: str
    weights:     Dict[str, float]

    def validate(self) -> None:
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Profile '{self.name}': weights must sum to 1.0, got {total:.4f}. "
                f"Weights: {self.weights}"
            )
        for dim, w in self.weights.items():
            if not (0.0 <= w <= 1.0):
                raise ValueError(f"Profile '{self.name}': weight for '{dim}' must be in [0,1], got {w}")

    @classmethod
    def from_name(cls, name: str) -> "ScoringProfile":
        """Load a built-in profile by name."""
        name = name.lower().strip()
        if name not in BUILTIN_PROFILES:
            raise ValueError(
                f"Unknown profile '{name}'. Available: {list(BUILTIN_PROFILES.keys())}"
            )
        spec = BUILTIN_PROFILES[name]
        profile = cls(name=name, description=spec["description"], weights=dict(spec["weights"]))
        profile.validate()
        return profile

    @classmethod
    def custom(
        cls,
        undervaluation: float = 0.70,
        confidence:     float = 0.30,
        location:       float = 0.0,
        growth:         float = 0.0,
        volume:         float = 0.0,
        crime:          float = 0.0,
        census:         float = 0.0,
        description:    str   = "Custom profile",
    ) -> "ScoringProfile":
        """
        Build a custom profile from explicit weight parameters.
        Weights are automatically normalized to sum to 1.0.

        Example:
            profile = ScoringProfile.custom(undervaluation=0.5, location=0.3, confidence=0.2)
            profile = ScoringProfile.custom(undervaluation=0.45, crime=0.25, confidence=0.2, growth=0.1)
        """
        raw = {
            "undervaluation_score": undervaluation,
            "data_confidence":      confidence,
            "location_score":       location,
            "growth_score":         growth,
            "volume_score":         volume,
            "crime_index":          crime,
            "census_score":         census,
        }
        # Keep only non-zero dimensions
        active = {k: v for k, v in raw.items() if v > 0}
        if not active:
            raise ValueError("All weights are 0. At least one dimension must have weight > 0.")

        total = sum(active.values())
        normalized = {k: round(v / total, 6) for k, v in active.items()}

        profile = cls(name="custom", description=description, weights=normalized)
        profile.validate()
        logger.info(f"Custom profile: {normalized}")
        return profile

    @classmethod
    def from_env(cls) -> "ScoringProfile":
        """
        Load profile from env vars. Falls back to 'default'.
        Env vars:
          SCORING_PROFILE=location           → named profile
          SCORING_PROFILE=custom             → reads WEIGHT_* vars below
          WEIGHT_UNDERVALUATION=0.5
          WEIGHT_CONFIDENCE=0.2
          WEIGHT_LOCATION=0.3
          WEIGHT_GROWTH=0.0
          WEIGHT_VOLUME=0.0
        """
        profile_name = os.getenv("SCORING_PROFILE", "default").lower()
        if profile_name == "custom":
            return cls.custom(
                undervaluation = float(os.getenv("WEIGHT_UNDERVALUATION", "0.70")),
                confidence     = float(os.getenv("WEIGHT_CONFIDENCE",     "0.30")),
                location       = float(os.getenv("WEIGHT_LOCATION",       "0.00")),
                growth         = float(os.getenv("WEIGHT_GROWTH",         "0.00")),
                volume         = float(os.getenv("WEIGHT_VOLUME",         "0.00")),
                crime          = float(os.getenv("WEIGHT_CRIME",          "0.00")),
                census         = float(os.getenv("WEIGHT_CENSUS",         "0.00")),
            )
        return cls.from_name(profile_name)

    def summary(self) -> str:
        lines = [f"Profile: {self.name}", f"  {self.description}"]
        for dim, w in sorted(self.weights.items(), key=lambda x: -x[1]):
            lines.append(f"  {dim}: {w*100:.1f}%")
        return "\n".join(lines)


# ── Auxiliary dimension scores ────────────────────────────────────────────────

def compute_location_score(df: pd.DataFrame) -> pd.Series:
    """
    Compute a location score (0-1) as a normalized inverse of dist_km_centroid.

    Properties closer to the commune centroid (proxy for urban core) score higher.
    Falls back to 0.5 if dist_km_centroid is not available.
    """
    if "dist_km_centroid" not in df.columns or df["dist_km_centroid"].isna().all():
        logger.warning("dist_km_centroid not available — location_score defaulting to 0.5")
        return pd.Series(0.5, index=df.index)

    dist = df["dist_km_centroid"].clip(lower=0)
    max_dist = dist.quantile(0.99)
    if max_dist == 0:
        return pd.Series(1.0, index=df.index)

    # Inverse: closer = higher score
    raw = 1.0 - (dist / max_dist).clip(0, 1)
    return raw.fillna(0.5).round(4)


def compute_growth_score(df: pd.DataFrame, commune_growth: Optional[pd.DataFrame] = None) -> pd.Series:
    """
    Compute a growth score (0-1) per commune.

    Priority:
      1. commune_growth DataFrame if explicitly provided
      2. INE commune growth index from data/processed/commune_growth_index.csv
      3. Cluster density proxy (dense = higher activity)
      4. Default 0.5

    commune_growth.growth_index should be pre-normalized to [0,1].
    """
    if commune_growth is not None and "county_name" in commune_growth.columns:
        merged = df[["county_name"]].merge(
            commune_growth[["county_name", "growth_index"]],
            on="county_name", how="left"
        )
        return merged["growth_index"].fillna(0.5).values

    # Auto-load INE data
    try:
        from src.features.commune_context import load_commune_growth
        ine_df = load_commune_growth()
        if not ine_df.empty and "county_name" in df.columns:
            merged = df[["county_name"]].merge(
                ine_df[["county_name", "growth_index"]],
                on="county_name", how="left"
            )
            covered = merged["growth_index"].notna().mean()
            logger.debug(f"INE growth data coverage: {covered*100:.0f}%")
            return merged["growth_index"].fillna(0.5).round(4)
    except Exception as e:
        logger.debug(f"Could not load INE growth data: {e}")

    # Proxy: use cluster density
    if "cluster_id" in df.columns and df["cluster_id"].notna().any():
        cluster_counts = df["cluster_id"].value_counts()
        max_count = cluster_counts.max()
        raw = df["cluster_id"].map(cluster_counts).fillna(1) / max_count
        return raw.clip(0, 1).round(4)

    logger.warning("No growth data available — growth_score defaulting to 0.5")
    return pd.Series(0.5, index=df.index)


def compute_volume_score(df: pd.DataFrame) -> pd.Series:
    """
    Compute a transaction volume score (0-1) by commune + typology.

    Higher volume → easier exit → higher liquidity score.
    """
    if "county_name" not in df.columns or "project_type" not in df.columns:
        return pd.Series(0.5, index=df.index)

    counts = df.groupby(["county_name", "project_type"])["id"].transform("count")
    max_count = counts.max()
    if max_count == 0:
        return pd.Series(0.5, index=df.index)

    return (counts / max_count).clip(0, 1).round(4)


def compute_crime_index(df: pd.DataFrame) -> pd.Series:
    """
    Compute crime_index (0-1, higher = safer) per commune.

    Loads from CEAD crime index via commune_context.
    Falls back to 0.5 if data unavailable or county_name column missing.
    """
    if "county_name" not in df.columns:
        logger.warning("county_name not available — crime_index defaulting to 0.5")
        return pd.Series(0.5, index=df.index)

    try:
        from src.features.commune_context import load_crime_index
        crime_df = load_crime_index()
        if crime_df.empty:
            logger.warning("Crime index data empty — crime_index defaulting to 0.5")
            return pd.Series(0.5, index=df.index)
        merged = df[["county_name"]].merge(
            crime_df[["county_name", "crime_index"]],
            on="county_name", how="left"
        )
        covered = merged["crime_index"].notna().mean()
        logger.debug(f"Crime index coverage: {covered*100:.0f}%")
        return merged["crime_index"].fillna(0.5).round(4)
    except Exception as e:
        logger.debug(f"Could not load crime index: {e}")
        return pd.Series(0.5, index=df.index)


def compute_census_score(df: pd.DataFrame) -> pd.Series:
    """
    Compute a composite census score (0-1) per commune.

    Combines educacion_score and hacinamiento_score (equal weight) from INE Census.
    Falls back to 0.5 if data unavailable or county_name column missing.
    """
    if "county_name" not in df.columns:
        logger.warning("county_name not available — census_score defaulting to 0.5")
        return pd.Series(0.5, index=df.index)

    try:
        from src.features.commune_context import load_ine_census
        ine_df = load_ine_census()
        if ine_df.empty:
            logger.warning("INE Census data empty — census_score defaulting to 0.5")
            return pd.Series(0.5, index=df.index)
        merged = df[["county_name"]].merge(
            ine_df[["county_name", "educacion_score", "hacinamiento_score"]],
            on="county_name", how="left"
        )
        edu  = merged["educacion_score"].fillna(0.5)
        hac  = merged["hacinamiento_score"].fillna(0.5)
        score = ((edu + hac) / 2.0).clip(0, 1).round(4)
        covered = merged["educacion_score"].notna().mean()
        logger.debug(f"Census score coverage: {covered*100:.0f}%")
        return score
    except Exception as e:
        logger.debug(f"Could not load INE census data: {e}")
        return pd.Series(0.5, index=df.index)


def _ensure_dimensions(df: pd.DataFrame, profile: ScoringProfile) -> pd.DataFrame:
    """Compute any auxiliary dimensions required by the profile that are missing."""
    df = df.copy()
    dims_needed = set(profile.weights.keys())

    if "location_score" in dims_needed and "location_score" not in df.columns:
        df["location_score"] = compute_location_score(df)

    if "growth_score" in dims_needed and "growth_score" not in df.columns:
        df["growth_score"] = compute_growth_score(df)

    if "volume_score" in dims_needed and "volume_score" not in df.columns:
        df["volume_score"] = compute_volume_score(df)

    if "crime_index" in dims_needed and "crime_index" not in df.columns:
        df["crime_index"] = compute_crime_index(df)

    if "census_score" in dims_needed and "census_score" not in df.columns:
        df["census_score"] = compute_census_score(df)

    return df


# ── Main scoring function ─────────────────────────────────────────────────────

def compute_profile_score(
    df: pd.DataFrame,
    profile: ScoringProfile,
    commune_growth: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Compute opportunity_score using the given ScoringProfile.

    Args:
        df: DataFrame with at minimum undervaluation_score and data_confidence columns.
        profile: ScoringProfile instance with weights.
        commune_growth: Optional DataFrame with (county_name, growth_index) for growth_score.

    Returns:
        df (copy) with added 'opportunity_score' and 'scoring_profile' columns.
    """
    profile.validate()
    df = _ensure_dimensions(df, profile)

    logger.info(f"Computing opportunity_score with profile: {profile.name}")
    logger.info(f"  Weights: {profile.weights}")

    score = pd.Series(0.0, index=df.index)
    missing_dims = []

    for dim, weight in profile.weights.items():
        if dim not in df.columns or df[dim].isna().all():
            missing_dims.append(dim)
            continue
        col = df[dim].fillna(0.0).clip(0, 1)
        score += col * weight

    if missing_dims:
        logger.warning(
            f"Profile '{profile.name}': missing dimensions {missing_dims}. "
            "Their weight redistributed to present dimensions via renormalization."
        )
        # Renormalize: compute effective weight from available dims only
        available_weight = sum(w for d, w in profile.weights.items() if d not in missing_dims)
        if available_weight > 0:
            score = score / available_weight
        else:
            score = pd.Series(np.nan, index=df.index)

    # Only score rows where at least undervaluation_score and data_confidence exist
    has_required = df["undervaluation_score"].notna() & df["data_confidence"].notna()
    final_score = pd.Series(np.nan, index=df.index)
    final_score[has_required] = score[has_required].clip(0, 1).round(4)

    df = df.copy()
    df["opportunity_score"] = final_score
    df["scoring_profile"]   = profile.name

    n_scored = final_score.notna().sum()
    mean_s   = final_score.mean()
    logger.info(
        f"Scored {n_scored:,} rows with profile '{profile.name}'. "
        f"Mean: {mean_s:.4f}"
    )
    return df


# ── Profile catalog for API/dashboard ────────────────────────────────────────

def list_profiles() -> list[dict]:
    """Return all built-in profiles as a list of dicts for API/UI consumption."""
    result = []
    for name, spec in BUILTIN_PROFILES.items():
        result.append({
            "name":        name,
            "description": spec["description"],
            "weights":     spec["weights"],
            "is_default":  name == "default",
        })
    return result
