"""
mercadolibre.py
---------------
MercadoLibre Inmuebles scraper for Región Metropolitana.

Uses ML's public REST API — no Playwright required.
API: https://api.mercadolibre.com/sites/MLC/search

Category IDs (Inmuebles RM):
  MLC1459 → Inmuebles (parent)
  MLC1051 → Departamentos
  MLC1461 → Casas
  MLC1462 → Terrenos
  MLC1466 → Locales y Oficinas
  MLC2008 → Oficinas

State ID: TUxDUFJNQWw = RM Santiago (base64 encoded)

Rate limit: ~1 req/s recommended (no auth). Max 50 results per request.
Max offset: 1000 (ML API hard limit per query). Use sub-queries by type to maximize.

Expected: 5,000-8,000 unique listings across types.

Usage:
    py src/scraping/mercadolibre.py
    py src/scraping/mercadolibre.py --max-offset 1000
    py src/scraping/mercadolibre.py --type apartments
    py src/scraping/mercadolibre.py --dry-run
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.scraping.base import BaseScraper, ScrapedListing

# ML API Configuration
ML_API_BASE = "https://api.mercadolibre.com"
ML_STATE_ID  = "TUxDUFJNQWw"   # RM Santiago
ML_LIMIT     = 50               # max per request (ML API limit)
ML_MAX_OFFSET = 1000            # ML API hard cap
REQUEST_DELAY = 1.1             # seconds between requests (rate limit)

ML_CATEGORIES = {
    "apartments":  "MLC1051",   # Departamentos
    "residential": "MLC1461",   # Casas
    "land":        "MLC1462",   # Terrenos
    "commercial":  "MLC1466",   # Locales y Oficinas
    "offices":     "MLC2008",   # Oficinas
}

# Typology normalization from ML category → our project_type
ML_TYPOLOGY_MAP = {
    "MLC1051": "apartments",
    "MLC1461": "residential",
    "MLC1462": "land",
    "MLC1466": "commercial",
    "MLC2008": "commercial",
}

UF_VALUE_APPROX = float(os.getenv("UF_VALUE_APPROX", "37000"))

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; RE_CL-scraper/1.0)",
    "Accept": "application/json",
})


# ── API functions ──────────────────────────────────────────────────────────────

def _search(category_id: str, offset: int = 0) -> dict:
    """Call ML search API and return raw JSON. No condition filter — CL marketplace doesn't support it."""
    url = f"{ML_API_BASE}/sites/MLC/search"
    params = {
        "category": category_id,
        "state":    ML_STATE_ID,
        "offset":   offset,
        "limit":    ML_LIMIT,
    }
    try:
        resp = SESSION.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.warning(f"  API error at offset {offset}: {e}")
        return {}


# ── Parsing ────────────────────────────────────────────────────────────────────

def _extract_attribute(attributes: list, attr_id: str) -> Optional[str]:
    """Extract a specific attribute value from ML attributes list."""
    for attr in attributes or []:
        if attr.get("id") == attr_id:
            return attr.get("value_name") or attr.get("values", [{}])[0].get("name")
    return None


def _parse_listing(item: dict, category_id: str) -> Optional[ScrapedListing]:
    """Convert a single ML search result item to ScrapedListing."""
    try:
        ext_id = str(item.get("id", ""))
        if not ext_id:
            return None

        # Price in CLP
        price_clp = item.get("price")
        currency   = item.get("currency_id", "CLP")
        price_uf   = None
        if price_clp:
            if currency == "UF":
                price_uf = float(price_clp)
            elif currency == "CLP":
                price_uf = float(price_clp) / UF_VALUE_APPROX
            else:
                price_uf = float(price_clp) / UF_VALUE_APPROX  # assume CLP

        # Location
        location = item.get("location", {}) or {}
        county   = (
            location.get("city", {}).get("name") if isinstance(location.get("city"), dict) else None or
            location.get("neighborhood", {}).get("name") if isinstance(location.get("neighborhood"), dict) else None or
            ""
        )
        lat = location.get("latitude")
        lon = location.get("longitude")

        # Attributes
        attrs = item.get("attributes", [])
        surface_str = _extract_attribute(attrs, "TOTAL_AREA") or _extract_attribute(attrs, "COVERED_AREA")
        surface = None
        if surface_str:
            try:
                surface = float(str(surface_str).replace(",", ".").split()[0])
            except ValueError:
                pass

        rooms_str = _extract_attribute(attrs, "ROOMS")
        rooms = None
        if rooms_str:
            try:
                rooms = int(rooms_str)
            except ValueError:
                pass

        uf_m2 = None
        if price_uf and surface and surface > 0:
            uf_m2 = price_uf / surface

        project_type = ML_TYPOLOGY_MAP.get(category_id, "residential")

        return ScrapedListing(
            source="mercadolibre",
            external_id=ext_id,
            project_type=project_type,
            county_name=county.strip() if county else None,
            price_uf=price_uf,
            surface_m2=surface,
            uf_m2=uf_m2,
            latitude=float(lat) if lat is not None else None,
            longitude=float(lon) if lon is not None else None,
            url=item.get("permalink", f"https://www.mercadolibre.cl/MLC-{ext_id}"),
            raw_data={
                "title": item.get("title"),
                "rooms": rooms,
                "thumbnail": item.get("thumbnail"),
                "currency": currency,
                "price_clp": price_clp,
            },
        )
    except Exception as e:
        logger.debug(f"  Failed parsing ML item {item.get('id')}: {e}")
        return None


