"""
load_transactions.py
--------------------
ETL: Lee el CSV del CBR en chunks y lo inserta en transactions_raw.

Uso:
    python src/ingestion/load_transactions.py

Variables de entorno requeridas (ver .env.example):
    RAW_CSV_PATH, DATABASE_URL (o POSTGRES_* individuales), CSV_CHUNK_SIZE

Formato del CSV fuente (quirks):
    - Cada fila está envuelta en comillas dobles externas: "field1,field2,..."
    - Valores numéricos con separador de miles también entre comillas: "" 70,926,394 ""
    - Encoding: latin-1
    - Solución: two-pass parsing (csv.reader outer → csv.reader inner)
"""

import csv
import os
import sys
from pathlib import Path
from typing import Generator

import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from loguru import logger
from tqdm import tqdm

# ── Configuración ──────────────────────────────────────────────────────────────
load_dotenv()

RAW_CSV_PATH = os.getenv("RAW_CSV_PATH", "../data/raw/Transactions w.Const.date_v2.csv")
CHUNK_SIZE   = int(os.getenv("CSV_CHUNK_SIZE", "50000"))

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


# ── Mapeo de columnas CSV → DB ─────────────────────────────────────────────────
CSV_TO_DB = {
    "Project_Type_Name":       "project_type_name",
    "ID_Role":                 "id_role",
    "Year_Building":           "year_building",
    "Inscription_Date":        "inscription_date",
    "Quarter":                 "quarter",
    "Year":                    "year",
    "County_Name":             "county_name",
    "Longitude":               "longitude",
    "Latitude":                "latitude",
    "Calculated_Value":        "calculated_value",
    "Real_Value":              "real_value",
    "Surface":                 "surface",
    "total_surface_building":  "total_surface_building",
    "Total_Surface_Land":      "total_surface_land",
    "UF_m2_u":                 "uf_m2_u",
    "Uf_m2_t":                 "uf_m2_t",
    "bimester":                "bimester",
    "Buyer_Name":              "buyer_name",
    "Seller_Name":             "seller_name",
    "Address":                 "address",
    "Apartment":               "apartment",
    "Village":                 "village",
    "UF":                      "uf_value",
}

# Columnas numéricas donde los nulos se dejan como NULL (no 0)
NUMERIC_COLS = [
    "year_building", "quarter", "year", "bimester",
    "longitude", "latitude",
    "calculated_value", "real_value", "uf_value",
    "surface", "total_surface_building", "total_surface_land",
    "uf_m2_u", "uf_m2_t",
]

# Bounding box de Chile continental (validación de coordenadas)
CHILE_BBOX = {
    "lat_min": -56.0,
    "lat_max": -17.0,
    "lon_min": -76.0,
    "lon_max": -65.0,
}


# ── Two-pass CSV parser ────────────────────────────────────────────────────────

def _parse_outer_row(raw_row: list[str]) -> list[str]:
    """
    The CSV has each line wrapped in outer double-quotes.
    csv.reader (pass 1) yields [single_string] for these lines.
    This function runs a second csv.reader pass on that string
    to split the inner comma-separated fields.

    Example raw line:
        "Apartments,833-75,""1993"",3/20/2014,,"" 70,926,394 "",...\n"
    After pass 1 → raw_row = ['Apartments,833-75,"1993",3/20/2014,," 70,926,394 ",...']
    After pass 2 → ['Apartments', '833-75', '1993', '3/20/2014', '', ' 70,926,394 ', ...]
    """
    if len(raw_row) == 1:
        inner = raw_row[0]
        for parsed in csv.reader([inner]):
            return parsed
        return raw_row
    # Row was already split (no outer quotes) — return as-is
    return raw_row


