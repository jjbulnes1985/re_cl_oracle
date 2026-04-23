"""
load_cbr_2018.py
----------------
Ingest additional CBR transaction data from ieut-inciti dataset (2017-2018).

Two source files:
  1. transacciones27062018_completo.csv  — 677k rows, 2008-2017, same schema as main CSV
                                           but ';' delimited and lon/lat as x/y columns
  2. 191118_Actualizacion_2018.csv       — 80k rows, 2017-2018, different schema
                                           FECHA in Excel serial, LON/LAT as integers (/1e6)

Strategy:
  - Only ingest rows with year >= 2015 to minimise overlap with existing cbr_v1 data
  - Dedup on (role, inscription_date, real_value): skip if already in transactions_raw
  - Tag with data_source='cbr_2018' or 'cbr_actualizacion_2018'

Usage:
    py src/ingestion/load_cbr_2018.py
    py src/ingestion/load_cbr_2018.py --dry-run
    py src/ingestion/load_cbr_2018.py --source completo     # only file 1
    py src/ingestion/load_cbr_2018.py --source actualizacion  # only file 2
    py src/ingestion/load_cbr_2018.py --min-year 2017        # only 2017+
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# ── Paths ─────────────────────────────────────────────────────────────────────

IEUT_DATA_DIR = Path(
    os.getenv(
        "IEUT_DATA_DIR",
        r"C:\Users\jjbul\Dropbox\Documentos\Master\Post_llegada\ieut - inciti\Data"
    )
)
CBR_2018_PATH = Path(
    os.getenv(
        "CBR_2018_PATH",
        str(IEUT_DATA_DIR / "CBR_SII" / "transacciones27062018_completo.csv")
    )
)
CBR_2018_UPDATE_PATH = Path(
    os.getenv(
        "CBR_2018_UPDATE_PATH",
        str(IEUT_DATA_DIR / "CBR_SII" / "Actualizacion_191118" / "191118_Actualizacion_2018.csv")
    )
)

CHUNK_SIZE = 50_000

# Chile bounding box (WGS84)
LAT_MIN, LAT_MAX = -56.0, -17.0
LON_MIN, LON_MAX = -76.0, -65.0


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


def _ensure_data_source_column(engine) -> None:
    """Apply migration 012 if not already applied."""
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE transactions_raw
            ADD COLUMN IF NOT EXISTS data_source VARCHAR(50) DEFAULT 'cbr_v1'
        """))


def _get_existing_keys(engine) -> set:
    """
    Load dedup keys from transactions_raw.
    Key = (id_role, year, real_value) — fast approximate dedup.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id_role, year, real_value
            FROM transactions_raw
            LIMIT 2000000
        """)).fetchall()
    keys = {(str(r[0]), str(r[1]), str(r[2])) for r in rows}
    logger.info(f"Loaded {len(keys):,} existing keys for dedup")
    return keys


# Columns that actually exist in transactions_raw (used to filter before to_sql)
DB_COLS = {
    "project_type_name", "id_role", "year_building", "inscription_date",
    "quarter", "year", "bimester", "county_name", "longitude", "latitude",
    "calculated_value", "real_value", "uf_value", "surface",
    "total_surface_building", "total_surface_land", "uf_m2_u", "uf_m2_t",
    "buyer_name", "seller_name", "address", "apartment", "village",
    "data_source",
}


# ── File 1: transacciones27062018_completo.csv ────────────────────────────────

# Mapping from source columns to transactions_raw columns
# Maps CSV column names → actual transactions_raw DB column names (all lowercase)
COMPLETO_COL_MAP = {
    "project_type_name":      "project_type_name",
    "address":                "address",
    "inscription_date":       "inscription_date",
    "buyer_name":             "buyer_name",
    "department":             "apartment",        # DB col is 'apartment'
    "real_value":             "real_value",
    "calculated_value":       "calculated_value",
    "quarter":                "quarter",
    "year":                   "year",
    "country_name":           "county_name",      # CSV typo: country → county
    "role":                   "id_role",
    "seller_name":            "seller_name",
    "surface":                "surface",
    "total_surface_building": "total_surface_building",
    "total_surface_terrain":  "total_surface_land",  # DB col is 'total_surface_land'
    "uf_m2_u":                "uf_m2_u",
    "uf_m2_t":                "uf_m2_t",
    "village":                "village",
    "x":                      "longitude",
    "y":                      "latitude",
}


