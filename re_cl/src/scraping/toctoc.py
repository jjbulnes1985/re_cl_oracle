"""
toctoc.py
---------
Scraper for toctoc.com — Chilean real estate portal focused on secondary market.

URL pattern:
  https://www.toctoc.com/propiedades/venta/{type}/region-metropolitana?page={n}

Types mapped:
  apartments → departamentos
  residential → casas
  land        → terrenos
  retail      → locales-comerciales

Usage:
    python src/scraping/toctoc.py
    python src/scraping/toctoc.py --max-pages 20 --type residential
    python src/scraping/toctoc.py --dry-run

NOTE: Toctoc uses a Next.js frontend with server-side rendered JSON in __NEXT_DATA__.
      This is more reliable than DOM scraping. Selectors last verified: 2024-Q4.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.scraping.base import BaseScraper, ScrapedListing

TYPE_MAP = {
    "apartments": "departamento",    # /venta/departamento (singular, verified 2026-04)
    "residential": "casa",
    "land":        "terreno",
    "retail":      "local-comercial",
}


class ToctocScraper(BaseScraper):
    """Scraper for toctoc.com."""

    BASE_URL = "https://www.toctoc.com"

    @property
    def source_name(self) -> str:
        return "toctoc"

    def _build_url(self, page_num: int, property_type: str = "apartments", **kwargs) -> str:
        toctoc_type = TYPE_MAP.get(property_type, "departamento")
        base = f"{self.BASE_URL}/venta/{toctoc_type}"
        return base if page_num <= 1 else f"{base}?page={page_num}"

    async def _extract_listings(self, page) -> list[ScrapedListing]:
        """
        Extract listings from Toctoc via __NEXT_DATA__ (Next.js SSR).
        Data path: props.pageProps.propiedades.results
        Verified structure 2026-04: titulo, comuna, precios, superficie, dormitorios.
        """
        listings = []

        try:
            # __NEXT_DATA__ is a <script> tag — wait_for_selector won't work on hidden elements
            await page.wait_for_function(
                "document.getElementById('__NEXT_DATA__') !== null", timeout=15_000
            )
        except Exception:
            logger.warning("Toctoc: __NEXT_DATA__ not found, falling back to DOM")
            return await self._extract_dom(page)

        next_data = await page.evaluate("""() => {
            const el = document.getElementById('__NEXT_DATA__');
            return el ? JSON.parse(el.textContent) : null;
        }""")

        if not next_data:
            return await self._extract_dom(page)

        try:
            props = next_data.get("props", {}).get("pageProps", {})
            propiedades = props.get("propiedades") or {}
            results = (
                propiedades.get("results") or
                props.get("initialReduxState", {}).get("PropertyState", {}).get("results") or
                []
            )
            if not results:
                logger.warning("Toctoc: no results found in __NEXT_DATA__, trying DOM")
                return await self._extract_dom(page)
        except Exception as e:
            logger.debug(f"Toctoc Next.js parse error: {e}")
            return await self._extract_dom(page)

        for prop in results:
            listing = self._parse_toctoc_property(prop)
            if listing:
                listings.append(listing)

        logger.debug(f"Toctoc __NEXT_DATA__ extracted {len(listings)} listings")
        return listings

    def _parse_toctoc_property(self, prop: dict) -> Optional[ScrapedListing]:
        """
        Parse a Toctoc property result item.
        Verified structure (2026-04):
          titulo, comuna, tipoPropiedad, urlFicha,
          precios: [{"prefix": "UF", "value": "2.100"}, ...],
          superficie: ["49,36", ...], dormitorios: ["3"], bannos: ["1"]
        """
        try:
            full_url = prop.get("urlFicha", "")
            # ext_id: last numeric segment of urlFicha (e.g. /.../.../2643817)
            ext_id = full_url.rstrip("/").split("/")[-1] if full_url else ""
            if not ext_id or not ext_id.isdigit():
                ext_id = str(prop.get("id") or prop.get("clientId") or "")
            if not ext_id:
                return None

            # Price: find the UF-prefixed entry
            price_uf = None
            for p in prop.get("precios", []):
                if isinstance(p, dict) and p.get("prefix", "").upper() in ("UF", "CLF"):
                    raw = str(p.get("value", "")).replace(".", "").replace(",", ".")
                    try:
                        price_uf = float(raw)
                        break
                    except ValueError:
                        pass

            # Surface: first value in lista (comma as decimal separator in Chilean locale)
            surface_m2 = None
            superficies = prop.get("superficie", [])
            if superficies:
                raw_surf = str(superficies[0]).replace(",", ".")
                try:
                    surface_m2 = float(raw_surf)
                except ValueError:
                    pass

            # Bedrooms / bathrooms
            dormitorios = prop.get("dormitorios", [])
            bannos      = prop.get("bannos", [])
            bedrooms  = int(dormitorios[0]) if dormitorios and str(dormitorios[0]).isdigit() else None
            bathrooms = int(bannos[0])      if bannos      and str(bannos[0]).isdigit()      else None

            county = str(prop.get("comuna", "") or "")
            ptype  = self._infer_type(prop.get("tipoPropiedad", ""), full_url)

            return ScrapedListing(
                source       = self.source_name,
                external_id  = ext_id,
                url          = full_url,
                project_type = ptype,
                county_name  = county.strip(),
                price_uf     = price_uf,
                surface_m2   = surface_m2,
                bedrooms     = bedrooms,
                bathrooms    = bathrooms,
                description  = prop.get("titulo"),
                raw_json     = json.dumps(prop)[:4000],
            )
        except Exception as e:
            logger.debug(f"Toctoc property parse error: {e}")
            return None

    async def _extract_dom(self, page) -> list[ScrapedListing]:
        """DOM fallback if Next.js data is unavailable."""
        listings = []
        cards = await page.query_selector_all("[data-testid='property-card'], .property-card, .listing-card")

        for card in cards:
            try:
                # Price
                price_el = await card.query_selector("[data-testid='price'], .price, .listing-price")
                price_raw = await price_el.inner_text() if price_el else ""
                price_uf  = self._parse_uf(price_raw)

                # Surface
                surface_el = await card.query_selector("[data-testid='surface'], .surface, .m2")
                surface_raw = await surface_el.inner_text() if surface_el else ""
                surface_m2  = self._parse_surface(surface_raw)

                # URL
                link_el = await card.query_selector("a")
                url = await link_el.get_attribute("href") if link_el else ""
                ext_id = url.split("/")[-1].split("?")[0] if url else ""

                # Location
                loc_el = await card.query_selector(".location, .commune, [data-testid='commune']")
                county = await loc_el.inner_text() if loc_el else ""

                if not ext_id or not county:
                    continue

                title_el = await card.query_selector("h2, h3, .title")
                title = await title_el.inner_text() if title_el else ""
                ptype = self._infer_type(title, url)

                listings.append(ScrapedListing(
                    source      = self.source_name,
                    external_id = ext_id,
                    url         = f"{self.BASE_URL}{url}" if url.startswith("/") else url,
                    project_type = ptype,
                    county_name = county.strip(),
                    price_uf    = price_uf,
                    surface_m2  = surface_m2,
                ))
            except Exception as e:
                logger.debug(f"Toctoc DOM card error: {e}")

        return listings

    def _infer_type(self, text: str, url: str = "") -> str:
        combined = (text + " " + url).lower()
        if "departamento" in combined or "apart" in combined:
            return "apartments"
        if "casa" in combined or "residential" in combined:
            return "residential"
        if "terreno" in combined or "land" in combined:
            return "land"
        if "local" in combined or "oficina" in combined or "retail" in combined:
            return "retail"
        return "unknown"


# ── Parallel runner (Phase 9) ─────────────────────────────────────────────────

async def _scrape_toctoc_all_types_async(engine, max_pages: int = 50) -> int:
    """Run all 4 Toctoc property types concurrently.

    Each ToctocScraper instance creates its own async_playwright() +
    browser + context inside scrape_async(), so 4 concurrent coroutines
    do NOT share Playwright state. Writes go through _write_batch()
    which uses engine.begin() (connection-pool safe).
    """
    import random

    async def one_type(ptype: str) -> int:
        scraper = ToctocScraper(engine=engine)
        # Stagger browser launches by up to 2s to avoid simultaneous TCP handshakes
        await asyncio.sleep(random.uniform(0, 2))
        n = await scraper.scrape_async(max_pages=max_pages, property_type=ptype)
        logger.info(f"[toctoc-parallel] {ptype}: {n} listings")
        return n

    results = await asyncio.gather(
        *[one_type(pt) for pt in TYPE_MAP.keys()],
        return_exceptions=True,
    )
    total = 0
    errors = []
    for ptype, r in zip(TYPE_MAP.keys(), results):
        if isinstance(r, Exception):
            errors.append((ptype, r))
            logger.warning(f"[toctoc-parallel] {ptype} FAILED: {r}")
        else:
            total += int(r)
    if errors:
        logger.warning(f"[toctoc-parallel] {len(errors)}/{len(TYPE_MAP)} types failed")
    logger.info(f"[toctoc-parallel] total: {total} listings across {len(TYPE_MAP)} types")
    return total


def run_parallel(engine=None, max_pages: int = 50) -> int:
    """Sync entry point for Prefect task. Runs 4 property types concurrently."""
    return asyncio.run(_scrape_toctoc_all_types_async(engine, max_pages))


# ── Module run() ──────────────────────────────────────────────────────────────

def run(engine=None, max_pages: int = 50, property_types: list = None) -> int:
    if property_types is None:
        property_types = list(TYPE_MAP.keys())

    total = 0
    for ptype in property_types:
        logger.info(f"[toctoc] Scraping type: {ptype}")
        scraper = ToctocScraper(engine=engine)
        n = scraper.run(max_pages=max_pages, property_type=ptype)
        total += n
        logger.info(f"[toctoc] {ptype}: {n} listings scraped")

    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--type", choices=list(TYPE_MAP.keys()), default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dump-html", action="store_true",
                        help="Save page HTML + log __NEXT_DATA__ structure for debugging")
    args = parser.parse_args()

    if args.dry_run:
        logger.info("[DRY RUN] Would scrape Toctoc. No actual requests.")
        sys.exit(0)

    def _build_db_url():
        url = os.getenv("DATABASE_URL")
        if url:
            return url
        return (
            f"postgresql://{os.getenv('POSTGRES_USER','re_cl_user')}:"
            f"{os.getenv('POSTGRES_PASSWORD','')}@"
            f"{os.getenv('POSTGRES_HOST','localhost')}:"
            f"{os.getenv('POSTGRES_PORT','5432')}/"
            f"{os.getenv('POSTGRES_DB','re_cl')}"
        )

    eng = create_engine(_build_db_url(), pool_pre_ping=True)
    types = [args.type] if args.type else list(TYPE_MAP.keys())

    if args.dump_html:
        import asyncio, random
        from playwright.async_api import async_playwright
        from src.scraping.base import USER_AGENTS

        async def _dump():
            scraper = ToctocScraper(engine=eng)
            ptype = types[0]
            url = scraper._build_url(1, property_type=ptype)
            logger.info(f"Loading {url} for Toctoc inspection...")
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                ctx = await browser.new_context(user_agent=random.choice(USER_AGENTS))
                page = await ctx.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                await page.wait_for_timeout(3000)
                html = await page.content()
                debug_path = Path("data/exports/toctoc_debug.html")
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                debug_path.write_text(html[:500_000], encoding="utf-8", errors="replace")
                logger.info(f"HTML dumped to {debug_path}")
                listings = await scraper._extract_listings(page)
                logger.info(f"Extracted {len(listings)} listings")
                for l in listings[:3]:
                    logger.info(f"  id={l.external_id} | price={l.price_uf} UF | surf={l.surface_m2}m2 | county={l.county_name}")
                await browser.close()

        asyncio.run(_dump())
        sys.exit(0)

    total = run(engine=eng, max_pages=args.max_pages, property_types=types)
    logger.info(f"Total scraped: {total:,} listings")