def read_csv_chunks(
    csv_path: Path,
    chunk_size: int,
    encoding: str = "latin-1",
) -> Generator[pd.DataFrame, None, None]:
    """
    Generator: yields DataFrames of up to chunk_size rows.
    Handles the CBR CSV format where each data row is wrapped in outer double-quotes
    and numeric values with thousands commas are also quoted internally.
    """
    with open(csv_path, encoding=encoding, newline="") as fh:
        outer_reader = csv.reader(fh)

        # ── Header ─────────────────────────────────────────────────────────────
        raw_header = next(outer_reader)
        header = _parse_outer_row(raw_header)
        # Strip whitespace, tabs, and stray quotes from column names
        header = [col.strip().strip('"').strip("\t").strip() for col in header]
        n_cols = len(header)
        logger.debug(f"Columnas detectadas ({n_cols}): {header}")

        # ── Data rows ──────────────────────────────────────────────────────────
        rows: list[list[str]] = []
        skipped = 0

        for raw_row in outer_reader:
            row = _parse_outer_row(raw_row)

            # Skip rows with wrong number of columns
            if len(row) != n_cols:
                skipped += 1
                continue

            rows.append(row)

            if len(rows) >= chunk_size:
                yield pd.DataFrame(rows, columns=header)
                rows = []

        if rows:
            yield pd.DataFrame(rows, columns=header)

        if skipped:
            logger.warning(f"  {skipped} filas descartadas por número incorrecto de columnas")


# ── Processing ────────────────────────────────────────────────────────────────

def validate_coords(df: pd.DataFrame) -> pd.DataFrame:
    """Marca filas con coordenadas fuera del bounding box de Chile como NULL."""
    has_coords = df["longitude"].notna() & df["latitude"].notna()
    in_chile = (
        (df["latitude"]  >= CHILE_BBOX["lat_min"]) &
        (df["latitude"]  <= CHILE_BBOX["lat_max"]) &
        (df["longitude"] >= CHILE_BBOX["lon_min"]) &
        (df["longitude"] <= CHILE_BBOX["lon_max"])
    )
    invalid = has_coords & ~in_chile
    n_invalid = invalid.sum()
    if n_invalid > 0:
        logger.warning(f"  {n_invalid} filas con coordenadas fuera de Chile → se anulan")
        df.loc[invalid, ["longitude", "latitude"]] = None
    return df


def process_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    """Limpieza mínima para carga inicial (limpieza profunda en clean_transactions.py)."""
    # Renombrar columnas al esquema de DB (header ya normalizado en read_csv_chunks)
    chunk = chunk.rename(columns=CSV_TO_DB)

    # Convertir tipos numéricos:
    #   - strip whitespace/tabs (e.g. "1993\t")
    #   - remove thousands-separator commas (e.g. " 70,926,394 " → "70926394")
    #   - coerce to float, errors → NaN
    for col in NUMERIC_COLS:
        if col in chunk.columns:
            chunk[col] = (
                chunk[col]
                .astype(str)
                .str.strip()
                .str.replace(",", "", regex=False)
            )
            chunk[col] = pd.to_numeric(chunk[col], errors="coerce")

    # Parsear fecha
    if "inscription_date" in chunk.columns:
        chunk["inscription_date"] = pd.to_datetime(
            chunk["inscription_date"], errors="coerce"
        ).dt.date

    # Validar coordenadas
    chunk = validate_coords(chunk)

    # Strip en columnas de texto y truncar a límites VARCHAR del schema
    text_cols = ["project_type_name", "county_name", "buyer_name",
                 "seller_name", "address", "apartment", "village", "id_role"]
    varchar_limits = {
        "project_type_name": 100,
        "id_role": 50,
        "county_name": 100,
        "apartment": 100,
    }
    for col in text_cols:
        if col in chunk.columns:
            chunk[col] = chunk[col].astype(str).str.strip().replace("nan", None)
            if col in varchar_limits:
                limit = varchar_limits[col]
                chunk[col] = chunk[col].apply(
                    lambda v: v[:limit] if isinstance(v, str) else v
                )

    return chunk