def _clean_coord(val):
    """Parse coordinate values, handling potential string formatting issues."""
    try:
        f = float(str(val).replace(",", "."))
        return f
    except (ValueError, TypeError):
        return np.nan


def load_completo(engine, min_year: int = 2015, dry_run: bool = False,
                  existing_keys: set = None) -> int:
    if not CBR_2018_PATH.exists():
        logger.warning(f"File not found: {CBR_2018_PATH}")
        return 0

    logger.info(f"Loading {CBR_2018_PATH.name} (min_year={min_year})")
    total_written = 0

    # Detect which 'year' column index to use for the CBR year (col 13, first 'year')
    with open(CBR_2018_PATH, encoding="utf-8", errors="replace") as f:
        raw_header = f.readline().strip().split(";")

    # Find first occurrence of 'year' (col 13 = transaction year)
    year_positions = [i for i, h in enumerate(raw_header) if h.strip().strip('"').lower() == "year"]
    cbr_year_col = year_positions[0] if year_positions else None
    logger.debug(f"'year' found at positions {year_positions}; using col {cbr_year_col}")

    for chunk_num, chunk in enumerate(
        pd.read_csv(
            CBR_2018_PATH,
            sep=";",
            encoding="utf-8",
            on_bad_lines="skip",
            dtype=str,
            chunksize=CHUNK_SIZE,
            low_memory=False,
        )
    ):
        chunk.columns = [c.strip().strip('"').lower() for c in chunk.columns]

        # Filter by year — use first 'year' column
        if "year" in chunk.columns:
            # Handle duplicate 'year' columns (pandas adds .1 suffix)
            year_col = [c for c in chunk.columns if c == "year" or c.startswith("year")][0]
            chunk["_year_int"] = pd.to_numeric(chunk[year_col], errors="coerce")
            chunk = chunk[chunk["_year_int"] >= min_year]

        if chunk.empty:
            continue

        # Rename columns
        chunk = chunk.rename(columns={
            k: v for k, v in COMPLETO_COL_MAP.items() if k in chunk.columns
        })

        # Coordinates — after rename x→longitude, y→latitude; still strings, convert to float
        if "longitude" in chunk.columns:
            chunk["longitude"] = chunk["longitude"].apply(_clean_coord)
        if "latitude" in chunk.columns:
            chunk["latitude"] = chunk["latitude"].apply(_clean_coord)

        # Validate bbox
        if "latitude" in chunk.columns and "longitude" in chunk.columns:
            valid_coords = (
                pd.to_numeric(chunk["latitude"], errors="coerce").between(LAT_MIN, LAT_MAX) &
                pd.to_numeric(chunk["longitude"], errors="coerce").between(LON_MIN, LON_MAX)
            )
            chunk.loc[~valid_coords, ["latitude", "longitude"]] = np.nan

        # Dedup against existing rows
        if existing_keys is not None:
            is_new = ~chunk.apply(
                lambda r: (str(r.get("id_role", "")), str(r.get("year", "")), str(r.get("real_value", ""))) in existing_keys,
                axis=1
            )
            chunk = chunk[is_new]

        if chunk.empty:
            continue

        chunk["data_source"] = "cbr_2018"

        # Filter to only DB columns that exist in both chunk and transactions_raw
        keep_cols = [c for c in chunk.columns if c in DB_COLS]
        out = chunk[keep_cols].copy()

        # Coerce numeric columns so PostgreSQL accepts them (all read as str)
        NUMERIC_FLOAT = ["real_value", "calculated_value", "uf_value",
                         "uf_m2_u", "uf_m2_t", "surface",
                         "total_surface_building", "total_surface_land",
                         "latitude", "longitude"]
        NUMERIC_INT   = ["year", "year_building", "quarter", "bimester"]
        for col in NUMERIC_FLOAT:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        for col in NUMERIC_INT:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")

        # Parse inscription_date → proper date (DB column type: date)
        if "inscription_date" in out.columns:
            out["inscription_date"] = pd.to_datetime(
                out["inscription_date"], errors="coerce", dayfirst=True
            ).dt.date

        # Truncate VARCHAR columns to their DB limits
        VARCHAR_LIMITS = {
            "project_type_name": 100,
            "id_role":           50,
            "county_name":       100,
            "apartment":         100,
            "data_source":       50,
        }
        for col, limit in VARCHAR_LIMITS.items():
            if col in out.columns:
                out[col] = out[col].astype(str).str.slice(0, limit).where(
                    out[col].notna(), other=None
                )

        if dry_run:
            logger.info(f"[DRY RUN] Chunk {chunk_num}: {len(out):,} rows would be written (year≥{min_year})")
            total_written += len(out)
            continue

        try:
            out.to_sql(
                "transactions_raw", engine,
                if_exists="append", index=False,
                method="multi", chunksize=1000
            )
            total_written += len(out)
            logger.info(f"  Chunk {chunk_num}: wrote {len(out):,} rows (total={total_written:,})")
        except Exception as e:
            logger.error(f"  Chunk {chunk_num} failed: {e}")

    logger.info(f"completo: {total_written:,} rows written")
    return total_written


