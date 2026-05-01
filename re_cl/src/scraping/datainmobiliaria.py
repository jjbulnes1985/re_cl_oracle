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

Multi-account rotation:
  When a 402 is encountered, automatically rotate to the next cookie file and
  retry the current commune from page 1. Use --extra-cookie-files to pass
  additional accounts.

Usage:
  py src/scraping/datainmobiliaria.py --dry-run
  py src/scraping/datainmobiliaria.py --commune "Las Condes" --min-year 2019
  py src/scraping/datainmobiliaria.py --min-year 2019           # all 40 RM communes
  py src/scraping/datainmobiliaria.py --next-commune            # resume: pick next unscraped commune
  py src/scraping/datainmobiliaria.py --fuente catastro         # cadastral data
  py src/scraping/datainmobiliaria.py --check-quota             # test if API is accessible
  py src/scraping/datainmobiliaria.py --cookie-file data/processed/di_cookies_acct2.json
  py src/scraping/datainmobiliaria.py --extra-cookie-files data/processed/di_cookies_acct2.json data/processed/di_cookies_acct3.json
  py src/scraping/datainmobiliaria.py --list-status             # show checkpoint + configured accounts
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import deque
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

# Default cookie file
COOKIE_FILE = Path(__file__).resolve().parents[2] / "data" / "processed" / "datainmobiliaria_cookies.json"


def _load_checkpoint() -> dict:
    """Load checkpoint data. Returns {commune: {"rows": N, "ts": "...", "partial": bool}}."""
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_checkpoint(commune: str, rows_written: int, partial: bool = False) -> None:
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = _load_checkpoint()
    entry: dict = {"rows": rows_written, "ts": pd.Timestamp.now().isoformat()}
    if partial:
        entry["partial"] = True
    elif "partial" in data.get(commune, {}):
        pass  # will be replaced by new entry without partial flag
    data[commune] = entry
    CHECKPOINT_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _next_unscraped_commune() -> Optional[str]:
    """Return the first commune not yet fully scraped (excludes partial entries)."""
    cp = _load_checkpoint()
    done = {k for k, v in cp.items() if not v.get("partial")}
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


async def _fetch_commune_streaming(
    page,
    commune: str,
    polygon: list,
    fuente: str = "ventas",
    max_pages: int = 999,
    min_year: Optional[int] = None,
):
    """Async generator that yields (batch, quota_hit) one page at a time.

    Yields:
        (records: list[dict], quota_hit: bool)
        quota_hit=True on the final yield when 402 is received.
        quota_hit=False for normal pages; after the last page the generator ends.
    """
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
            status = result["error"]
            if status == 402:
                logger.warning(f"  API 402 on page {p_num} — quota exhausted")
                yield [], True
                return
            logger.warning(f"  API error page {p_num}: {status}")
            return

        batch = result.get("resultados", [])
        if not batch:
            return

        if min_year:
            def _year(rec):
                d = str(rec.get("date_inscripcion") or "")
                m = re.search(r"(\d{4})", d)
                return int(m.group(1)) if m else 0
            batch = [r for r in batch if _year(r) >= min_year]

        has_more = result.get("has_more", False)
        logger.debug(f"  Page {p_num}: {len(batch)} records, has_more={has_more}")

        yield batch, False

        if not has_more:
            return

        p_num += 1
        await asyncio.sleep(0.5)


def _save_cookies(cookies: list, path: Optional[Path] = None) -> None:
    target = path or COOKIE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cookies, indent=2, ensure_ascii=False))
    logger.info(f"Session cookies saved → {target}")


def _load_cookies(path: Optional[Path] = None) -> list:
    target = path or COOKIE_FILE
    if target.exists():
        try:
            return json.loads(target.read_text())
        except Exception:
            pass
    return []


def _discover_cookie_files() -> list[Path]:
    """Return all cookie files in data/processed/ matching di_cookies_*.json plus the default."""
    processed_dir = COOKIE_FILE.parent
    files = []
    if COOKIE_FILE.exists():
        files.append(COOKIE_FILE)
    for p in sorted(processed_dir.glob("di_cookies_*.json")):
        if p not in files:
            files.append(p)
    return files


