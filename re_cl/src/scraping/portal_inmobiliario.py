"""
portal_inmobiliario.py
----------------------
Scraper for portalinmobiliario.com — Chile's largest real estate portal.
Powered by MercadoLibre infrastructure (Polaris UI, updated 2025).

URL pattern (venta, RM):
  https://www.portalinmobiliario.com/venta/{type}/region-metropolitana-metropolitana/_Desde_{offset}_NoIndex_True

Types mapped:
  apartments → departamento
  residential → casa
  land        → terreno
  retail      → local-comercial

Usage:
    python src/scraping/portal_inmobiliario.py
    python src/scraping/portal_inmobiliario.py --max-pages 20 --type apartments
    python src/scraping/portal_inmobiliario.py --dry-run
    python src/scraping/portal_inmobiliario.py --dump-html    # debug: write page HTML to /tmp/pi_debug.html

Selectors last verified: 2025-04 (MeLi Polaris UI).
"""

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.scraping.base import BaseScraper, ScrapedListing, USER_AGENTS

# Items per page on Portal Inmobiliario
ITEMS_PER_PAGE = 48

TYPE_MAP = {
    "apartments": "departamento",
    "residential": "casa",
    "land":        "terreno",
    "retail":      "local-comercial",
}

# RM communes and their PI URL slugs (verified 2026-04)
# Pattern: /venta/{type}/{slug}-metropolitana
# MeLi requires login for paginated results (_Desde_N), but page 1 per commune is free.
# 40 communes × 4 types = 160 unique page-1 scrapes → up to 7,680 listings.
RM_COMMUNES = {
    "Las Condes":          "las-condes",
    "Providencia":         "providencia",
    "Santiago":            "santiago",
    "Vitacura":            "vitacura",
    "Ñuñoa":               "nunoa",
    "La Florida":          "la-florida",
    "Maipú":               "maipu",
    "Peñalolén":           "penalolen",
    "San Miguel":          "san-miguel",
    "La Reina":            "la-reina",
    "Lo Barnechea":        "lo-barnechea",
    "Macul":               "macul",
    "Pudahuel":            "pudahuel",
    "Quilicura":           "quilicura",
    "Huechuraba":          "huechuraba",
    "Recoleta":            "recoleta",
    "Independencia":       "independencia",
    "Conchalí":            "conchali",
    "Renca":               "renca",
    "Quinta Normal":       "quinta-normal",
    "Estación Central":    "estacion-central",
    "Cerrillos":           "cerrillos",
    "Lo Espejo":           "lo-espejo",
    "Pedro Aguirre Cerda": "pedro-aguirre-cerda",
    "San Ramón":           "san-ramon",
    "La Cisterna":         "la-cisterna",
    "El Bosque":           "el-bosque",
    "La Granja":           "la-granja",
    "Lo Prado":            "lo-prado",
    "Cerro Navia":         "cerro-navia",
    "Colina":              "colina",
    "Lampa":               "lampa",
    "Talagante":           "talagante",
    "Buin":                "buin",
    "Melipilla":           "melipilla",
    "San Bernardo":        "san-bernardo",
    "Puente Alto":         "puente-alto",
    "La Pintana":          "la-pintana",
    "San Joaquín":         "san-joaquin",
    "Pirque":              "pirque",
}

# MeLi Polaris UI selectors (updated 2025)
# Each is a list — tried in order, first match wins.
CONTAINER_SELECTORS = [
    "ol.ui-search-layout",          # Polaris grid layout
    "section.ui-search-main",       # Polaris main section
    ".ui-search-results",           # Legacy (pre-2024)
    ".ui-search-layout",            # Legacy fallback
]

CARD_SELECTORS = [
    ".poly-card",                   # Polaris card
    ".ui-search-layout__item",      # Polaris item wrapper
    ".ui-search-result__wrapper",   # Legacy
]

PRICE_SELECTORS = [
    ".poly-price__current .andes-money-amount__fraction",
    ".andes-money-amount__fraction",
    ".price-tag-fraction",
]

LOCATION_SELECTORS = [
    ".poly-component__location",
    ".ui-search-item__location",
    ".ui-search-result__content-location",
]

