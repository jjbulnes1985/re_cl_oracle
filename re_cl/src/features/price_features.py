"""
price_features.py
-----------------
Computes price-based features for the hedonic model:
  - gap_pct: winsorized (real_value_uf - calculated_value_uf) / calculated_value_uf
  - price_percentile_{25,50,75}: UF/m² percentiles by (project_type, county_name, year)
  - price_vs_median: ratio of actual UF/m² to median

Thesis features (V4.1 — Juan Montes MIT 2017):
  - age: 2014 - construction_year
  - age_sq: age²
  - construction_year_bucket: 7 categorical era buckets
  - city_zone: 4 RM Santiago zones (centro_norte, este, sur, oeste)
  - log_surface: log(surface_m2 + 1)

All functions accept a DataFrame and return a new DataFrame with added columns.
The run() function reads from transactions_clean and returns the full feature DataFrame.
"""

import os

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine

load_dotenv()

WINSOR_LOW  = 0.01
WINSOR_HIGH = 0.99

# Reference year for age computation (CBR data is 2013-2014)
AGE_REFERENCE_YEAR = 2014

CITY_ZONE_MAP = {
    # Centro-Norte
    'Santiago': 'centro_norte', 'Providencia': 'centro_norte',
    'Ñuñoa': 'centro_norte', 'Macul': 'centro_norte',
    'San Joaquín': 'centro_norte', 'Recoleta': 'centro_norte',
    'Independencia': 'centro_norte', 'Conchalí': 'centro_norte',
    'Huechuraba': 'centro_norte', 'Renca': 'centro_norte',
    'Cerro Navia': 'centro_norte', 'Lo Prado': 'centro_norte',
    'Quinta Normal': 'centro_norte', 'Estación Central': 'centro_norte',
    # Este
    'Las Condes': 'este', 'Vitacura': 'este', 'Lo Barnechea': 'este',
    'La Reina': 'este', 'Peñalolén': 'este', 'La Florida': 'este',
    # Sur
    'La Pintana': 'sur', 'San Ramón': 'sur', 'La Granja': 'sur',
    'San Miguel': 'sur', 'Lo Espejo': 'sur', 'Pedro Aguirre Cerda': 'sur',
    'El Bosque': 'sur', 'La Cisterna': 'sur', 'San Bernardo': 'sur',
    'Puente Alto': 'sur', 'Pirque': 'sur', 'San José De Maipo': 'sur',
    'Colina': 'sur', 'Lampa': 'sur', 'Tiltil': 'sur', 'Quilicura': 'sur',
    # Oeste
    'Maipú': 'oeste', 'Cerrillos': 'oeste', 'Padre Hurtado': 'oeste',
    'Peñaflor': 'oeste', 'El Monte': 'oeste', 'Isla De Maipo': 'oeste',
    'Melipilla': 'oeste', 'Curacaví': 'oeste', 'Alhué': 'oeste',
    'San Pedro': 'oeste', 'Pudahuel': 'oeste',
}


def construction_year_to_bucket(year) -> str:
    """Maps a construction year to an era bucket string."""
    if pd.isna(year):
        return 'unknown'
    year = int(year)
    if year <= 1960:
        return 'pre_1960'
    elif year <= 1970:
        return '1961_1970'
    elif year <= 1980:
        return '1971_1980'
    elif year <= 1990:
        return '1981_1990'
    elif year <= 2000:
        return '1991_2000'
    elif year <= 2006:
        return '2001_2006'
    else:
        return '2007_2016'