def upsert_chunk(chunk: pd.DataFrame, engine) -> int:
    """Inserta el chunk en transactions_raw. Retorna filas insertadas."""
    db_cols = list(CSV_TO_DB.values())
    cols_present = [c for c in db_cols if c in chunk.columns]
    chunk = chunk[cols_present]

    chunk.to_sql(
        "transactions_raw",
        engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=1000,
    )
    return len(chunk)


def update_geometry(engine) -> None:
    """Genera la columna geom a partir de longitude/latitude después de la carga."""
    logger.info("Actualizando columna geom (PostGIS)...")
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE transactions_raw
            SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
            WHERE longitude IS NOT NULL
              AND latitude  IS NOT NULL
              AND geom IS NULL
        """))
    logger.info("  Columna geom actualizada.")


def print_load_summary(engine) -> None:
    """Muestra estadísticas de la carga."""
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM transactions_raw")).scalar()
        by_type = conn.execute(text(
            "SELECT project_type_name, COUNT(*) AS n "
            "FROM transactions_raw GROUP BY 1 ORDER BY 2 DESC"
        )).fetchall()
        counties = conn.execute(text(
            "SELECT COUNT(DISTINCT county_name) FROM transactions_raw"
        )).scalar()
        with_geom = conn.execute(text(
            "SELECT COUNT(*) FROM transactions_raw WHERE geom IS NOT NULL"
        )).scalar()

    logger.info("─" * 50)
    logger.info(f"RESUMEN DE CARGA")
    logger.info(f"  Total registros:      {total:,}")
    logger.info(f"  Comunas únicas:       {counties}")
    logger.info(f"  Con coordenadas:      {with_geom:,} ({with_geom/total*100:.1f}%)")
    logger.info(f"  Por tipología:")
    for row in by_type:
        logger.info(f"    {row[0]:<30} {row[1]:>8,}")
    logger.info("─" * 50)


def main() -> None:
    csv_path = Path(RAW_CSV_PATH)
    if not csv_path.exists():
        logger.error(f"CSV no encontrado: {csv_path.resolve()}")
        sys.exit(1)

    engine = create_engine(build_db_url(), pool_pre_ping=True)

    # Verificar conexión
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Conexión a PostgreSQL OK")
    except Exception as e:
        logger.error(f"No se pudo conectar a la base de datos: {e}")
        sys.exit(1)

    # Verificar si ya hay datos
    with engine.connect() as conn:
        existing = conn.execute(text("SELECT COUNT(*) FROM transactions_raw")).scalar()
    if existing > 0:
        logger.warning(f"La tabla transactions_raw ya tiene {existing:,} registros.")
        resp = input("¿Deseas truncar y recargar? (s/N): ").strip().lower()
        if resp == "s":
            with engine.begin() as conn:
                conn.execute(text("TRUNCATE TABLE transactions_raw RESTART IDENTITY CASCADE"))
            logger.info("Tabla truncada.")
        else:
            logger.info("Carga cancelada por el usuario.")
            return

    logger.info(f"Leyendo CSV: {csv_path}")
    logger.info(f"Chunk size: {CHUNK_SIZE:,} filas")

    total_inserted = 0
    chunk_n = 0

    with tqdm(desc="Cargando chunks", unit="chunk") as pbar:
        for chunk in read_csv_chunks(csv_path, CHUNK_SIZE):
            chunk_n += 1
            try:
                chunk = process_chunk(chunk)
                n = upsert_chunk(chunk, engine)
                total_inserted += n
                pbar.set_postfix({"filas": f"{total_inserted:,}"})
                pbar.update(1)
            except Exception as e:
                logger.error(f"Error en chunk {chunk_n}: {e}")
                raise

    logger.info(f"Carga completada: {total_inserted:,} filas en {chunk_n} chunks")

    # Actualizar geometría PostGIS
    update_geometry(engine)

    # Resumen final
    print_load_summary(engine)


if __name__ == "__main__":
    main()
