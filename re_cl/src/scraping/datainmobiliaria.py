"""
datainmobiliaria.py
-------------------
Scraper for datainmobiliaria.cl — official CBR ventas efectivas (2008-present).

Endpoint discovered: POST /reports/busqueda_poligono_data
  Body:    { polygon: [{lat, lng}, ...], fuente: 'ventas', page: N }
  Returns: { resultados: [...], page: N, has_more: bool }
  Limit:   ~150 records/page, paginated via has_more flag

Rate limits (observed):
  - Guest: ~100 pages total per IP per day (~15k records). 402 = quota exhausted.
  - Free account: unlimited queries (register at datainmobiliaria.cl/users/sign_in)
  - Per-query cap: 100 pages per commune polygon (402 at page 101)

Guest strategy (no credentials):
  Run 1 commune per day via --commune flag + Prefect daily schedule.
  Checkpoint file tracks completed communes for resume.

Authenticated strategy (recommended):
  Set DATA_INMOBILIARIA_EMAIL + DATA_INMOBILIARIA_PASSWORD in .env
  and run all 40 communes in one session (~90 min).

Usage:
  py src/scraping/datainmobiliaria.py --dry-run
  py src/scraping/datainmobiliaria.py --commune "Las Condes" --min-year 2019
  py src/scraping/datainmobiliaria.py --min-year 2019           # all 40 RM communes
  py src/scraping/datainmobiliaria.py --next-commune            # resume: pick next unscraped commune
  py src/scraping/datainmobiliaria.py --fuente catastro         # cadastral data
  py src/scraping/datainmobiliaria.py --check-quota             # test if API is accessible
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Checkpoint file: tracks which communes have been successfully scraped
CHECKPOINT_FILE = Path(__file__).resolve().parents[2] / "data" / "processed" / "datainmobiliaria_checkpoint.json"


def _load_checkpoint() -> dict:
    """Load checkpoint data. Returns {commune: {"rows": N, "ts": "..."}}."""
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_checkpoint(commune: str, rows_written: int) -> None:
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = _load_checkpoint()
    data[commune] = {"rows": rows_written, "ts": pd.Timestamp.now().isoformat()}
    CHECKPOINT_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _next_unscraped_commune() -> Optional[str]:
    """Return the first commune not yet in checkpoint."""
    done = set(_load_checkpoint().keys())
    for name in RM_COMMUNE_POLYGONS:
        if name not in done:
            return name
    return None

BASE_URL   = "https://datainmobiliaria.cl"
SEARCH_EP  = f"{BASE_URL}/reports/busqueda_poligono_data"
LOGIN_URL  = f"{BASE_URL}/users/sign_in"
SEARCH_PAGE = f"{BASE_URL}/reports/busqueda_poligono"

# ── Commune polygons (RM bounding boxes) ──────────────────────────────────────
# Format: [{lat, lng}, ...] — at least 3 points
# Rough bounding boxes per commune; enough precision for the API polygon search.
RM_COMMUNE_POLYGONS = {
    "Santiago":           [{"lat":-33.47,"lng":-70.68},{"lat":-33.47,"lng":-70.63},{"lat":-33.42,"lng":-70.63},{"lat":-33.42,"lng":-70.68}],
    "Providencia":        [{"lat":-33.44,"lng":-70.63},{"lat":-33.44,"lng":-70.58},{"lat":-33.41,"lng":-70.58},{"lat":-33.41,"lng":-70.63}],
    "Las Condes":         [{"lat":-33.45,"lng":-70.62},{"lat":-33.45,"lng":-70.52},{"lat":-33.37,"lng":-70.52},{"lat":-33.37,"lng":-70.62}],
    "Ñuñoa":              [{"lat":-33.47,"lng":-70.62},{"lat":-33.47,"lng":-70.57},{"lat":-33.44,"lng":-70.57},{"lat":-33.44,"lng":-70.62}],
    "La Florida":         [{"lat":-33.55,"lng":-70.62},{"lat":-33.55,"lng":-70.55},{"lat":-33.48,"lng":-70.55},{"lat":-33.48,"lng":-70.62}],
    "Maipú":              [{"lat":-33.54,"lng":-70.80},{"lat":-33.54,"lng":-70.73},{"lat":-33.49,"lng":-70.73},{"lat":-33.49,"lng":-70.80}],
    "Pudahuel":           [{"lat":-33.46,"lng":-70.81},{"lat":-33.46,"lng":-70.74},{"lat":-33.41,"lng":-70.74},{"lat":-33.41,"lng":-70.81}],
    "La Pintana":         [{"lat":-33.60,"lng":-70.66},{"lat":-33.60,"lng":-70.61},{"lat":-33.56,"lng":-70.61},{"lat":-33.56,"lng":-70.66}],
    "Puente Alto":        [{"lat":-33.63,"lng":-70.59},{"lat":-33.63,"lng":-70.55},{"lat":-33.58,"lng":-70.55},{"lat":-33.58,"lng":-70.59}],
    "San Bernardo":       [{"lat":-33.62,"lng":-70.73},{"lat":-33.62,"lng":-70.68},{"lat":-33.57,"lng":-70.68},{"lat":-33.57,"lng":-70.73}],
    "Quilicura":          [{"lat":-33.38,"lng":-70.76},{"lat":-33.38,"lng":-70.71},{"lat":-33.34,"lng":-70.71},{"lat":-33.34,"lng":-70.76}],
    "Recoleta":           [{"lat":-33.40,"lng":-70.66},{"lat":-33.40,"lng":-70.63},{"lat":-33.37,"lng":-70.63},{"lat":-33.37,"lng":-70.66}],
    "Independencia":      [{"lat":-33.42,"lng":-70.67},{"lat":-33.42,"lng":-70.64},{"lat":-33.40,"lng":-70.64},{"lat":-33.40,"lng":-70.67}],
    "Estación Central":   [{"lat":-33.47,"lng":-70.71},{"lat":-33.47,"lng":-70.68},{"lat":-33.45,"lng":-70.68},{"lat":-33.45,"lng":-70.71}],
    "Lo Barnechea":       [{"lat":-33.37,"lng":-70.58},{"lat":-33.37,"lng":-70.50},{"lat":-33.31,"lng":-70.50},{"lat":-33.31,"lng":-70.58}],
    "Peñalolén":          [{"lat":-33.52,"lng":-70.57},{"lat":-33.52,"lng":-70.51},{"lat":-33.47,"lng":-70.51},{"lat":-33.47,"lng":-70.57}],
    "Macul":              [{"lat":-33.51,"lng":-70.61},{"lat":-33.51,"lng":-70.57},{"lat":-33.48,"lng":-70.57},{"lat":-33.48,"lng":-70.61}],
    "La Granja":          [{"lat":-33.56,"lng":-70.64},{"lat":-33.56,"lng":-70.60},{"lat":-33.53,"lng":-70.60},{"lat":-33.53,"lng":-70.64}],
    "San Ramón":          [{"lat":-33.55,"lng":-70.67},{"lat":-33.55,"lng":-70.64},{"lat":-33.53,"lng":-70.64},{"lat":-33.53,"lng":-70.67}],
    "El Bosque":          [{"lat":-33.58,"lng":-70.69},{"lat":-33.58,"lng":-70.65},{"lat":-33.55,"lng":-70.65},{"lat":-33.55,"lng":-70.69}],
    "Lo Espejo":          [{"lat":-33.54,"lng":-70.71},{"lat":-33.54,"lng":-70.68},{"lat":-33.52,"lng":-70.68},{"lat":-33.52,"lng":-70.71}],
    "Pedro Aguirre Cerda":[{"lat":-33.52,"lng":-70.68},{"lat":-33.52,"lng":-70.65},{"lat":-33.50,"lng":-70.65},{"lat":-33.50,"lng":-70.68}],
    "Lo Prado":           [{"lat":-33.46,"lng":-70.75},{"lat":-33.46,"lng":-70.72},{"lat":-33.44,"lng":-70.72},{"lat":-33.44,"lng":-70.75}],
    "Cerro Navia":        [{"lat":-33.44,"lng":-70.76},{"lat":-33.44,"lng":-70.72},{"lat":-33.42,"lng":-70.72},{"lat":-33.42,"lng":-70.76}],
    "Renca":              [{"lat":-33.41,"lng":-70.74},{"lat":-33.41,"lng":-70.70},{"lat":-33.38,"lng":-70.70},{"lat":-33.38,"lng":-70.74}],
    "Quinta Normal":      [{"lat":-33.44,"lng":-70.72},{"lat":-33.44,"lng":-70.68},{"lat":-33.42,"lng":-70.68},{"lat":-33.42,"lng":-70.72}],
    "Conchalí":           [{"lat":-33.40,"lng":-70.70},{"lat":-33.40,"lng":-70.66},{"lat":-33.37,"lng":-70.66},{"lat":-33.37,"lng":-70.70}],
    "Huechuraba":         [{"lat":-33.38,"lng":-70.66},{"lat":-33.38,"lng":-70.62},{"lat":-33.35,"lng":-70.62},{"lat":-33.35,"lng":-70.66}],
    "Vitacura":           [{"lat":-33.40,"lng":-70.59},{"lat":-33.40,"lng":-70.55},{"lat":-33.37,"lng":-70.55},{"lat":-33.37,"lng":-70.59}],
    "La Reina":           [{"lat":-33.47,"lng":-70.57},{"lat":-33.47,"lng":-70.53},{"lat":-33.44,"lng":-70.53},{"lat":-33.44,"lng":-70.57}],
    "San Joaquín":        [{"lat":-33.50,"lng":-70.65},{"lat":-33.50,"lng":-70.62},{"lat":-33.48,"lng":-70.62},{"lat":-33.48,"lng":-70.65}],
    "La Cisterna":        [{"lat":-33.53,"lng":-70.67},{"lat":-33.53,"lng":-70.64},{"lat":-33.51,"lng":-70.64},{"lat":-33.51,"lng":-70.67}],
    "San Miguel":         [{"lat":-33.50,"lng":-70.66},{"lat":-33.50,"lng":-70.63},{"lat":-33.48,"lng":-70.63},{"lat":-33.48,"lng":-70.66}],
    "Cerrillos":          [{"lat":-33.51,"lng":-70.76},{"lat":-33.51,"lng":-70.72},{"lat":-33.48,"lng":-70.72},{"lat":-33.48,"lng":-70.76}],
    "Colina":             [{"lat":-33.22,"lng":-70.70},{"lat":-33.22,"lng":-70.65},{"lat":-33.17,"lng":-70.65},{"lat":-33.17,"lng":-70.70}],
    "Lampa":              [{"lat":-33.32,"lng":-70.92},{"lat":-33.32,"lng":-70.87},{"lat":-33.27,"lng":-70.87},{"lat":-33.27,"lng":-70.92}],
    "Talagante":          [{"lat":-33.67,"lng":-70.95},{"lat":-33.67,"lng":-70.90},{"lat":-33.63,"lng":-70.90},{"lat":-33.63,"lng":-70.95}],
    "Buin":               [{"lat":-33.74,"lng":-70.75},{"lat":-33.74,"lng":-70.70},{"lat":-33.70,"lng":-70.70},{"lat":-33.70,"lng":-70.75}],
    "Melipilla":          [{"lat":-33.70,"lng":-71.23},{"lat":-33.70,"lng":-71.18},{"lat":-33.66,"lng":-71.18},{"lat":-33.66,"lng":-71.23}],
    "Pirque":             [{"lat":-33.68,"lng":-70.59},{"lat":-33.68,"lng":-70.54},{"lat":-33.63,"lng":-70.54},{"lat":-33.63,"lng":-70.59}],
}

# cod_destino → project_type mapping
DESTINO_MAP = {
    "D": "apartments",   # Departamento
    "Z": "apartments",   # Departamento (zone code)
    "C": "residential",  # Casa
    "H": "residential",  # Habitacional
    "O": "retail",       # Oficina
    "L": "retail",       # Local Comercial
    "B": "retail",       # Bodega
    "T": "unknown",      # Terreno
    "E": "retail",       # Estacionamiento
    "I": "retail",       # Industrial
}


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


def _safe_float(val) -> Optional[float]:
    try:
        return float(str(val).replace(",", ".").strip()) if val not in (None, "", "None") else None
    except Exception:
        return None


def _safe_int(val) -> Optional[int]:
    try:
        return int(str(val).strip()) if val not in (None, "", "None") else None
    except Exception:
        return None


def _parse_record(rec: dict, commune: str) -> Optional[dict]:
    """Transform a raw API record into transactions_raw schema."""
    try:
        price_raw   = _safe_float(rec.get("price"))
        unit        = str(rec.get("unit") or "UF").upper()
        uf_m2_raw   = _safe_float(rec.get("uf_m2"))
        date_raw    = str(rec.get("date_inscripcion") or "")
        ano_const   = _safe_int(rec.get("ano_construccion"))
        sup_const   = _safe_float(rec.get("superficie_construccion"))
        sup_terreno = _safe_float(rec.get("superficie_total_terreno"))
        lat         = _safe_float(rec.get("lat"))
        lng         = _safe_float(rec.get("lng"))
        cod_dest    = str(rec.get("cod_destino") or "")
        rol         = str(rec.get("rol") or "")
        direccion   = str(rec.get("direccion_sii") or "").strip()
        avaluo      = _safe_float(rec.get("avaluo_fiscal_clp"))

        # Convert price to UF
        uf_approx = float(os.getenv("UF_VALUE_APPROX", "37000"))
        if unit == "CLP" and price_raw:
            price_uf = price_raw / uf_approx
        else:
            price_uf = price_raw

        # Compute uf_m2 if not given
        surface = sup_const or sup_terreno
        if not uf_m2_raw and price_uf and surface and surface > 0:
            uf_m2_raw = round(price_uf / surface, 4)

        # Parse date → year, quarter
        year = quarter = None
        if date_raw and date_raw != "None":
            m = re.search(r"(\d{4})-(\d{2})-\d{2}", date_raw)
            if m:
                year = int(m.group(1))
                month = int(m.group(2))
                quarter = (month - 1) // 3 + 1

        project_type = DESTINO_MAP.get(cod_dest.upper(), "unknown")

        return {
            "project_type_name":       project_type,
            "county_name":             commune[:100],
            "real_value":              (price_raw * uf_approx) if unit == "UF" and price_raw else (price_raw if unit == "CLP" else None),
            "uf_value":                price_uf,
            "uf_m2_u":                 uf_m2_raw,
            "surface":                 sup_const,
            "total_surface_building":  sup_const,
            "total_surface_land":      sup_terreno,
            "latitude":                lat,
            "longitude":               lng,
            "year":                    year,
            "year_building":           ano_const,
            "quarter":                 quarter,
            "id_role":                 rol[:50] if rol else None,
            "apartment":               direccion[:100] if direccion else None,
            "inscription_date":        pd.to_datetime(date_raw, errors="coerce").date() if date_raw else None,
            "data_source":             "data_inmobiliaria",
            "calculated_value":        avaluo,
        }
    except Exception as e:
        logger.debug(f"  Parse error: {e}")
        return None


async def _fetch_commune(
    page,
    commune: str,
    polygon: list,
    fuente: str = "ventas",
    max_pages: int = 999,
    min_year: Optional[int] = None,
) -> list[dict]:
    """Paginate through all records for a commune polygon."""
    records = []
    p_num = 1

    while p_num <= max_pages:
        body = {"polygon": polygon, "fuente": fuente, "page": p_num}
        result = await page.evaluate(f'''async () => {{
            const r = await fetch('/reports/busqueda_poligono_data', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'X-CSRF-Token': document.querySelector('meta[name=csrf-token]')?.content || ''
                }},
                body: JSON.stringify({json.dumps(body)})
            }});
            if (!r.ok) return {{error: r.status}};
            return await r.json();
        }}''')

        if "error" in result:
            logger.warning(f"  API error page {p_num}: {result['error']}")
            break

        batch = result.get("resultados", [])
        if not batch:
            break

        # Filter by min_year if specified
        if min_year:
            def _year(rec):
                d = str(rec.get("date_inscripcion") or "")
                m = re.search(r"(\d{4})", d)
                return int(m.group(1)) if m else 0
            batch = [r for r in batch if _year(r) >= min_year]

        records.extend(batch)
        has_more = result.get("has_more", False)
        logger.debug(f"  Page {p_num}: {len(batch)} records, has_more={has_more}")

        if not has_more:
            break

        p_num += 1
        await asyncio.sleep(0.5)

    return records


COOKIE_FILE = Path(__file__).resolve().parents[2] / "data" / "processed" / "datainmobiliaria_cookies.json"


def _save_cookies(cookies: list) -> None:
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text(json.dumps(cookies, indent=2, ensure_ascii=False))
    logger.info(f"Session cookies saved → {COOKIE_FILE}")


def _load_cookies() -> list:
    if COOKIE_FILE.exists():
        try:
            return json.loads(COOKIE_FILE.read_text())
        except Exception:
            pass
    return []


async def scrape_all(
    engine,
    communes: list[str] = None,
    fuente: str = "ventas",
    dry_run: bool = False,
    max_pages: int = 100,
    min_year: Optional[int] = None,
    headless: bool = True,
    use_checkpoint: bool = True,
    check_quota_only: bool = False,
    manual_login: bool = False,
) -> int:
    """Returns number of rows written. Raises RuntimeError on quota exhaustion."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ImportError("playwright required: pip install playwright && playwright install chromium")

    if communes is None:
        communes = list(RM_COMMUNE_POLYGONS.keys())

    # Skip already-scraped communes when using checkpoint
    if use_checkpoint and not dry_run and not check_quota_only:
        checkpoint = _load_checkpoint()
        communes_todo = [c for c in communes if c not in checkpoint]
        skipped = len(communes) - len(communes_todo)
        if skipped:
            logger.info(f"Checkpoint: skipping {skipped} already-scraped communes")
        communes = communes_todo

    if not communes and not check_quota_only:
        logger.info("All communes already scraped per checkpoint. Done.")
        return 0

    # Check credentials for optional login
    email    = os.getenv("DATA_INMOBILIARIA_EMAIL")
    password = os.getenv("DATA_INMOBILIARIA_PASSWORD")

    # manual_login forces headed mode
    if manual_login:
        headless = False

    t_start = time.time()
    total_written = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )

        # Restore saved cookies if available (from a prior --manual-login session)
        saved_cookies = _load_cookies()
        if saved_cookies and not manual_login:
            await context.add_cookies(saved_cookies)
            logger.info(f"Restored {len(saved_cookies)} cookies from {COOKIE_FILE.name}")

        page = await context.new_page()

        # --manual-login: open browser, let user do Google OAuth, then press Enter
        if manual_login:
            logger.info("Opening browser for manual login...")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")
            print("\n" + "="*60)
            print("  Browser abierto en datainmobiliaria.cl")
            print("  1. Haz login con Google en el browser")
            print("  2. Espera a que cargue la página principal")
            print("  3. Vuelve aquí y presiona ENTER para continuar")
            print("="*60)
            await asyncio.get_event_loop().run_in_executor(None, input, "  → Presiona ENTER cuando estés logueado: ")
            await page.wait_for_timeout(2000)
            logger.info(f"  Guardando cookies desde: {page.url}")
            cookies = await context.cookies()
            _save_cookies(cookies)

        # Optional email/password login (for non-Google accounts)
        elif email and password and not saved_cookies:
            logger.info(f"Logging in as {email}...")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            try:
                await page.fill('input[type="email"], #user_email', email)
                await page.fill('input[type="password"], #user_password', password)
                await page.click('input[type="submit"], button[type="submit"]')
                await page.wait_for_timeout(3000)
                if "sign_in" not in page.url:
                    logger.info("  Login successful")
                    cookies = await context.cookies()
                    _save_cookies(cookies)
                else:
                    logger.warning("  Login may have failed — continuing as guest")
            except Exception as e:
                logger.warning(f"  Login error: {e} — continuing as guest")

        # Load the search page to get CSRF token + session state
        await page.goto(SEARCH_PAGE, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        csrf = await page.evaluate('() => document.querySelector("meta[name=csrf-token]")?.content || ""')
        logger.info(f"CSRF token acquired: {'yes' if csrf else 'no'}")

        # --check-quota: probe one small request to see if API is accessible
        if check_quota_only:
            test_polygon = list(RM_COMMUNE_POLYGONS.values())[0]
            body = {"polygon": test_polygon, "fuente": fuente, "page": 1}
            result = await page.evaluate(f'''async () => {{
                const r = await fetch('/reports/busqueda_poligono_data', {{
                    method: 'POST',
                    headers: {{'Content-Type':'application/json','Accept':'application/json','X-CSRF-Token': document.querySelector('meta[name=csrf-token]')?.content||''}},
                    body: JSON.stringify({json.dumps(body)})
                }});
                return {{status: r.status}};
            }}''')
            status = result.get("status", 0)
            if status == 200:
                logger.info("Quota check: API accessible (200). Ready to scrape.")
            elif status == 402:
                logger.warning("Quota check: 402 — guest quota exhausted. Wait until midnight or add credentials to .env")
            else:
                logger.warning(f"Quota check: unexpected status {status}")
            await browser.close()
            return 0

        logger.info(f"Communes: {len(communes)} | fuente={fuente} | min_year={min_year} | max_pages={max_pages}")
        logger.info("=" * 60)

        quota_exhausted = False

        for commune in communes:
            polygon = RM_COMMUNE_POLYGONS.get(commune)
            if not polygon:
                logger.warning(f"No polygon defined for {commune}, skipping")
                continue

            logger.info(f"Scraping: {commune}")
            raw_records = await _fetch_commune(
                page, commune, polygon, fuente=fuente,
                max_pages=max_pages, min_year=min_year,
            )

            # Detect quota exhaustion: 0 records AND error on page 1 means 402
            if not raw_records:
                # Do a quick probe to confirm quota vs genuinely empty commune
                probe_body = {"polygon": polygon, "fuente": fuente, "page": 1}
                probe = await page.evaluate(f'''async () => {{
                    const r = await fetch('/reports/busqueda_poligono_data', {{
                        method: 'POST',
                        headers: {{'Content-Type':'application/json','Accept':'application/json','X-CSRF-Token': document.querySelector('meta[name=csrf-token]')?.content||''}},
                        body: JSON.stringify({json.dumps(probe_body)})
                    }});
                    return {{status: r.status}};
                }}''')
                if probe.get("status") == 402:
                    logger.error(f"  Quota exhausted (402). Stopping. Run again after midnight or add credentials.")
                    quota_exhausted = True
                    break
                else:
                    logger.info(f"  No records found for {commune} (status={probe.get('status')})")
                    if use_checkpoint and not dry_run:
                        _save_checkpoint(commune, 0)
                    continue

            logger.info(f"  {len(raw_records)} raw records")

            parsed = [_parse_record(r, commune) for r in raw_records]
            parsed = [r for r in parsed if r]
            logger.info(f"  {len(parsed)} parsed records")

            if dry_run:
                logger.info(f"  [DRY RUN] Would insert {len(parsed)} rows for {commune}")
                if parsed:
                    logger.info(f"  Sample: year={parsed[0].get('year')} uf={parsed[0].get('uf_value')} uf_m2={parsed[0].get('uf_m2_u')}")
                continue

            # Upsert into transactions_raw (skip existing roles)
            df = pd.DataFrame(parsed)
            with engine.begin() as conn:
                existing = set()
                roles = tuple(df["id_role"].dropna().unique().tolist())
                if roles:
                    res = conn.execute(
                        text("SELECT id_role FROM transactions_raw WHERE id_role = ANY(:roles) AND data_source='data_inmobiliaria'"),
                        {"roles": list(roles)}
                    )
                    existing = {r[0] for r in res}

                new_rows = df[~df["id_role"].isin(existing)] if existing else df
                dupes = len(df) - len(new_rows)

                if new_rows.empty:
                    logger.info(f"  All {len(df)} rows already in DB")
                    if use_checkpoint:
                        _save_checkpoint(commune, 0)
                    continue

                new_rows.to_sql("transactions_raw", conn, if_exists="append", index=False, method="multi")
                n = len(new_rows)
                total_written += n
                logger.info(f"  Written {n} rows ({dupes} dupes skipped)")

            if use_checkpoint:
                _save_checkpoint(commune, len(new_rows))

            await asyncio.sleep(2)  # polite delay between communes

        await browser.close()

    elapsed = time.time() - t_start
    logger.info("=" * 60)
    logger.info(f"DONE: {total_written} rows written in {elapsed/60:.1f}min")
    if quota_exhausted:
        logger.warning("NOTE: Run stopped early — quota exhausted. Re-run after midnight.")
        logger.warning("TIP: Register free at datainmobiliaria.cl and add credentials to .env to remove limit.")
    logger.info("=" * 60)

    if total_written > 0 and not dry_run:
        logger.info("Next steps:")
        logger.info("  py src/ingestion/clean_transactions.py")
        logger.info("  py src/ingestion/normalize_county.py")
        logger.info("  py src/features/build_features.py --skip-ieut")
        logger.info("  py src/models/hedonic_model.py")

    return total_written


def main():
    parser = argparse.ArgumentParser(description="Scraper datainmobiliaria.cl — CBR ventas efectivas")
    parser.add_argument("--commune",        type=str,  default=None,    help="Single commune name (e.g. 'Las Condes')")
    parser.add_argument("--fuente",         type=str,  default="ventas", choices=["ventas","catastro"], help="Data source type")
    parser.add_argument("--dry-run",        action="store_true",         help="Parse but don't write to DB")
    parser.add_argument("--min-year",       type=int,  default=None,     help="Only import records from this year onwards (e.g. 2019)")
    parser.add_argument("--max-pages",      type=int,  default=100,      help="Max pages per commune (~150 records each, default 100=guest limit)")
    parser.add_argument("--no-headless",    action="store_true",         help="Show browser window")
    parser.add_argument("--manual-login",   action="store_true",         help="Open browser for manual Google/OAuth login, save session, then scrape")
    parser.add_argument("--next-commune",   action="store_true",         help="Auto-pick next unscraped commune from checkpoint (for daily scheduling)")
    parser.add_argument("--check-quota",    action="store_true",         help="Test if API quota is available (200=ok, 402=exhausted)")
    parser.add_argument("--skip-checkpoint",action="store_true",         help="Ignore checkpoint — rescrape all communes")
    parser.add_argument("--list-status",    action="store_true",         help="Show checkpoint status and exit")
    args = parser.parse_args()

    if args.list_status:
        cp = _load_checkpoint()
        all_communes = list(RM_COMMUNE_POLYGONS.keys())
        done = [c for c in all_communes if c in cp]
        todo = [c for c in all_communes if c not in cp]
        print(f"\nCheckpoint: {len(done)}/{len(all_communes)} communes scraped")
        for c in done:
            print(f"  DONE  {c:25s}  {cp[c]['rows']:6d} rows  ({cp[c]['ts'][:10]})")
        if todo:
            print(f"\n  Pending ({len(todo)}):")
            for c in todo:
                print(f"  TODO  {c}")
        return

    if args.next_commune:
        next_c = _next_unscraped_commune()
        if next_c is None:
            logger.info("All 40 communes already scraped. Nothing to do.")
            return
        communes = [next_c]
        logger.info(f"--next-commune: picked '{next_c}'")
    elif args.commune:
        communes = [args.commune]
    else:
        communes = None  # all

    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    asyncio.run(scrape_all(
        engine,
        communes         = communes,
        fuente           = args.fuente,
        dry_run          = args.dry_run,
        max_pages        = args.max_pages,
        min_year         = args.min_year,
        headless         = not args.no_headless,
        use_checkpoint   = not args.skip_checkpoint,
        check_quota_only = args.check_quota,
        manual_login     = args.manual_login,
    ))


if __name__ == "__main__":
    main()
