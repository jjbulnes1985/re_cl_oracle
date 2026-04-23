"""
yapo.py
-------
Scraper for Yapo.cl real estate listings (Región Metropolitana).

Yapo renders server-side HTML with listings in structured divs.
Uses Playwright for JavaScript rendering.

URL pattern: https://www.yapo.cl/region_metropolitana/inmuebles?ca=15&l=0&cpa=1&pag=N
  ca=15  → Real estate category
  l=0    → All RM
  cpa=1  → For sale (not rent)
  pag=N  → Page number

Expected: 3,000-5,000 listings across all RM

Usage:
    py src/scraping/yapo.py
    py src/scraping/yapo.py --max-pages 50
    py src/scraping/yapo.py --type departamentos
    py src/scraping/yapo.py --dry-run
    py src/scraping/yapo.py --dump-html
"""

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from loguru import logger

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.scraping.base import BaseScraper, ScrapedListing

# Yapo category IDs for real estate types
YAPO_CATEGORIES = {
    "apartments":  {"ca": "15_1097", "label": "Departamentos"},
    "residential": {"ca": "15_1098", "label": "Casas"},
    "land":        {"ca": "15_1099", "label": "Terrenos"},
    "commercial":  {"ca": "15_1100", "label": "Locales/Oficinas"},
}

BASE_URL = "https://www.yapo.cl"
ITEMS_PER_PAGE = 20


