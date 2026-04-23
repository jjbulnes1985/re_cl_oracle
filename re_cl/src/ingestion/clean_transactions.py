"""
clean_transactions.py
---------------------
Lee transactions_raw, aplica limpieza profunda y escribe en transactions_clean.

Proceso:
    1. Detectar y corregir escala de Real_Value (pesos vs UF)
    2. Deduplicar por (id_role, inscription_date)
    3. Imputar Surface nulos (mediana por tipología+comuna)
    4. Detectar outliers de precio (IQR por tipología+año)
    5. Calcular data_confidence por registro
    6. Escribir en transactions_clean

NEEDS APPROVAL:  La normalización de Real_Value cambia la escala de todos los datos.
                 Revisar el reporte de distribución antes de confirmar.

Uso:
    python src/ingestion/clean_transactions.py [--dry-run]
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from loguru import logger

load_dotenv()


# ── Configuración ──────────────────────────────────────────────────────────────
def build_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db   = os.getenv("POSTGRES_DB", "re_cl")
    user = os.getenv("POSTGRES_USER", "re_cl_user")
    pwd  = os.getenv("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


# Valores de UF históricos de referencia (para detectar si Real_Value está en pesos)
# Rango aproximado de la UF en 2013-2014: 22,800 - 23,700 CLP
UF_2013_APPROX = 23_000.0
UF_MIN_PLAUSIBLE = 21_000.0
UF_MAX_PLAUSIBLE = 25_000.0

# Umbral: si Real_Value > este múltiplo del Calculated_Value, probablemente está en pesos
UF_SCALE_THRESHOLD = 500.0

# Límites de precio razonables por tipología (UF/m²) — Santiago RM, 2013-2014
# Fuente de referencia: CBR RM, índices CChC, valores CIADE/MINVU
# Mínimos calibrados: sub-10 UF/m² en inmuebles construidos es error de dato,
# no una oportunidad real. Aplica tanto a IQR como a filtro absoluto.
PRICE_LIMITS = {
    # Floors calibrados por auditoría multiagente 2026-04-20:
    # - Estos valores son para ENTRENAMIENTO (marcar is_outlier en transactions_clean).
    # - La vista v_opportunities aplica filtros adicionales más estrictos para el dashboard.
    # - Comunas periféricas (Cerro Navia, Lo Espejo, San Ramón) transaccionan
    #   casas legítimamente en el rango 5-9 UF/m² con alta confianza (≥0.93).
    # - Social housing SERVIU se clasifica como 'apartments' y puede llegar a 8-11 UF/m².
    "apartments":  (8.0,  250.0),  # Floor: SERVIU/periferia legítimo; view aplica ≥10
    "residential": (5.0,  200.0),  # Floor: periférico legítimo (p5=5.5); view aplica ≥10
    "retail":      (7.0,  350.0),  # Floor: kioscos/bodegas pequeñas legítimas
    "land":        (2.0,  120.0),  # Floor: terreno periférico; view aplica ≥2
    "default":     (5.0,  500.0),  # Fallback conservador
}

# Piso para has_valid_price — más permisivo que la vista para no excluir del entrenamiento
# datos legítimos de comunas periféricas. La vista aplica piso mayor (10 UF/m²) en display.
UF_M2_FLOOR_BUILT = 5.0   # UF/m² mínimo para apartments / residential / retail (entrenamiento)
UF_M2_FLOOR_LAND  = 1.5   # UF/m² mínimo para land (terreno puro)

TYPOLOGY_MAP = {
    "apartments": "apartments",
    "apartment":  "apartments",
    "residential": "residential",
    "house":       "residential",
    "retail":      "retail",
    "office y retail": "retail",
    "office and retail": "retail",
    "land":        "land",
    "terreno":     "land",
}


def normalize_typology(raw: str) -> str:
    if pd.isna(raw):
        return "unknown"
    return TYPOLOGY_MAP.get(str(raw).strip().lower(), "unknown")


def detect_real_value_scale(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detecta si Real_Value está en pesos (CLP) en lugar de UF y convierte.

    Heurística:
    - Si la mediana de (Real_Value / Calculated_Value) supera UF_SCALE_THRESHOLD,
      se asume que Real_Value está en pesos y se divide por uf_value.
    - NEEDS APPROVAL: esta operación modifica la columna real_value en el DataFrame.
    """
    valid = df[
        df["calculated_value"].notna() &
        df["real_value"].notna() &
        (df["calculated_value"] > 0) &
        (df["real_value"] > 0)
    ].copy()

    if valid.empty:
        logger.warning("No hay registros válidos para detectar escala de Real_Value.")
        return df

    ratio = valid["real_value"] / valid["calculated_value"]
    median_ratio = ratio.median()
    pct_high = (ratio > UF_SCALE_THRESHOLD).mean() * 100

    logger.info(f"Ratio mediano Real_Value / Calculated_Value: {median_ratio:.2f}")
    logger.info(f"% registros con ratio > {UF_SCALE_THRESHOLD}: {pct_high:.1f}%")

    if pct_high > 50:
        # La mayoría parece estar en pesos → convertir
        logger.warning(
            f"ALERTA: {pct_high:.0f}% de registros tiene ratio > {UF_SCALE_THRESHOLD}. "
            "Se asume que Real_Value está en CLP. Convirtiendo a UF dividiendo por uf_value."
        )
        has_uf = df["uf_value"].notna() & (df["uf_value"] > UF_MIN_PLAUSIBLE) & (df["uf_value"] < UF_MAX_PLAUSIBLE)
        df.loc[has_uf, "real_value"] = df.loc[has_uf, "real_value"] / df.loc[has_uf, "uf_value"]
        df.loc[~has_uf & df["real_value"].notna(), "real_value"] = df.loc[~has_uf & df["real_value"].notna(), "real_value"] / UF_2013_APPROX
        logger.info("Conversión CLP → UF completada.")
    else:
        logger.info("Real_Value parece estar en UF. No se realiza conversión.")

    return df


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Elimina duplicados por (id_role, inscription_date).
    Mantiene el registro con mayor data_completeness.
    """
    before = len(df)
    df["_completeness"] = df.notna().sum(axis=1)
    df = df.sort_values("_completeness", ascending=False)
    df = df.drop_duplicates(subset=["id_role", "inscription_date"], keep="first")
    df = df.drop(columns=["_completeness"])
    after = len(df)
    logger.info(f"Deduplicación: {before:,} → {after:,} ({before - after:,} duplicados eliminados)")
    return df


def impute_surface(df: pd.DataFrame) -> pd.DataFrame:
    """
    Imputa surface nulos con la mediana por (project_type_norm, county_name).
    Marca los registros imputados.
    """
    df["surface_imputed"] = False
    missing = df["surface"].isna()
    n_missing = missing.sum()

    if n_missing == 0:
        return df

    medians = (
        df[df["surface"].notna()]
        .groupby(["project_type_norm", "county_name"])["surface"]
        .median()
    )

    def fill_row(row):
        if pd.notna(row["surface"]):
            return row["surface"], False
        key = (row["project_type_norm"], row["county_name"])
        median = medians.get(key)
        if median is not None:
            return median, True
        # Fallback: mediana global por tipología
        type_median = df[df["project_type_norm"] == row["project_type_norm"]]["surface"].median()
        return type_median, True if pd.notna(type_median) else (None, False)

    results = df[missing].apply(fill_row, axis=1)
    df.loc[missing, "surface"] = [r[0] for r in results]
    df.loc[missing, "surface_imputed"] = [r[1] for r in results]

    n_imputed = df["surface_imputed"].sum()
    logger.info(f"Imputación surface: {n_imputed:,} / {n_missing:,} filas imputadas con mediana")
    return df


def detect_outliers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detecta outliers de precio (uf_m2_u) en dos capas:

    1. Piso/techo absoluto por tipología (PRICE_LIMITS) — errores de captura evidentes.
       Ej: dpto con 3 UF/m² = precio en pesos no convertido, superficie mal registrada, etc.
    2. IQR × 3 dentro de cada (tipología, año) — outliers estadísticos relativos al mercado.

    Registros marcados conservan is_outlier=True y son excluidos de v_opportunities y del modelo.
    """
    df["is_outlier"] = False
    df["outlier_reason"] = None

    # ── Capa 1: piso/techo absoluto (filtra errores de captura) ───────────────
    for ptype, grp in df.groupby("project_type_norm"):
        abs_lo, abs_hi = PRICE_LIMITS.get(ptype, PRICE_LIMITS["default"])

        # Piso adicional por tipo constructivo (más estricto para inmuebles con edificación)
        if ptype in ("apartments", "residential", "retail"):
            abs_lo = max(abs_lo, UF_M2_FLOOR_BUILT)
        elif ptype == "land":
            abs_lo = max(abs_lo, UF_M2_FLOOR_LAND)

        valid_price = grp["uf_m2_u"].notna()
        mask_high = valid_price & (grp["uf_m2_u"] > abs_hi)
        mask_low  = valid_price & (grp["uf_m2_u"] < abs_lo)

        df.loc[grp[mask_high].index, "is_outlier"] = True
        df.loc[grp[mask_high].index, "outlier_reason"] = f"uf_m2_u > {abs_hi} (límite absoluto {ptype})"
        df.loc[grp[mask_low].index,  "is_outlier"] = True
        df.loc[grp[mask_low].index,  "outlier_reason"] = f"uf_m2_u < {abs_lo} (límite absoluto {ptype})"

    # ── Capa 2: IQR × 3 sobre registros no-outlier, por (tipología, año) ─────
    clean_mask = ~df["is_outlier"]
    for (ptype, year), grp in df[clean_mask].groupby(["project_type_norm", "year"]):
        prices = grp["uf_m2_u"].dropna()
        if len(prices) < 10:
            continue
        q1, q3 = prices.quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr == 0:
            continue
        lo = max(q1 - 3 * iqr, PRICE_LIMITS.get(ptype, PRICE_LIMITS["default"])[0])
        hi = min(q3 + 3 * iqr, PRICE_LIMITS.get(ptype, PRICE_LIMITS["default"])[1])

        mask_high = grp["uf_m2_u"].notna() & (grp["uf_m2_u"] > hi)
        mask_low  = grp["uf_m2_u"].notna() & (grp["uf_m2_u"] < lo)

        df.loc[grp[mask_high].index, "is_outlier"] = True
        df.loc[grp[mask_high].index, "outlier_reason"] = f"uf_m2_u > {hi:.1f} (IQR×3, {ptype} {year})"
        df.loc[grp[mask_low].index,  "is_outlier"] = True
        df.loc[grp[mask_low].index,  "outlier_reason"] = f"uf_m2_u < {lo:.1f} (IQR×3, {ptype} {year})"

    n_out = df["is_outlier"].sum()
    logger.info(f"Outliers detectados: {n_out:,} ({n_out / len(df) * 100:.2f}%)")
    logger.info(f"  → Capa absoluta: sub-{UF_M2_FLOOR_BUILT} UF/m² en inmuebles construidos")
    logger.info(f"  → Capa IQR×3:   outliers estadísticos por tipología/año")
    return df