# ── File 2: 191118_Actualizacion_2018.csv ─────────────────────────────────────

def _excel_serial_to_date(serial_str: str) -> str | None:
    """Convert Excel date serial (days since 1899-12-30) to ISO date string."""
    try:
        serial = int(float(serial_str))
        dt = datetime(1899, 12, 30) + timedelta(days=serial)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError, OverflowError):
        return None


def _parse_coord_int(val_str: str) -> float | None:
    """
    Parse coordinates stored as integers like -70562014 → -70.562014
    The actual decimal was lost — reconstruct by dividing by 1e6.
    """
    try:
        raw = int(str(val_str).replace(".", "").replace(",", ""))
        # Sanity: expect lat ~-33, lon ~-70 for Santiago
        candidate = raw / 1_000_000
        if LAT_MIN <= candidate <= LAT_MAX or LON_MIN <= candidate <= LON_MAX:
            return candidate
        return np.nan
    except (ValueError, TypeError):
        return np.nan


ACTUALIZACION_COL_MAP = {
    "N°":       "Serial",
    "FECHA":    "Inscription_Date",
    "TOMO":     "Tome",
    "FOJA":     "Sheet",
    "COMPRADOR":             "buyer_name",
    "VENDEDOR":              "seller_name",
    "CALLE":                 "address",
    "COMUNA":                "county_name",
    "VILLA":                 "village",
    "DPTO":                  "apartment",
    "USO":                   "project_type_name",
    "SUPERFICIE":            "surface",
    "PESOS":                 "_real_value_clp",   # temp col, converted below
    "UF":                    "real_value",
    "ROL":                   "id_role",
    "LON":                   "longitude",
    "LAT":                   "latitude",
    "TOTAL_SUP_CONSTRUIDO":  "total_surface_building",
    "TOTAL_SUP_TERRENO":     "total_surface_land",
    "UF_M2_U":               "uf_m2_u",
    "UF_M2_T":               "uf_m2_t",
}

USOTYPE_MAP = {
    "C": "Casas",
    "D": "Departamentos",
    "O": "Oficinas",
    "L": "Locales",
    "B": "Bodegas",
    "G": "Garajes",
    "T": "Terrenos",
    "I": "Industriales",
}