class YapoScraper(BaseScraper):
    SOURCE = "yapo"

    @property
    def source_name(self) -> str:
        return self.SOURCE

    def __init__(self, engine=None, property_type: str = "apartments"):
        super().__init__(engine=engine)
        self.property_type = property_type
        self._cat_info = YAPO_CATEGORIES.get(property_type, YAPO_CATEGORIES["apartments"])

    def _build_url(self, page_num: int, **kwargs) -> str:
        ca = self._cat_info["ca"]
        return f"{BASE_URL}/region_metropolitana/inmuebles?ca={ca}&l=0&cpa=1&pag={page_num}"

    async def _extract_listings(self, page) -> List[ScrapedListing]:
        listings = []

        # Wait for Yapo's jQuery AJAX to populate #currentlistings
        try:
            await page.wait_for_selector(
                "#currentlistings li.item-list, #currentlistings article",
                timeout=12_000,
            )
        except Exception:
            pass  # Will attempt extraction anyway — may return empty

        # Try JSON-LD structured data first
        json_listings = await self._extract_json_ld(page)
        if json_listings:
            return json_listings

        # Fall back to HTML parsing
        html_listings = await self._extract_html(page)
        return html_listings

    async def _extract_json_ld(self, page) -> List[ScrapedListing]:
        """Try to extract from JSON-LD or window.__NEXT_DATA__."""
        try:
            data = await page.evaluate("""
                () => {
                    // Try NEXT_DATA
                    if (window.__NEXT_DATA__) return JSON.stringify(window.__NEXT_DATA__);
                    // Try JSON-LD scripts
                    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                    for (const s of scripts) {
                        try { const d = JSON.parse(s.textContent); if (d['@type'] === 'ItemList') return JSON.stringify(d); }
                        catch {}
                    }
                    return null;
                }
            """)
            if not data:
                return []

            import json
            parsed = json.loads(data)

            # Handle NEXT_DATA format
            items = []
            if isinstance(parsed, dict):
                # Try to navigate to listing items
                props = parsed.get("props", {}).get("pageProps", {})
                raw_ads = (
                    props.get("ads", []) or
                    props.get("listings", []) or
                    props.get("items", []) or
                    parsed.get("itemListElement", [])
                )
                items = raw_ads if isinstance(raw_ads, list) else []

            listings = []
            for item in items[:ITEMS_PER_PAGE]:
                listing = self._parse_json_item(item)
                if listing:
                    listings.append(listing)
            return listings

        except Exception as e:
            logger.debug(f"JSON-LD extraction failed: {e}")
            return []

    def _parse_json_item(self, item: dict) -> Optional[ScrapedListing]:
        """Parse a single item from JSON data."""
        try:
            # Try various key names
            ext_id = str(
                item.get("id") or item.get("adId") or item.get("listingId") or ""
            )
            if not ext_id:
                return None

            price_raw = (
                item.get("price") or
                item.get("priceValue") or
                item.get("offers", {}).get("price") if isinstance(item.get("offers"), dict) else None
            )
            price_clp = None
            price_uf = None
            if price_raw:
                try:
                    price_clp = float(str(price_raw).replace(".", "").replace(",", ""))
                    uf_val = float(os.getenv("UF_VALUE_APPROX", "37000"))
                    price_uf = price_clp / uf_val
                except ValueError:
                    pass

            surface = None
            for key in ["surface", "surfaceTotal", "area", "squareMeters"]:
                if key in item:
                    try:
                        surface = float(item[key])
                        break
                    except (ValueError, TypeError):
                        pass

            county = (
                item.get("commune") or item.get("county") or
                item.get("location", {}).get("commune") if isinstance(item.get("location"), dict) else None or
                ""
            )
            lat = item.get("latitude") or (item.get("location", {}).get("lat") if isinstance(item.get("location"), dict) else None)
            lon = item.get("longitude") or (item.get("location", {}).get("lng") if isinstance(item.get("location"), dict) else None)

            uf_m2 = None
            if price_uf and surface and surface > 0:
                uf_m2 = price_uf / surface

            import json as _json
            return ScrapedListing(
                source=self.SOURCE,
                external_id=ext_id,
                project_type=self.property_type,
                county_name=str(county) if county else None,
                price_uf=price_uf,
                surface_m2=surface,
                uf_m2=uf_m2,
                latitude=float(lat) if lat else None,
                longitude=float(lon) if lon else None,
                url=f"{BASE_URL}/aviso/{ext_id}",
                raw_json=_json.dumps(item, ensure_ascii=False)[:4000] if item else None,
            )
        except Exception as e:
            logger.debug(f"Failed parsing JSON item: {e}")
            return None

    async def _extract_html(self, page) -> List[ScrapedListing]:
        """Extract listings from Yapo HTML structure."""
        listings = []
        try:
            # Yapo listing cards
            cards = await page.query_selector_all(
                "li.item-list, article.ad-item, div[class*='listing-card'], div[class*='item']"
            )

            if not cards:
                # Try to detect anti-bot / captcha page
                body_text = await page.inner_text("body")
                if "captcha" in body_text.lower() or "robot" in body_text.lower():
                    logger.warning("  Captcha detected on Yapo")
                return []

            for card in cards:
                listing = await self._parse_html_card(card)
                if listing:
                    listings.append(listing)

        except Exception as e:
            logger.debug(f"HTML extraction error: {e}")

        return listings

    async def _parse_html_card(self, card) -> Optional[ScrapedListing]:
        """Parse a single listing card element."""
        try:
            # ID from link
            link_el = await card.query_selector("a[href*='/aviso/']")
            href = await link_el.get_attribute("href") if link_el else ""
            ext_id_match = re.search(r"/aviso/(\d+)", href or "")
            if not ext_id_match:
                return None
            ext_id = ext_id_match.group(1)

            # Price
            price_el = await card.query_selector(
                "[class*='price'], [class*='precio'], [class*='value']"
            )
            price_text = await price_el.inner_text() if price_el else ""
            price_uf = self._parse_price_uf(price_text)

            # Surface
            surface_el = await card.query_selector(
                "[class*='surface'], [class*='area'], [class*='m2'], [class*='metros']"
            )
            surface_text = await surface_el.inner_text() if surface_el else ""
            surface = self._parse_surface(surface_text)

            # Location
            loc_el = await card.query_selector(
                "[class*='location'], [class*='commune'], [class*='comuna'], [class*='ciudad']"
            )
            county = await loc_el.inner_text() if loc_el else ""
            county = county.strip().split(",")[0].strip()

            uf_m2 = None
            if price_uf and surface and surface > 0:
                uf_m2 = price_uf / surface

            return ScrapedListing(
                source=self.SOURCE,
                external_id=ext_id,
                project_type=self.property_type,
                county_name=county if county else None,
                price_uf=price_uf,
                surface_m2=surface,
                uf_m2=uf_m2,
                latitude=None,
                longitude=None,
                url=f"{BASE_URL}{href}" if href.startswith("/") else href,
                raw_json=None,
            )
        except Exception as e:
            logger.debug(f"Failed parsing Yapo card: {e}")
            return None

    def _parse_price_uf(self, text: str) -> Optional[float]:
        """Parse price text → UF float."""
        if not text:
            return None
        text = text.replace("\xa0", " ").strip()

        # Direct UF price
        uf_match = re.search(r"UF\s*([\d.,]+)", text, re.IGNORECASE)
        if uf_match:
            try:
                return float(uf_match.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                pass

        # CLP price → convert to UF
        clp_match = re.search(r"\$\s*([\d.,]+)", text)
        if clp_match:
            try:
                clp = float(clp_match.group(1).replace(".", "").replace(",", ""))
                uf_val = float(os.getenv("UF_VALUE_APPROX", "37000"))
                return clp / uf_val
            except ValueError:
                pass

        return None

    def _parse_surface(self, text: str) -> Optional[float]:
        """Parse surface text → m² float."""
        if not text:
            return None
        match = re.search(r"([\d.,]+)\s*m", text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1).replace(",", "."))
            except ValueError:
                pass
        return None

    def run(self, max_pages: int = 50, **kwargs) -> int:
        return asyncio.run(
            self.scrape_async(
                max_pages=max_pages,
                start_page=1,
                property_type=self.property_type,
            )
        )