TITLE_SELECTORS = [
    ".poly-component__title",
    ".ui-search-item__title",
    "h2.poly-box",
]

SURFACE_SELECTORS = [
    "[class*='attribute']",        # Polaris: contains bedrooms/bathrooms/m² as multiline block
    "[data-surface]",
    ".poly-attributes-list__item",
    ".ui-search-attributes-list__attribute",
]


class PortalInmobiliarioScraper(BaseScraper):
    """Scraper for portalinmobiliario.com (MeLi Polaris UI, 2025)."""

    BASE_URL = "https://www.portalinmobiliario.com"
    _current_property_type: str = "unknown"   # set by _build_url for type-aware parsing

    @property
    def source_name(self) -> str:
        return "portal_inmobiliario"

    def _build_url(
        self, page_num: int, property_type: str = "apartments",
        commune_slug: str = "", **kwargs
    ) -> str:
        self._current_property_type = property_type
        pi_type = TYPE_MAP.get(property_type, "departamento")
        # Commune-filtered URL: /venta/{type}/{commune-slug}-metropolitana
        if commune_slug:
            base = f"{self.BASE_URL}/venta/{pi_type}/{commune_slug}-metropolitana"
        else:
            base = f"{self.BASE_URL}/venta/{pi_type}/region-metropolitana-metropolitana"
        offset = (page_num - 1) * ITEMS_PER_PAGE + 1
        if offset <= 1:
            return base
        return f"{base}/_Desde_{offset}_NoIndex_True"

    async def _wait_for_page(self, page) -> bool:
        """
        Wait for the page to load listings. Tries multiple selectors.
        Returns True if any container was found, False otherwise.
        """
        for selector in CONTAINER_SELECTORS:
            try:
                await page.wait_for_selector(selector, timeout=8_000)
                logger.debug(f"Container found with selector: {selector}")
                return True
            except Exception:
                continue

        # Last resort: wait for networkidle and hope content is there
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
            # Check if any card exists
            for selector in CARD_SELECTORS:
                count = await page.locator(selector).count()
                if count > 0:
                    logger.debug(f"Cards found via locator: {selector} ({count} cards)")
                    return True
        except Exception:
            pass

        return False

    async def _extract_listings(self, page, dump_html: bool = False) -> list[ScrapedListing]:
        """
        Extract listings from the Portal Inmobiliario search results page.

        Strategy (in order of reliability):
          1. JSON-LD ItemList embedded in <script> — most stable, schema.org standard
          2. window.__PRELOADED_STATE__ — MeLi SPA state object
          3. DOM cards with Polaris UI selectors
          4. DOM cards with legacy selectors
        """
        listings = []

        found = await self._wait_for_page(page)
        if not found:
            logger.warning("No listing container found — possible CAPTCHA, block, or page structure change")

        if dump_html:
            html = await page.content()
            debug_path = Path("data/exports/pi_debug.html")
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            debug_path.write_text(html[:500_000], encoding="utf-8")
            logger.info(f"[debug] HTML dumped to {debug_path}")

        # ── Strategy 1: JSON-LD ItemList ──────────────────────────────────────
        json_ld = await page.evaluate("""() => {
            const scripts = document.querySelectorAll('script[type="application/ld+json"]');
            for (const s of scripts) {
                try {
                    const d = JSON.parse(s.textContent);
                    if (d['@type'] === 'ItemList') return d;
                    if (Array.isArray(d)) {
                        const il = d.find(x => x['@type'] === 'ItemList');
                        if (il) return il;
                    }
                } catch(e) {}
            }
            return null;
        }""")

        if json_ld and "itemListElement" in json_ld:
            for item in json_ld.get("itemListElement", []):
                listing = self._parse_json_ld_item(item)
                if listing:
                    listings.append(listing)
            if listings:
                logger.debug(f"JSON-LD extracted {len(listings)} listings")
                return listings

        # ── Strategy 2: __PRELOADED_STATE__ (MeLi SPA) ───────────────────────
        preloaded = await page.evaluate("""() => {
            try { return window.__PRELOADED_STATE__ || null; } catch(e) { return null; }
        }""")
        if preloaded:
            results = self._parse_preloaded_state(preloaded)
            if results:
                logger.debug(f"__PRELOADED_STATE__ extracted {len(results)} listings")
                return results

        # ── Strategy 3: DOM scraping (Polaris + legacy selectors) ─────────────
        cards = []
        for selector in CARD_SELECTORS:
            cards = await page.query_selector_all(selector)
            if cards:
                logger.debug(f"DOM cards found with selector: {selector} ({len(cards)} cards)")
                break

        for card in cards:
            listing = await self._parse_card(card, page)
            if listing:
                listings.append(listing)

        if not listings:
            logger.warning(
                "0 listings extracted. If this persists, run with --dump-html to inspect page structure. "
                "Common causes: CAPTCHA, IP block, or updated HTML selectors."
            )

        return listings

    def _parse_preloaded_state(self, state: dict) -> list[ScrapedListing]:
        """Parse MeLi's window.__PRELOADED_STATE__ SPA data."""
        listings = []
        try:
            # Navigate common MeLi state structures
            results = (
                state.get("results") or
                state.get("initialState", {}).get("results") or
                state.get("search", {}).get("results") or
                []
            )
            for item in results:
                listing = self._parse_meli_item(item)
                if listing:
                    listings.append(listing)
        except Exception as e:
            logger.debug(f"__PRELOADED_STATE__ parse error: {e}")
        return listings

    def _parse_meli_item(self, item: dict) -> Optional[ScrapedListing]:
        """Parse a MeLi search result item dict."""
        try:
            ext_id = str(item.get("id") or "")
            if not ext_id:
                return None

            permalink = item.get("permalink") or f"{self.BASE_URL}/propiedades/{ext_id}"

            # Price
            price_uf = None
            prices = item.get("prices", {}).get("prices", []) or []
            if not prices:
                prices = [item.get("price", {})] if item.get("price") else []
            for p in prices:
                if isinstance(p, dict):
                    currency = p.get("currency_id", "")
                    amount = p.get("amount") or p.get("regular_amount")
                    if amount:
                        price_uf = self._convert_price(float(amount), currency)
                        break
            if price_uf is None and item.get("price"):
                currency = item.get("currency_id", "CLF")
                price_uf = self._convert_price(float(item["price"]), currency)

            # Location
            location = item.get("location") or item.get("seller_address") or {}
            county = (
                location.get("city", {}).get("name") or
                location.get("neighborhood", {}).get("name") or
                location.get("state", {}).get("name") or ""
            )
            lat = location.get("latitude")
            lon = location.get("longitude")
            lat = float(lat) if lat else None
            lon = float(lon) if lon else None

            # Surface from attributes
            surface_m2 = None
            for attr in item.get("attributes", []):
                if attr.get("id") in ("TOTAL_AREA", "COVERED_AREA"):
                    try:
                        surface_m2 = float(attr.get("value_struct", {}).get("number", 0) or attr.get("value_name", 0))
                        break
                    except Exception:
                        pass

            ptype = self._infer_type(item.get("title", ""), permalink)

            return ScrapedListing(
                source       = self.source_name,
                external_id  = ext_id,
                url          = permalink,
                project_type = ptype,
                county_name  = county,
                price_uf     = price_uf,
                surface_m2   = surface_m2,
                latitude     = lat,
                longitude    = lon,
                description  = item.get("title"),
                raw_json     = json.dumps(item)[:4000],
            )
        except Exception as e:
            logger.debug(f"MeLi item parse error: {e}")
            return None

    def _parse_json_ld_item(self, item: dict) -> Optional[ScrapedListing]:
        """Parse a JSON-LD ItemListElement from Portal Inmobiliario."""
        try:
            thing  = item.get("item", item)
            url    = thing.get("url", "")
            ext_id = url.split("-")[-1].replace(".html", "") if url else ""
            if not ext_id:
                return None

            offers = thing.get("offers", {})
            price  = offers.get("price")
            geo    = thing.get("geo", {})
            addr   = thing.get("address", {})

            county = addr.get("addressLocality", "") or addr.get("addressRegion", "")
            lat    = float(geo["latitude"])  if geo.get("latitude")  else None
            lon    = float(geo["longitude"]) if geo.get("longitude") else None

            currency = offers.get("priceCurrency", "UF")
            price_uf = self._convert_price(float(price), currency) if price else None

            name  = thing.get("name", "")
            ptype = self._infer_type(name, url)

            return ScrapedListing(
                source       = self.source_name,
                external_id  = ext_id,
                url          = url,
                project_type = ptype,
                county_name  = county,
                price_uf     = price_uf,
                latitude     = lat,
                longitude    = lon,
                description  = thing.get("description"),
                raw_json     = json.dumps(thing)[:4000],
            )
        except Exception as e:
            logger.debug(f"JSON-LD parse error: {e}")
            return None

    async def _parse_card(self, card, page) -> Optional[ScrapedListing]:
        """DOM scraping for a single listing card (Polaris + legacy selectors)."""
        try:
            # URL — prefer MLC property links over brand_ads tracking links
            link_el = await card.query_selector("a[href*='/MLC'], a[href*='/propiedades/']")
            if not link_el:
                link_el = await card.query_selector("a")
            url = await link_el.get_attribute("href") if link_el else ""

            # ext_id: extract MLC-XXXXXXXX from URL (strip fragment first)
            url_clean = (url or "").split("#")[0]
            mlc_match = re.search(r"MLC-?(\d+)", url_clean)
            ext_id = f"MLC-{mlc_match.group(1)}" if mlc_match else ""
            if not ext_id:
                return None

            # Price — try Polaris then legacy
            price_raw = ""
            for sel in PRICE_SELECTORS:
                price_el = await card.query_selector(sel)
                if price_el:
                    price_raw = await price_el.inner_text()
                    break

            # Currency symbol in sibling element
            currency = "CLF"
            currency_el = await card.query_selector(
                ".andes-money-amount__currency-symbol, .price-tag-symbol"
            )
            if currency_el:
                sym = (await currency_el.inner_text()).strip()
                currency = "CLP" if sym in ("$", "CLP") else "CLF"

            price_uf = None
            if price_raw:
                cleaned = price_raw.replace(".", "").replace(",", ".").strip()
                try:
                    price_uf = self._convert_price(float(cleaned), currency)
                except ValueError:
                    pass

            # Surface — from attributes block (multiline: "N dorm\nN baño\nXX m² útiles")
            surface_m2 = None
            for sel in SURFACE_SELECTORS:
                surf_els = await card.query_selector_all(sel)
                for surf_el in surf_els:
                    txt = await surf_el.inner_text()
                    if "m" in txt:
                        surface_m2 = self._parse_surface(txt)
                        if surface_m2:
                            break
                if surface_m2:
                    break

            # Bedrooms from attributes text
            bedrooms = None
            attr_el = await card.query_selector("[class*='attribute']")
            if attr_el:
                attr_txt = await attr_el.inner_text()
                bed_m = re.search(r"(\d+)\s*dormitorio", attr_txt, re.IGNORECASE)
                if bed_m:
                    bedrooms = int(bed_m.group(1))

            # Location — parts: [street, commune, neighborhood?, commune?]
            # parts[1] is the commune in MeLi Polaris format
            county = ""
            for sel in LOCATION_SELECTORS:
                loc_el = await card.query_selector(sel)
                if loc_el:
                    location = await loc_el.inner_text()
                    parts = [p.strip() for p in location.split(",") if p.strip()]
                    county = parts[1] if len(parts) > 1 else parts[0] if parts else ""
                    break

            # Title for type inference
            title = ""
            for sel in TITLE_SELECTORS:
                title_el = await card.query_selector(sel)
                if title_el:
                    title = await title_el.inner_text()
                    break

            ptype = self._infer_type(title, url)

            return ScrapedListing(
                source       = self.source_name,
                external_id  = ext_id,
                url          = f"{self.BASE_URL}{url}" if url.startswith("/") else url,
                project_type = ptype,
                county_name  = county or "unknown",
                price_uf     = price_uf,
                surface_m2   = surface_m2,
                bedrooms     = bedrooms,
            )
        except Exception as e:
            logger.debug(f"Card parse error: {e}")
            return None

    async def _dismiss_overlays(self, page) -> None:
        """Remove MeLi overlays (coach marks, cookie banner) that block clicks."""
        try:
            await page.evaluate("""() => {
                // Coach marks overlay (tutorial)
                document.querySelectorAll(
                    '[class*="coach-marks"], [id*="coach"], [class*="andes-portal"]'
                ).forEach(e => e.remove());
                // Cookie / GDPR banners
                document.querySelectorAll(
                    '[id*="cookie"], [id*="Cookie"], .nav-new-cookie-disclaimer, '
                    '[class*="cookie-disclaimer"], [id*="gdpr"]'
                ).forEach(e => e.remove());
            }""")
            await page.wait_for_timeout(300)
        except Exception:
            pass

    async def _click_next_page(self, page) -> bool:
        """
        Click the pagination 'next' button on Portal Inmobiliario.
        Direct URL navigation to _Desde_N_NoIndex_True is blocked by MeLi anti-bot;
        clicking from within an established session works.
        Returns True if the next button was found and clicked.
        """
        await self._dismiss_overlays(page)

        NEXT_SELECTORS = [
            ".andes-pagination__button--next a",
            ".andes-pagination__button--next",
            "li.andes-pagination__button--next a",
            "[aria-label='Siguiente']",
            "a[title='Siguiente']",
            "a[rel='next']",
            ".ui-search-pagination__button--next a",
        ]
        old_url = page.url
        for sel in NEXT_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el:
                    # Check it's not disabled
                    disabled = await el.get_attribute("aria-disabled")
                    cls = await el.get_attribute("class") or ""
                    if disabled == "true" or "disabled" in cls:
                        logger.debug(f"Next button found but disabled: {sel}")
                        return False
                    await el.scroll_into_view_if_needed()
                    # Click and wait for navigation to complete
                    async with page.expect_navigation(
                        wait_until="domcontentloaded", timeout=30_000
                    ):
                        await el.click(timeout=5_000)
                    await page.wait_for_timeout(3_000)
                    logger.debug(f"Navigated via click to: {page.url}")
                    return True
            except Exception as e:
                logger.debug(f"Next button click error ({sel}): {e}")
                continue
        # Last resort: extract href and navigate directly
        try:
            href = await page.evaluate("""() => {
                const selectors = [
                    '.andes-pagination__button--next a',
                    '[aria-label="Siguiente"]',
                    'a[rel="next"]'
                ];
                for (const s of selectors) {
                    const el = document.querySelector(s);
                    if (el && el.href && !el.closest('[aria-disabled="true"]')) {
                        return el.href;
                    }
                }
                return null;
            }""")
            if href and href != old_url:
                await page.goto(href, wait_until="domcontentloaded", timeout=60_000)
                await page.wait_for_timeout(3_000)
                logger.debug(f"Navigated via href to: {page.url}")
                return True
        except Exception as e:
            logger.debug(f"JS href nav error: {e}")
        return False

    async def scrape_async(
        self, max_pages: int = 50, start_page: int = 1, **url_kwargs
    ) -> int:
        """
        PI-specific scrape loop: page 1 via direct URL, pages 2+ via pagination click.
        MeLi blocks direct navigation to _Desde_N_NoIndex_True without session cookies.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError("playwright not installed. Run: pip install playwright && playwright install chromium")

        total        = 0
        empty_streak = 0
        end_page     = start_page + max_pages - 1
        worker_tag   = f"{self.source_name}|{url_kwargs.get('property_type','?')}|p{start_page}-{end_page}"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            for page_num in range(start_page, end_page + 1):
                url = self._build_url(page_num, **url_kwargs)
                logger.info(f"[{worker_tag}] Page {page_num}/{end_page}: {url}")

                try:
                    # Navigate directly — page 1 establishes session cookies; pages 2+
                    # use the same browser context so cookies are sent automatically.
                    # Direct goto with established cookies works; fresh-browser goto does not.
                    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    await page.wait_for_timeout(3_000)

                    listings = await self._extract_listings(page)

                    if not listings:
                        empty_streak += 1
                        logger.info(
                            f"[{worker_tag}] No listings on page {page_num} "
                            f"(streak: {empty_streak}). Stopping."
                        )
                        if empty_streak >= 2:
                            break
                        self._random_delay()
                        continue

                    empty_streak = 0
                    n = self._write_batch(listings)
                    total += n
                    logger.info(f"[{worker_tag}] Page {page_num}: {n} written (subtotal: {total})")

                except Exception as e:
                    logger.warning(f"[{worker_tag}] Page {page_num} error: {e}")
                    empty_streak += 1
                    if empty_streak >= 3:
                        logger.warning(f"[{worker_tag}] 3 consecutive errors, stopping.")
                        break

                self._random_delay()

            await context.close()
            await browser.close()

        return total

    def _convert_price(self, amount: float, currency: str) -> Optional[float]:
        """Convert CLP/CLF/UF amounts to UF."""
        if amount <= 0:
            return None
        if currency in ("CLF", "UF"):   # CLF = UF in ISO 4217
            return amount
        if currency == "CLP":
            uf_value = float(os.getenv("UF_VALUE_APPROX", "38000"))
            return amount / uf_value
        return amount  # assume UF

    def _infer_type(self, name: str, url: str) -> str:
        """Infer property type from name or URL; falls back to current search type."""
        text = (name + " " + url).lower()
        if "departamento" in text or "apart" in text:
            return "apartments"
        if "casa" in text or "residential" in text:
            return "residential"
        if "terreno" in text or "land" in text:
            return "land"
        if "local" in text or "retail" in text or "oficina" in text:
            return "retail"
        # Fall back to whatever type we're currently scraping
        return self._current_property_type if self._current_property_type != "unknown" else "unknown"


# ── Module run() for Prefect task ─────────────────────────────────────────────

def run(
    engine=None,
    max_pages: int = 50,
    property_types: list = None,
    by_commune: bool = False,
) -> int:
    """
    Entry point for Prefect task and CLI.

    by_commune=True: scrape page 1 for each RM commune × type combination.
    MeLi gates pagination behind login, but per-commune page-1 is free.
    40 communes × 4 types = 160 requests → up to ~7,680 unique listings.
    """
    if property_types is None:
        property_types = list(TYPE_MAP.keys())

    total = 0
    if by_commune:
        communes = list(RM_COMMUNES.items())  # [(name, slug), ...]
        for ptype in property_types:
            for cname, cslug in communes:
                logger.info(f"[portal_inmobiliario] Commune {cname} / {ptype}")
                scraper = PortalInmobiliarioScraper(engine=engine)
                n = scraper.run(max_pages=1, property_type=ptype, commune_slug=cslug)
                total += n
                if n:
                    logger.info(f"[portal_inmobiliario] {cname}/{ptype}: {n} listings")
    else:
        for ptype in property_types:
            logger.info(f"[portal_inmobiliario] Scraping type: {ptype}")
            scraper = PortalInmobiliarioScraper(engine=engine)
            n = scraper.run(max_pages=max_pages, property_type=ptype)
            total += n
            logger.info(f"[portal_inmobiliario] {ptype}: {n} listings scraped")

    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--type", choices=list(TYPE_MAP.keys()), default=None)
    parser.add_argument("--by-commune", action="store_true",
                        help="Scrape page 1 per commune (bypasses MeLi login gate on pagination)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dump-html", action="store_true",
                        help="Save page HTML to data/exports/pi_debug.html for selector debugging")
    args = parser.parse_args()

    if args.dry_run:
        logger.info("[DRY RUN] Would scrape Portal Inmobiliario. No actual requests.")
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

    # If dump-html, scrape only 1 page of 1 type for inspection
    if args.dump_html:
        import asyncio
        from playwright.async_api import async_playwright
        import random
        from src.scraping.base import USER_AGENTS

        async def _dump():
            scraper = PortalInmobiliarioScraper(engine=eng)
            ptype = types[0]
            url = scraper._build_url(1, property_type=ptype)
            logger.info(f"Loading {url} for HTML inspection...")
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                await page.wait_for_timeout(3000)  # let JS render
                listings = await scraper._extract_listings(page, dump_html=True)
                logger.info(f"Extracted {len(listings)} listings from debug page")
                await browser.close()

        asyncio.run(_dump())
        sys.exit(0)

    total = run(
        engine=eng,
        max_pages=args.max_pages,
        property_types=types,
        by_commune=args.by_commune,
    )
    logger.info(f"Total scraped: {total:,} listings")
