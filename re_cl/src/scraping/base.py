"""
base.py
-------
Abstract base scraper for real estate portals.

Provides:
  - Playwright browser lifecycle management
  - Rate limiting (configurable min/max delay between requests)
  - User-agent rotation
  - Retry logic
  - DB write interface (scraped_listings table)
  - Coordinate validation

Concrete scrapers (portal_inmobiliario.py, toctoc.py) inherit from BaseScraper
and implement: _extract_listings(page) and _build_url(page_num, **kwargs).
"""

import asyncio
import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger
from sqlalchemy import text
from sqlalchemy.engine import Engine

# Chile RM bounding box
RM_LAT = (-33.70, -33.25)
RM_LON = (-71.00, -70.40)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


@dataclass
class ScrapedListing:
    """Normalized listing extracted from any portal."""
    source:          str
    external_id:     str
    url:             str
    project_type:    str          # apartments, residential, land, retail
    county_name:     str
    address:         Optional[str]   = None
    price_uf:        Optional[float] = None
    surface_m2:      Optional[float] = None
    uf_m2:           Optional[float] = None
    bedrooms:        Optional[int]   = None
    bathrooms:       Optional[int]   = None
    latitude:        Optional[float] = None
    longitude:       Optional[float] = None
    description:     Optional[str]   = None
    scraped_at:      datetime        = field(default_factory=datetime.utcnow)
    raw_json:        Optional[str]   = None