# ── Main scraping logic ────────────────────────────────────────────────────────

class _MLWriter(BaseScraper):
    """Minimal BaseScraper subclass used only for its _write_batch method."""
    SOURCE = "mercadolibre"

    @property
    def source_name(self) -> str:
        return self.SOURCE

    def __init__(self, engine):
        self.engine = engine

    def _build_url(self, page_num, **kwargs):
        return ""

    async def _extract_listings(self, page):
        return []


def scrape_category(category_id: str, project_type: str, engine,
                    max_offset: int = ML_MAX_OFFSET,
                    dry_run: bool = False) -> int:
    """Scrape a single ML category (new + used) up to max_offset."""
    writer = _MLWriter(engine) if engine else None
    total = 0
    offset = 0
    consecutive_empty = 0

    while offset <= max_offset:
        data = _search(category_id, offset)
        items = data.get("results", [])

        if not items:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                break
            offset += ML_LIMIT
            time.sleep(REQUEST_DELAY)
            continue

        consecutive_empty = 0
        api_total = data.get("paging", {}).get("total", 0)

        listings = []
        for item in items:
            listing = _parse_listing(item, category_id)
            if listing and listing.uf_m2 and listing.uf_m2 > 0:
                listings.append(listing)

        if dry_run:
            logger.info(f"  [DRY RUN] {project_type} offset={offset}: {len(listings)} listings (API total: {api_total:,})")
        elif writer and listings:
            n = writer._write_batch(listings)
            total += n
            logger.info(f"  {project_type} offset={offset}/{min(api_total, max_offset)}: +{n} written")

        if offset + ML_LIMIT > min(api_total, max_offset):
            break

        offset += ML_LIMIT
        time.sleep(REQUEST_DELAY)

    return total


def run(engine=None, max_offset: int = ML_MAX_OFFSET,
        property_types: list = None, dry_run: bool = False) -> int:
    if property_types is None:
        property_types = list(ML_CATEGORIES.keys())

    logger.info("=" * 60)
    logger.info(f"MERCADOLIBRE SCRAPER (max_offset={max_offset})")
    logger.info("=" * 60)

    total = 0
    for ptype in property_types:
        cat_id = ML_CATEGORIES.get(ptype)
        if not cat_id:
            logger.warning(f"Unknown property type: {ptype}")
            continue
        logger.info(f"Scraping {ptype} (category={cat_id})")
        n = scrape_category(cat_id, ptype, engine,
                            max_offset=max_offset, dry_run=dry_run)
        total += n
        logger.info(f"  {ptype}: {n:,} total")

    logger.info(f"MercadoLibre total: {total:,} listings written")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-offset", type=int, default=ML_MAX_OFFSET,
                        help=f"Max ML API offset per type (hard cap: {ML_MAX_OFFSET})")
    parser.add_argument("--type",       default=None,
                        choices=list(ML_CATEGORIES.keys()),
                        help="Property type (default: all)")
    parser.add_argument("--dry-run",    action="store_true")
    args = parser.parse_args()

    def _build_db_url():
        url = os.getenv("DATABASE_URL")
        if url: return url
        return f"postgresql://{os.getenv('POSTGRES_USER','re_cl_user')}:{os.getenv('POSTGRES_PASSWORD','')}@{os.getenv('POSTGRES_HOST','localhost')}:{os.getenv('POSTGRES_PORT','5432')}/{os.getenv('POSTGRES_DB','re_cl')}"

    from sqlalchemy import create_engine as _ce
    engine = _ce(_build_db_url(), pool_pre_ping=True) if not args.dry_run else None
    ptypes = [args.type] if args.type else list(ML_CATEGORIES.keys())
    run(engine=engine, max_offset=args.max_offset, property_types=ptypes, dry_run=args.dry_run)