def load_actualizacion(engine, min_year: int = 2017, dry_run: bool = False) -> int:
    if not CBR_2018_UPDATE_PATH.exists():
        logger.warning(f"File not found: {CBR_2018_UPDATE_PATH}")
        return 0

    logger.info(f"Loading {CBR_2018_UPDATE_PATH.name} (min_year={min_year})")
    total_written = 0

    for chunk_num, chunk in enumerate(
        pd.read_csv(
            CBR_2018_UPDATE_PATH,
            sep=";",
            encoding="utf-8",
            on_bad_lines="skip",
            dtype=str,
            chunksize=CHUNK_SIZE,
            low_memory=False,
        )
    ):
        chunk.columns = [c.strip() for c in chunk.columns]

        # Parse FECHA (Excel serial) → ISO date and extract year
        if "FECHA" in chunk.columns:
            chunk["inscription_date"] = chunk["FECHA"].apply(_excel_serial_to_date)
            chunk["year"] = pd.to_datetime(
                chunk["inscription_date"], errors="coerce"
            ).dt.year
            chunk = chunk[chunk["year"] >= min_year]

        if chunk.empty:
            continue

        # Rename columns to DB names
        chunk = chunk.rename(columns={
            k: v for k, v in ACTUALIZACION_COL_MAP.items() if k in chunk.columns
        })

        # Parse coordinates (stored as integers with implicit decimal)
        if "longitude" in chunk.columns:
            chunk["longitude"] = chunk["longitude"].apply(_parse_coord_int)
        if "latitude" in chunk.columns:
            chunk["latitude"] = chunk["latitude"].apply(_parse_coord_int)

        # Validate bbox
        if "latitude" in chunk.columns and "longitude" in chunk.columns:
            valid_coords = (
                chunk["latitude"].between(LAT_MIN, LAT_MAX) &
                chunk["longitude"].between(LON_MIN, LON_MAX)
            )
            chunk.loc[~valid_coords, ["latitude", "longitude"]] = np.nan

        # Map USO → project_type_name
        if "project_type_name" in chunk.columns:
            chunk["project_type_name"] = chunk["project_type_name"].map(USOTYPE_MAP).fillna("Otros")

        # real_value: use UF if available, else convert PESOS (temp col _real_value_clp)
        if "real_value" not in chunk.columns and "_real_value_clp" in chunk.columns:
            uf_val = float(os.getenv("UF_VALUE_APPROX", "37000"))
            chunk["real_value"] = pd.to_numeric(chunk["_real_value_clp"], errors="coerce") / uf_val

        # quarter from inscription_date
        chunk["quarter"] = pd.to_datetime(chunk.get("inscription_date"), errors="coerce").dt.quarter

        chunk["data_source"] = "cbr_actualizacion_2018"

        # Drop temp columns and keep only real DB columns
        keep_cols = [c for c in chunk.columns if c in DB_COLS]

        if dry_run:
            logger.info(f"[DRY RUN] Chunk {chunk_num}: {len(chunk):,} rows (year≥{min_year}) cols={keep_cols}")
            total_written += len(chunk)
            continue

        try:
            chunk[keep_cols].to_sql(
                "transactions_raw", engine,
                if_exists="append", index=False,
                method="multi", chunksize=1000
            )
            total_written += len(chunk)
            logger.info(f"  Chunk {chunk_num}: wrote {len(chunk):,} rows (total={total_written:,})")
        except Exception as e:
            logger.error(f"  Chunk {chunk_num} failed: {e}")

    logger.info(f"actualizacion: {total_written:,} rows written")
    return total_written


# ── Main ──────────────────────────────────────────────────────────────────────

def main(source: str = "all", min_year: int = 2015, dry_run: bool = False) -> None:
    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info("=" * 60)
    logger.info(f"CBR 2017-2018 INGESTION (source={source}, min_year={min_year})")
    logger.info("=" * 60)

    _ensure_data_source_column(engine)

    total = 0

    if source in ("all", "completo"):
        existing_keys = _get_existing_keys(engine)
        n = load_completo(engine, min_year=min_year, dry_run=dry_run, existing_keys=existing_keys)
        total += n

    if source in ("all", "actualizacion"):
        n = load_actualizacion(engine, min_year=max(min_year, 2017), dry_run=dry_run)
        total += n

    logger.info("=" * 60)
    logger.info(f"TOTAL INGESTED: {total:,} rows {'(dry run)' if dry_run else ''}")
    logger.info("=" * 60)

    if not dry_run and total > 0:
        logger.info("Next steps:")
        logger.info("  1. py src/ingestion/clean_transactions.py")
        logger.info("  2. py src/features/build_features.py")
        logger.info("  3. py src/models/hedonic_model.py  (retrain with more data)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",   action="store_true",
                        help="Preview without writing to DB")
    parser.add_argument("--source",    default="all",
                        choices=["all", "completo", "actualizacion"],
                        help="Which source file to load")
    parser.add_argument("--min-year",  type=int, default=2015,
                        help="Only load records from this year onwards (default: 2015)")
    args = parser.parse_args()
    main(source=args.source, min_year=args.min_year, dry_run=args.dry_run)