class BaseScraper(ABC):
    """
    Abstract real estate portal scraper.
    Subclasses implement _build_url() and _extract_listings().
    """

    def __init__(
        self,
        engine: Engine,
        min_delay: float = 2.0,
        max_delay: float = 5.0,
        headless: bool = True,
    ):
        self.engine    = engine
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.headless  = headless
        self._listings_buffer: list[ScrapedListing] = []

    # ── Abstract interface ────────────────────────────────────────────────────

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Short name of the portal (e.g. 'portal_inmobiliario')."""

    @abstractmethod
    def _build_url(self, page_num: int, **kwargs) -> str:
        """Build the URL for a given page number and filters."""

    @abstractmethod
    async def _extract_listings(self, page) -> list[ScrapedListing]:
        """
        Extract listings from the current Playwright page.
        Returns list of ScrapedListing objects.
        """

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _validate_coords(self, lat, lon) -> bool:
        if lat is None or lon is None:
            return False
        return (RM_LAT[0] <= lat <= RM_LAT[1]) and (RM_LON[0] <= lon <= RM_LON[1])

    def _parse_uf(self, raw: str) -> Optional[float]:
        """Parse price string to UF float. Returns None if not parseable."""
        if not raw:
            return None
        cleaned = raw.upper().replace("UF", "").replace(".", "").replace(",", ".").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _parse_surface(self, raw: str) -> Optional[float]:
        """Parse surface m² from text. Handles ranges ('23 - 38 m²'), multiline blocks, and plain numbers."""
        if not raw:
            return None
        # Find all numbers preceding m² (handles "23 - 38 m² útiles", "45 m²", "45.5m2")
        matches = re.findall(r"(\d[\d\.,]*)\s*(?:-\s*(\d[\d\.,]*))?\s*m[²2²]", raw, re.IGNORECASE)
        if matches:
            try:
                lo = float(matches[0][0].replace(".", "").replace(",", "."))
                hi_str = matches[0][1]
                if hi_str:
                    hi = float(hi_str.replace(".", "").replace(",", "."))
                    return (lo + hi) / 2  # midpoint of range
                return lo
            except (ValueError, IndexError):
                pass
        # Fallback: strip m² and try plain float
        cleaned = re.sub(r"[^\d\.,]", " ", raw).strip()
        first_num = re.search(r"\d[\d\.]*", cleaned)
        if first_num:
            try:
                return float(first_num.group().replace(",", "."))
            except ValueError:
                pass
        return None

    def _random_delay(self):
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    # ── DB write ──────────────────────────────────────────────────────────────

    def _write_batch(self, listings: list[ScrapedListing]) -> int:
        """Write a batch of listings to scraped_listings table. Upserts by (source, external_id)."""
        if not listings:
            return 0

        import json
        rows = []
        for l in listings:
            rows.append({
                "source":       l.source,
                "external_id":  l.external_id,
                "url":          l.url,
                "project_type": l.project_type,
                "county_name":  l.county_name,
                "address":      l.address,
                "price_uf":     l.price_uf,
                "surface_m2":   l.surface_m2,
                "uf_m2":        l.uf_m2 or (l.price_uf / l.surface_m2 if l.price_uf and l.surface_m2 and l.surface_m2 > 0 else None),
                "bedrooms":     l.bedrooms,
                "bathrooms":    l.bathrooms,
                "latitude":     l.latitude if self._validate_coords(l.latitude, l.longitude) else None,
                "longitude":    l.longitude if self._validate_coords(l.latitude, l.longitude) else None,
                "description":  l.description,
                "scraped_at":   l.scraped_at,
                "raw_json":     l.raw_json,
            })

        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO scraped_listings
                    (source, external_id, url, project_type, county_name, address,
                     price_uf, surface_m2, uf_m2, bedrooms, bathrooms,
                     latitude, longitude, description, scraped_at, raw_json)
                VALUES
                    (:source, :external_id, :url, :project_type, :county_name, :address,
                     :price_uf, :surface_m2, :uf_m2, :bedrooms, :bathrooms,
                     :latitude, :longitude, :description, :scraped_at, :raw_json)
                ON CONFLICT (source, external_id) DO UPDATE SET
                    price_uf    = EXCLUDED.price_uf,
                    surface_m2  = EXCLUDED.surface_m2,
                    uf_m2       = EXCLUDED.uf_m2,
                    latitude    = EXCLUDED.latitude,
                    longitude   = EXCLUDED.longitude,
                    scraped_at  = EXCLUDED.scraped_at,
                    raw_json    = EXCLUDED.raw_json
            """), rows)

        return len(rows)

    # ── Main scrape loop ──────────────────────────────────────────────────────

    async def scrape_async(
        self, max_pages: int = 50, start_page: int = 1, **url_kwargs
    ) -> int:
        """
        Async scrape loop. Returns total listings written.

        Parameters
        ----------
        max_pages : int
            Number of pages to scrape (not the ending page number).
        start_page : int
            Page number to start from. Enables parallel workers splitting
            a page range (e.g. worker A: start=1 max=50, worker B: start=51 max=50).
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError("playwright not installed. Run: pip install playwright && playwright install chromium")

        total        = 0
        empty_streak = 0  # consecutive empty pages before giving up
        end_page     = start_page + max_pages - 1
        worker_tag   = f"{self.source_name}|{url_kwargs.get('property_type','?')}|p{start_page}-{end_page}"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)

            # Rotate user-agent per page via fresh context every 10 pages (anti-bot)
            ctx_page_count = 0
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            for page_num in range(start_page, end_page + 1):
                # Rotate context every 10 pages to avoid session-based blocking
                if ctx_page_count >= 10:
                    await context.close()
                    context = await browser.new_context(
                        user_agent=random.choice(USER_AGENTS),
                        viewport={"width": 1280, "height": 800},
                    )
                    page = await context.new_page()
                    ctx_page_count = 0
                    logger.debug(f"[{worker_tag}] Context rotated at page {page_num}")

                url = self._build_url(page_num, **url_kwargs)
                logger.info(f"[{worker_tag}] Page {page_num}/{end_page}: {url}")

                try:
                    # domcontentloaded + explicit wait is more reliable than networkidle
                    # for SPAs (MeLi Polaris) and Next.js portals that keep background XHR alive
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
                    ctx_page_count += 1
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

    def run(self, max_pages: int = 50, start_page: int = 1, **url_kwargs) -> int:
        """Synchronous entrypoint — runs the async scrape loop."""
        return asyncio.run(
            self.scrape_async(max_pages=max_pages, start_page=start_page, **url_kwargs)
        )