def compute_thesis_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds thesis-derived features (Juan Montes MIT 2017):
      - age: AGE_REFERENCE_YEAR - construction_year
      - age_sq: age squared (captures diminishing depreciation returns / vintage premium)
      - construction_year_bucket: categorical era (7 buckets)
      - city_zone: RM Santiago macrozone (centro_norte / este / sur / oeste / unknown)
      - log_surface: log(surface_m2 + 1)  — thesis coeff=0.928

    Requires columns: construction_year, county_name, surface_m2 (all may be null).
    """
    df = df.copy()

    # Age and age squared
    if 'construction_year' in df.columns:
        age = AGE_REFERENCE_YEAR - pd.to_numeric(df['construction_year'], errors='coerce')
        # Clip negative ages (data entry errors where construction_year > 2014)
        age = age.clip(lower=0)
        df['age'] = age
        df['age_sq'] = age ** 2
        df['construction_year_bucket'] = df['construction_year'].apply(construction_year_to_bucket)
        n_known = df['construction_year'].notna().sum()
        logger.info(f"age: {n_known:,}/{len(df):,} rows have construction_year")
    else:
        logger.warning("construction_year not in DataFrame — age features set to null")
        df['age'] = np.nan
        df['age_sq'] = np.nan
        df['construction_year_bucket'] = 'unknown'

    # City zone from county_name
    if 'county_name' in df.columns:
        df['city_zone'] = df['county_name'].map(CITY_ZONE_MAP).fillna('unknown')
        zone_counts = df['city_zone'].value_counts().to_dict()
        logger.info(f"city_zone distribution: {zone_counts}")
    else:
        logger.warning("county_name not in DataFrame — city_zone set to unknown")
        df['city_zone'] = 'unknown'

    # Log surface
    if 'surface_m2' in df.columns:
        df['log_surface'] = np.log1p(pd.to_numeric(df['surface_m2'], errors='coerce').clip(lower=0))
    else:
        logger.warning("surface_m2 not in DataFrame — log_surface set to null")
        df['log_surface'] = np.nan

    return df


def _build_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db   = os.getenv("POSTGRES_DB",   "re_cl")
    user = os.getenv("POSTGRES_USER", "re_cl_user")
    pwd  = os.getenv("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


def compute_gap_pct(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds gap_pct_raw and gap_pct (winsorized) columns.

    gap_pct_raw = (real_value_uf - calculated_value_uf) / calculated_value_uf
      - NaN where either value is null or calculated_value_uf == 0
      - Negative → property transacted below calculated value (potential undervaluation)

    gap_pct = gap_pct_raw clipped at [p1, p99] computed from the data itself.
    """
    df = df.copy()

    valid = (
        df["real_value_uf"].notna() &
        df["calculated_value_uf"].notna() &
        (df["calculated_value_uf"] != 0) &
        df.get("has_valid_price", pd.Series(True, index=df.index))
    )

    df["gap_pct_raw"] = np.nan
    df.loc[valid, "gap_pct_raw"] = (
        (df.loc[valid, "real_value_uf"] - df.loc[valid, "calculated_value_uf"])
        / df.loc[valid, "calculated_value_uf"]
    )

    # Winsorize dynamically from the data — never hardcode bounds
    raw_valid = df["gap_pct_raw"].dropna()
    if len(raw_valid) < 10:
        logger.warning("Too few valid rows for winsorization — skipping clip")
        df["gap_pct"] = df["gap_pct_raw"]
    else:
        p_low  = raw_valid.quantile(WINSOR_LOW)
        p_high = raw_valid.quantile(WINSOR_HIGH)
        df["gap_pct"] = df["gap_pct_raw"].clip(lower=p_low, upper=p_high)
        logger.info(f"gap_pct winsorized: [{p_low:.4f}, {p_high:.4f}]")

    return df


def compute_percentiles(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds price_percentile_{25,50,75} and price_vs_median columns.

    Percentiles are computed via pandas groupby over (project_type, county_name, year)
    and joined back to each row. Uses uf_m2_building as the primary price metric.
    Falls back to uf_m2_land for 'land' typology if building is null.
    """
    df = df.copy()

    # Effective UF/m² column: prefer building, fallback land for land typology
    df["_uf_m2_eff"] = np.where(
        (df["project_type"] == "land") & df["uf_m2_building"].isna(),
        df["uf_m2_land"],
        df["uf_m2_building"]
    )

    group_cols = ["project_type", "county_name", "year"]
    pct_funcs  = {"p25": 0.25, "p50": 0.50, "p75": 0.75}

    pct_df = (
        df.groupby(group_cols)["_uf_m2_eff"]
        .quantile(list(pct_funcs.values()))
        .unstack()
        .reset_index()
    )
    pct_df.columns = group_cols + ["price_percentile_25", "price_percentile_50", "price_percentile_75"]

    df = df.merge(pct_df, on=group_cols, how="left")

    # Ratio vs median
    safe_median = df["price_percentile_50"].replace(0, np.nan)
    df["price_vs_median"] = df["_uf_m2_eff"] / safe_median

    df = df.drop(columns=["_uf_m2_eff"])

    n_matched = df["price_percentile_50"].notna().sum()
    logger.info(f"Percentiles computed: {n_matched:,}/{len(df):,} rows matched a group")
    return df


def run(engine=None) -> pd.DataFrame:
    """
    Reads transactions_clean from DB, computes all price features, returns DataFrame.
    Called by build_features.py.
    """
    if engine is None:
        engine = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info("Loading transactions_clean for price features...")
    query = """
        SELECT id, project_type, county_name, year, quarter,
               real_value_uf, calculated_value_uf,
               uf_m2_building, uf_m2_land,
               surface_m2,
               construction_year,
               has_valid_price, is_outlier, data_confidence
        FROM transactions_clean
        WHERE is_outlier = FALSE
    """
    df = pd.read_sql(query, engine)
    logger.info(f"  {len(df):,} rows loaded (outliers excluded)")

    df = compute_gap_pct(df)
    df = compute_percentiles(df)
    df = compute_thesis_features(df)

    return df[["id", "gap_pct", "gap_pct_raw",
               "price_percentile_25", "price_percentile_50", "price_percentile_75",
               "price_vs_median",
               "age", "age_sq", "construction_year_bucket", "city_zone", "log_surface"]]