def _credentials_for_cookie_file(cookie_file: Optional[Path]) -> tuple[Optional[str], Optional[str]]:
    """Return (email, password) from env vars for a given cookie file.

    Looks for DATA_INMOBILIARIA_EMAIL_N / PASSWORD_N where N matches the
    cookie filename suffix (di_cookies_2.json → N=2). Falls back to the
    unnumbered DATA_INMOBILIARIA_EMAIL / PASSWORD for the default file.
    """
    fname = cookie_file.name if cookie_file else COOKIE_FILE.name
    # di_cookies_2.json → "2", di_cookies_3.json → "3", default → ""
    import re as _re
    m = _re.search(r"_(\d+)\.json$", fname)
    suffix = m.group(1) if m else ""
    if suffix:
        email = os.getenv(f"DATA_INMOBILIARIA_EMAIL_{suffix}")
        pwd   = os.getenv(f"DATA_INMOBILIARIA_PASSWORD_{suffix}")
    else:
        email = os.getenv("DATA_INMOBILIARIA_EMAIL")
        pwd   = os.getenv("DATA_INMOBILIARIA_PASSWORD")
    return email or None, pwd or None


async def _auto_login(page, context, email: str, password: str, cookie_file: Optional[Path]) -> bool:
    """Attempt email+password login. Returns True on success."""
    logger.info(f"  Auto-login as {email}...")
    try:
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        await page.fill('input[type="email"], #user_email', email)
        await page.fill('input[type="password"], #user_password', password)
        await page.click('input[type="submit"], button[type="submit"]')
        await page.wait_for_timeout(3000)
        if "sign_in" not in page.url:
            cookies = await context.cookies()
            _save_cookies(cookies, cookie_file)
            logger.info(f"  Auto-login successful — cookies refreshed")
            return True
        else:
            logger.warning(f"  Auto-login failed (wrong credentials?)")
            return False
    except Exception as e:
        logger.warning(f"  Auto-login error: {e}")
        return False