def run(engine=None, max_pages: int = 50, property_types: list = None) -> int:
    if property_types is None:
        property_types = list(YAPO_CATEGORIES.keys())

    total = 0
    for ptype in property_types:
        logger.info(f"Yapo: scraping {ptype} (max_pages={max_pages})")
        scraper = YapoScraper(engine=engine, property_type=ptype)
        n = scraper.run(max_pages=max_pages)
        total += n
        logger.info(f"  {ptype}: {n:,} listings written")

    logger.info(f"Yapo total: {total:,} listings")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages",  type=int, default=50)
    parser.add_argument("--type",       default=None,
                        choices=list(YAPO_CATEGORIES.keys()),
                        help="Property type (default: all)")
    parser.add_argument("--dry-run",    action="store_true")
    parser.add_argument("--dump-html",  action="store_true",
                        help="Print first page HTML and exit (debug)")
    args = parser.parse_args()

    from sqlalchemy import create_engine as _ce

    def _build_db_url():
        url = os.getenv("DATABASE_URL")
        if url: return url
        return f"postgresql://{os.getenv('POSTGRES_USER','re_cl_user')}:{os.getenv('POSTGRES_PASSWORD','')}@{os.getenv('POSTGRES_HOST','localhost')}:{os.getenv('POSTGRES_PORT','5432')}/{os.getenv('POSTGRES_DB','re_cl')}"

    if args.dump_html:
        async def _dump():
            import playwright.async_api as pw
            async with pw.async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                url = f"https://www.yapo.cl/region_metropolitana/inmuebles?ca=15&l=0&cpa=1&pag=1"
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                print(await page.content())
                await browser.close()
        asyncio.run(_dump())
        sys.exit(0)

    engine = _ce(_build_db_url(), pool_pre_ping=True) if not args.dry_run else None
    ptypes = [args.type] if args.type else list(YAPO_CATEGORIES.keys())
    run(engine=engine, max_pages=args.max_pages, property_types=ptypes)