def compute_data_confidence(df: pd.DataFrame) -> pd.DataFrame:
    """
    Score de confianza por registro (0.0 a 1.0).
    Penaliza: campos nulos, surface imputada, outlier, coordenadas inválidas.
    """
    score = pd.Series(1.0, index=df.index)

    # Penalizaciones
    score -= df["surface_imputed"].astype(float) * 0.10
    score -= df["is_outlier"].astype(float) * 0.30
    score -= df["longitude"].isna().astype(float) * 0.20
    score -= df["real_value"].isna().astype(float) * 0.25
    score -= df["calculated_value"].isna().astype(float) * 0.15
    score -= (df["year_building"].isna()).astype(float) * 0.05

    df["data_confidence"] = score.clip(0.0, 1.0).round(3)
    logger.info(f"data_confidence — media: {df['data_confidence'].mean():.3f}, "
                f"mediana: {df['data_confidence'].median():.3f}")
    return df


def write_clean(df: pd.DataFrame, engine, dry_run: bool = False) -> None:
    """Escribe el DataFrame limpio en transactions_clean."""
    # Seleccionar y renombrar columnas al schema de transactions_clean
    # longitude/latitude are NOT columns in transactions_clean (geom is built via UPDATE)
    col_map = {
        "id":                    "raw_id",
        "project_type_norm":     "project_type",
        "id_role":               "id_role",
        "inscription_date":      "inscription_date",
        "year":                  "year",
        "quarter":               "quarter",
        "county_name":           "county_name",
        "year_building":         "construction_year",
        "longitude":             "longitude",
        "latitude":              "latitude",
        "calculated_value":      "calculated_value_uf",
        "real_value":            "real_value_uf",
        "uf_value":              "uf_value",
        "surface":               "surface_m2",
        "total_surface_building": "surface_building_m2",
        "total_surface_land":    "surface_land_m2",
        "surface_imputed":       "surface_imputed",
        "uf_m2_u":               "uf_m2_building",
        "uf_m2_t":               "uf_m2_land",
        "is_outlier":            "is_outlier",
        "outlier_reason":        "outlier_reason",
        "data_confidence":       "data_confidence",
    }

    existing = [c for c in col_map if c in df.columns]
    out = df[existing].rename(columns={k: col_map[k] for k in existing})
    out["has_valid_coords"] = df["longitude"].notna() & df["latitude"].notna()
    # has_valid_price: precio positivo + UF/m² por encima del piso absoluto por tipo.
    # Sub-piso = error de captura (precio en pesos no convertido, superficie errónea, etc.)
    ptype_col = df["project_type_norm"] if "project_type_norm" in df.columns else pd.Series("default", index=df.index)
    floor_series = ptype_col.map(lambda p: UF_M2_FLOOR_BUILT if p in ("apartments", "residential", "retail") else (UF_M2_FLOOR_LAND if p == "land" else 8.0))
    uf_ok = df["uf_m2_u"].notna() & (df["uf_m2_u"] >= floor_series)
    out["has_valid_price"]  = df["real_value"].notna() & (df["real_value"] > 0) & uf_ok
    out["has_surface"]      = df["surface"].notna()

    # Truncar strings to schema VARCHAR limits
    varchar_limits = {"project_type": 50, "id_role": 50, "county_name": 100}
    for col, limit in varchar_limits.items():
        if col in out.columns:
            out[col] = out[col].apply(lambda v: v[:limit] if isinstance(v, str) else v)

    if dry_run:
        logger.info(f"[DRY RUN] Se escribirían {len(out):,} filas en transactions_clean")
        logger.info(out.describe())
        return

    # Truncar y recargar
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE transactions_clean RESTART IDENTITY CASCADE"))

    out.to_sql("transactions_clean", engine, if_exists="append", index=False,
               method="multi", chunksize=5000)

    # Actualizar geom vía JOIN con transactions_raw (que sí tiene longitude/latitude)
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE transactions_clean tc
            SET geom = ST_SetSRID(ST_MakePoint(tr.longitude, tr.latitude), 4326)
            FROM transactions_raw tr
            WHERE tc.raw_id = tr.id
              AND tr.longitude IS NOT NULL
              AND tr.latitude  IS NOT NULL
        """))

    logger.info(f"transactions_clean cargada: {len(out):,} filas")


def print_quality_report(df: pd.DataFrame) -> None:
    """Reporte de calidad de datos."""
    logger.info("=" * 60)
    logger.info("REPORTE DE CALIDAD DE DATOS")
    logger.info("=" * 60)
    logger.info(f"Total registros:          {len(df):,}")
    logger.info(f"Outliers:                 {df['is_outlier'].sum():,} ({df['is_outlier'].mean()*100:.1f}%)")
    logger.info(f"Surface imputada:         {df['surface_imputed'].sum():,} ({df['surface_imputed'].mean()*100:.1f}%)")
    logger.info(f"Sin coordenadas:          {df['longitude'].isna().sum():,}")
    logger.info(f"Sin real_value:           {df['real_value'].isna().sum():,}")
    logger.info(f"Confianza media:          {df['data_confidence'].mean():.3f}")
    logger.info("")
    logger.info("% nulos por columna clave:")
    for col in ["real_value", "calculated_value", "surface", "uf_m2_u", "year_building"]:
        if col in df.columns:
            pct = df[col].isna().mean() * 100
            logger.info(f"  {col:<30} {pct:5.1f}%")
    logger.info("=" * 60)


def main(dry_run: bool = False) -> None:
    engine = create_engine(build_db_url(), pool_pre_ping=True)

    logger.info("Leyendo transactions_raw desde PostgreSQL...")
    df = pd.read_sql("SELECT * FROM transactions_raw", engine)
    logger.info(f"  {len(df):,} registros leídos")

    if df.empty:
        logger.error("transactions_raw está vacía. Ejecuta load_transactions.py primero.")
        sys.exit(1)

    # Pipeline de limpieza
    df["project_type_norm"] = df["project_type_name"].apply(normalize_typology)
    df = detect_real_value_scale(df)
    df = deduplicate(df)
    df = impute_surface(df)
    df = detect_outliers(df)
    df = compute_data_confidence(df)

    print_quality_report(df)
    write_clean(df, engine, dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Solo reporta sin escribir en DB")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