async def _setup_context_with_cookies(
    browser,
    cookie_file: Optional[Path],
    manual_login: bool,
    email: Optional[str],
    password: Optional[str],
    headless: bool,
    proxy_url: Optional[str] = None,
) -> tuple:
    """Create a new browser context, apply cookies or auto-login, navigate to SEARCH_PAGE.

    Session expiry detection: if after loading cookies the page redirects to /sign_in,
    the session has expired. We then attempt auto-login using credentials from env vars.

    proxy_url: optional HTTP proxy URL (http://user:pass@host:port) for IP rotation.
    Useful with residential proxies (Bright Data, IPRoyal) when DI quota is per-IP.

    Returns (context, page, csrf_token).
    """
    context_kwargs = {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    if proxy_url:
        from urllib.parse import urlparse
        parsed = urlparse(proxy_url)
        proxy_config = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
        if parsed.username:
            proxy_config["username"] = parsed.username
        if parsed.password:
            proxy_config["password"] = parsed.password
        context_kwargs["proxy"] = proxy_config
        logger.info(f"  Using proxy: {parsed.hostname}:{parsed.port}")

    context = await browser.new_context(**context_kwargs)

    saved_cookies = _load_cookies(cookie_file)
    if saved_cookies and not manual_login:
        await context.add_cookies(saved_cookies)
        label = cookie_file.name if cookie_file else COOKIE_FILE.name
        logger.info(f"Restored {len(saved_cookies)} cookies from {label}")

    page = await context.new_page()

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
        _save_cookies(cookies, cookie_file)
    else:
        # Resolve credentials for this account (env vars take priority over caller args)
        acct_email, acct_pwd = _credentials_for_cookie_file(cookie_file)
        if not acct_email:
            acct_email, acct_pwd = email, password

        if not saved_cookies and acct_email and acct_pwd:
            # No saved session — login fresh
            await _auto_login(page, context, acct_email, acct_pwd, cookie_file)

    # Navigate to search page and detect session expiry
    await page.goto(SEARCH_PAGE, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    # If redirected to login page, session has expired — try auto-login
    if "sign_in" in page.url:
        acct_email, acct_pwd = _credentials_for_cookie_file(cookie_file)
        if not acct_email:
            acct_email, acct_pwd = email, password
        if acct_email and acct_pwd:
            logger.warning("  Session expired — attempting auto-login")
            ok = await _auto_login(page, context, acct_email, acct_pwd, cookie_file)
            if ok:
                await page.goto(SEARCH_PAGE, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
            else:
                logger.warning("  Auto-login failed — will scrape as guest (quota may be limited)")
        else:
            logger.warning("  Session expired and no credentials available for this account")
            logger.warning("  Add DATA_INMOBILIARIA_EMAIL[_N] / PASSWORD[_N] to .env for auto-login")

    csrf = await page.evaluate('() => document.querySelector("meta[name=csrf-token]")?.content || ""')
    logger.info(f"CSRF token acquired: {'yes' if csrf else 'no'}")

    return context, page, csrf


def _write_page_to_db(engine, parsed: list[dict], commune: str) -> int:
    """Write a parsed page to DB, skipping duplicates. Returns new rows written."""
    if not parsed:
        return 0
    df = pd.DataFrame(parsed)
    with engine.begin() as conn:
        roles = df["id_role"].dropna().unique().tolist()
        existing: set = set()
        if roles:
            res = conn.execute(
                text("SELECT id_role FROM transactions_raw WHERE id_role = ANY(:roles) AND data_source='data_inmobiliaria'"),
                {"roles": roles},
            )
            existing = {r[0] for r in res}
        new_rows = df[~df["id_role"].isin(existing)] if existing else df
        if new_rows.empty:
            return 0
        new_rows.to_sql("transactions_raw", conn, if_exists="append", index=False, method="multi")
        return len(new_rows)


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
    cookie_file: Optional[Path] = None,
    extra_cookie_files: Optional[list[Path]] = None,
    proxy_urls: Optional[list[str]] = None,
) -> int:
    """Stream-scrape communes, writing to DB page-by-page so partial progress is never lost.

    Account rotation on 402:
    - 0 rows written for this commune → rotate and retry same commune from page 1.
    - >0 rows written (partial commune) → save partial checkpoint, rotate and continue
      with next commune. On the next daily run the partial commune is retried; dedup
      via id_role handles any overlap.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ImportError("playwright required: pip install playwright && playwright install chromium")

    if communes is None:
        communes = list(RM_COMMUNE_POLYGONS.keys())

    # Skip fully-scraped communes (partial ones are retried)
    if use_checkpoint and not dry_run and not check_quota_only:
        checkpoint = _load_checkpoint()
        done = {k for k, v in checkpoint.items() if not v.get("partial")}
        communes_todo = [c for c in communes if c not in done]
        skipped = len(communes) - len(communes_todo)
        if skipped:
            logger.info(f"Checkpoint: skipping {skipped} fully-scraped communes")
        communes = communes_todo

    if not communes and not check_quota_only:
        logger.info("All communes already scraped per checkpoint. Done.")
        return 0

    primary_cookie = cookie_file
    rotation_files: deque[Optional[Path]] = deque([primary_cookie])
    if extra_cookie_files:
        for ef in extra_cookie_files:
            if ef not in rotation_files:
                rotation_files.append(ef)

    total_accounts = len(rotation_files)
    current_account_idx = 1

    email    = os.getenv("DATA_INMOBILIARIA_EMAIL")
    password = os.getenv("DATA_INMOBILIARIA_PASSWORD")

    if manual_login:
        headless = False

    t_start = time.time()
    total_written = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        current_cookie_file = rotation_files[0]
        current_proxy = (proxy_urls or [None] * len(rotation_files))[0] if proxy_urls else None
        context, page, csrf = await _setup_context_with_cookies(
            browser, current_cookie_file, manual_login, email, password, headless, proxy_url=current_proxy
        )

        if check_quota_only:
            test_polygon = list(RM_COMMUNE_POLYGONS.values())[0]
            statuses = []
            for probe_page in [1, 2]:
                body = {"polygon": test_polygon, "fuente": fuente, "page": probe_page}
                result = await page.evaluate(f'''async () => {{
                    const r = await fetch('/reports/busqueda_poligono_data', {{
                        method: 'POST',
                        headers: {{'Content-Type':'application/json','Accept':'application/json','X-CSRF-Token': document.querySelector('meta[name=csrf-token]')?.content||''}},
                        body: JSON.stringify({json.dumps(body)})
                    }});
                    return {{status: r.status}};
                }}''')
                statuses.append(result.get("status", 0))
                if result.get("status") == 402:
                    break
            status = statuses[-1]
            if status == 200:
                logger.info(f"Quota check: API accessible (200 on page {len(statuses)}). Ready to scrape.")
            elif status == 402:
                logger.warning("Quota check: 402 — quota exhausted. Wait until midnight or switch session.")
            else:
                logger.warning(f"Quota check: unexpected status {status}")
            await browser.close()
            return 0

        logger.info(f"Communes: {len(communes)} | fuente={fuente} | min_year={min_year} | max_pages={max_pages}")
        logger.info(f"Accounts configured: {total_accounts}")
        logger.info("=" * 60)

        all_accounts_exhausted = False
        commune_idx = 0

        while commune_idx < len(communes):
            commune = communes[commune_idx]
            polygon = RM_COMMUNE_POLYGONS.get(commune)
            if not polygon:
                logger.warning(f"No polygon defined for {commune}, skipping")
                commune_idx += 1
                continue

            logger.info(f"Scraping: {commune} (account {current_account_idx}/{total_accounts})")

            commune_rows = 0   # rows written for this commune in this session
            quota_hit    = False

            async for batch, is_quota in _fetch_commune_streaming(
                page, commune, polygon, fuente=fuente,
                max_pages=max_pages, min_year=min_year,
            ):
                if is_quota:
                    quota_hit = True
                    break
                if not batch:
                    continue

                parsed = [_parse_record(r, commune) for r in batch]
                parsed = [r for r in parsed if r]

                if dry_run:
                    logger.info(f"  [DRY RUN] Page: {len(parsed)} rows")
                    continue

                n = _write_page_to_db(engine, parsed, commune)
                commune_rows   += n
                total_written  += n

            if quota_hit:
                rotation_files.popleft()
                if rotation_files:
                    current_account_idx += 1
                    next_cookie = rotation_files[0]
                    next_label  = next_cookie.name if next_cookie else COOKIE_FILE.name
                    next_proxy  = proxy_urls[current_account_idx - 1] if proxy_urls and len(proxy_urls) >= current_account_idx else None
                    logger.warning(
                        f"Quota exhausted on account {current_account_idx - 1} "
                        f"— switching to account {current_account_idx}/{total_accounts} ({next_label})"
                        + (f" via proxy {next_proxy.split('@')[-1] if '@' in next_proxy else next_proxy}" if next_proxy else "")
                    )
                    await context.close()
                    context, page, csrf = await _setup_context_with_cookies(
                        browser, next_cookie, False, email, password, headless, proxy_url=next_proxy
                    )
                    if commune_rows == 0:
                        # Nothing was written yet — retry same commune with fresh account
                        logger.info(f"  Retrying {commune} from page 1 (0 rows written so far)")
                        continue
                    else:
                        # Partial data saved — checkpoint as partial, advance to next commune
                        logger.info(
                            f"  {commune}: {commune_rows} rows written before quota hit "
                            f"— saved as partial, continuing with next commune"
                        )
                        if use_checkpoint and not dry_run:
                            _save_checkpoint(commune, commune_rows, partial=True)
                        commune_idx += 1
                        continue
                else:
                    if commune_rows > 0 and use_checkpoint and not dry_run:
                        _save_checkpoint(commune, commune_rows, partial=True)
                        logger.info(f"  {commune}: partial checkpoint saved ({commune_rows} rows)")
                    logger.error(
                        "All accounts exhausted. "
                        "Stopping. Run again after midnight or register additional accounts."
                    )
                    all_accounts_exhausted = True
                    break

            if not dry_run and commune_rows > 0 and not quota_hit:
                logger.info(f"  {commune}: {commune_rows} rows written — complete")
                if use_checkpoint:
                    _save_checkpoint(commune, commune_rows)
            elif not dry_run and commune_rows == 0 and not quota_hit:
                logger.info(f"  {commune}: no new rows (all already in DB or no data)")
                if use_checkpoint:
                    _save_checkpoint(commune, 0)

            commune_idx += 1
            if not quota_hit:
                await asyncio.sleep(2)

        await context.close()
        await browser.close()

    elapsed = time.time() - t_start
    logger.info("=" * 60)
    logger.info(f"DONE: {total_written} rows written in {elapsed/60:.1f}min")
    if all_accounts_exhausted:
        logger.warning("NOTE: Run stopped early — all accounts exhausted.")
        logger.warning("TIP: Register additional free accounts at datainmobiliaria.cl")
        logger.warning("     and pass their cookie files via --extra-cookie-files.")
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
    parser.add_argument("--list-status",    action="store_true",         help="Show checkpoint status and configured accounts, then exit")
    parser.add_argument("--cookie-file",    type=Path, default=None,     help="Override default cookie file path (e.g. data/processed/di_cookies_acct2.json)")
    parser.add_argument("--extra-cookie-files", type=Path, nargs="+", default=None,
                        help="Additional cookie files for multi-account rotation (space-separated paths)")
    args = parser.parse_args()

    if args.list_status:
        cp = _load_checkpoint()
        all_communes = list(RM_COMMUNE_POLYGONS.keys())
        fully_done   = [c for c in all_communes if c in cp and not cp[c].get("partial")]
        partial_done = [c for c in all_communes if c in cp and cp[c].get("partial")]
        todo         = [c for c in all_communes if c not in cp]
        print(f"\nCheckpoint: {len(fully_done)}/{len(all_communes)} communes complete"
              f" (+{len(partial_done)} partial)")
        for c in fully_done:
            print(f"  DONE     {c:25s}  {cp[c]['rows']:6d} rows  ({cp[c]['ts'][:10]})")
        for c in partial_done:
            print(f"  PARTIAL  {c:25s}  {cp[c]['rows']:6d} rows  ({cp[c]['ts'][:10]}) — will retry")
        if todo:
            print(f"\n  Pending ({len(todo)}):")
            for c in todo:
                print(f"  TODO  {c}")

        # Show configured accounts
        print("\nConfigured accounts:")
        cookie_files = _discover_cookie_files()
        if args.cookie_file:
            primary = args.cookie_file
            extras = [f for f in cookie_files if f != primary]
            cookie_files = [primary] + extras
        if not cookie_files:
            print("  (none found — run --manual-login to save a session)")
        for i, cf in enumerate(cookie_files, 1):
            exists = "OK" if cf.exists() else "MISSING"
            label = "(default)" if cf == COOKIE_FILE else ""
            print(f"  Account {i}: {cf.name} [{exists}] {label}")
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
        communes            = communes,
        fuente              = args.fuente,
        dry_run             = args.dry_run,
        max_pages           = args.max_pages,
        min_year            = args.min_year,
        headless            = not args.no_headless,
        use_checkpoint      = not args.skip_checkpoint,
        check_quota_only    = args.check_quota,
        manual_login        = args.manual_login,
        cookie_file         = args.cookie_file,
        extra_cookie_files  = args.extra_cookie_files,
    ))


if __name__ == "__main__":
    main()
