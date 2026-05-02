"""
run_di_warp_loop.py — Loop automatico WARP + scrape

Estrategia: reconecta WARP repetidamente para forzar IPs distintas del pool de Cloudflare,
scrapea hasta que ya no encuentre IP fresca o complete todas las comunas.

Limites de seguridad:
  - Max 10 reconexiones por sesion (evita rate limit de WARP)
  - Cooldown 30s entre reconexiones (no abusar de Cloudflare)
  - Detiene si misma IP se repite 3 veces consecutivas
  - Detiene si scrape no avanza (0 rows nuevos en 2 rondas)

Run:
  py scripts/run_di_warp_loop.py
  py scripts/run_di_warp_loop.py --max-rounds 5
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine

load_dotenv()

WARP_PATHS = [
    r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe",
    r"C:\Program Files (x86)\Cloudflare\Cloudflare WARP\warp-cli.exe",
    "warp-cli",
]

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
LOG_DIR = Path(__file__).resolve().parents[1] / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def find_warp() -> str:
    for p in WARP_PATHS:
        try:
            r = subprocess.run([p, "--version"], capture_output=True, timeout=3)
            if r.returncode == 0:
                return p
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
    return ""


def warp_reconnect(warp_cli: str) -> str | None:
    """Disconnect+connect WARP. Returns new public IP or None."""
    try:
        subprocess.run([warp_cli, "disconnect"], capture_output=True, timeout=10)
        time.sleep(4)
        subprocess.run([warp_cli, "connect"], capture_output=True, timeout=15)
        time.sleep(6)
        # Get IP
        r = requests.get("https://api.ipify.org?format=json", timeout=10)
        if r.status_code == 200:
            return r.json().get("ip")
    except Exception as e:
        logger.warning(f"  WARP reconnect error: {e}")
    return None


async def quick_quota_check(cookie_file: Path) -> int:
    """Returns HTTP status (200=ok, 402=exhausted)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
            )
            cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
            await context.add_cookies(cookies)
            page = await context.new_page()
            await page.goto("https://datainmobiliaria.cl/reports/busqueda_poligono",
                            wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            test_body = json.dumps({
                "polygon": [{"lat": -33.47, "lng": -70.68}, {"lat": -33.47, "lng": -70.63},
                            {"lat": -33.42, "lng": -70.63}, {"lat": -33.42, "lng": -70.68}],
                "fuente": "ventas", "page": 1
            })
            result = await page.evaluate(f'''async () => {{
                const r = await fetch('/reports/busqueda_poligono_data', {{
                    method: 'POST',
                    headers: {{'Content-Type':'application/json','Accept':'application/json',
                               'X-CSRF-Token': document.querySelector('meta[name=csrf-token]')?.content||''}},
                    body: JSON.stringify({test_body})
                }});
                return {{status: r.status}};
            }}''')
            return int(result.get("status", 0))
        finally:
            await browser.close()


def discover_accounts() -> list[Path]:
    files = []
    default = DATA_DIR / "datainmobiliaria_cookies.json"
    if default.exists():
        files.append(default)
    for f in sorted(DATA_DIR.glob("di_cookies_*.json")):
        if f not in files:
            files.append(f)
    return files


def _build_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    return "postgresql://{user}:{pwd}@{host}:{port}/{db}".format(
        user=os.getenv("POSTGRES_USER", "re_cl_user"),
        pwd=os.getenv("POSTGRES_PASSWORD", ""),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        db=os.getenv("POSTGRES_DB", "re_cl"),
    )


async def scrape_round(accounts: list[Path]) -> int:
    """Scrape with all accounts in rotation. Returns rows written."""
    from src.scraping.datainmobiliaria import scrape_all
    from scripts.run_di_bulk_multi import _pending_communes_sorted

    pending = _pending_communes_sorted()
    if not pending:
        return 0

    primary = accounts[0]
    extras = accounts[1:] if len(accounts) > 1 else []
    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    return await scrape_all(
        engine, communes=pending, fuente="ventas", dry_run=False,
        max_pages=100, min_year=2019, headless=True, use_checkpoint=True,
        cookie_file=primary, extra_cookie_files=extras,
    )


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-rounds", type=int, default=8)
    parser.add_argument("--cooldown", type=int, default=30)
    args = parser.parse_args()

    log_file = LOG_DIR / "di_warp_loop.log"
    logger.add(log_file, rotation="10 MB")

    logger.info("=" * 60)
    logger.info("DI WARP LOOP — auto reconnect + scrape")
    logger.info("=" * 60)

    warp_cli = find_warp()
    if not warp_cli:
        logger.error("Cloudflare WARP not found. Install from https://1.1.1.1")
        sys.exit(1)
    logger.info(f"WARP CLI: {warp_cli}")

    accounts = discover_accounts()
    if not accounts:
        logger.error("No cookie files found")
        sys.exit(1)
    logger.info(f"Accounts: {len(accounts)}")

    seen_ips: dict[str, int] = {}  # IP → exhausted count
    total_rows = 0
    total_communes_at_start = 0

    # Get baseline checkpoint count
    try:
        cp_path = DATA_DIR / "datainmobiliaria_checkpoint.json"
        cp = json.loads(cp_path.read_text(encoding="utf-8"))
        total_communes_at_start = sum(1 for v in cp.values() if not v.get("partial"))
    except Exception:
        pass
    logger.info(f"Communes complete at start: {total_communes_at_start}/40")

    consecutive_exhausted = 0
    repeat_ip_count = 0

    for round_num in range(1, args.max_rounds + 1):
        logger.info("")
        logger.info(f"{'=' * 30} Round {round_num}/{args.max_rounds} {'=' * 30}")

        # Reconnect WARP
        ip = warp_reconnect(warp_cli)
        if not ip:
            logger.warning("Could not get new IP. Stopping.")
            break
        logger.info(f"WARP IP: {ip}")

        if ip in seen_ips:
            seen_ips[ip] += 1
            logger.warning(f"  IP {ip} already seen ({seen_ips[ip]} times)")
            if seen_ips[ip] >= 3:
                logger.warning("Same IP repeated 3 times — WARP pool exhausted. Stopping.")
                break
            repeat_ip_count += 1
            if repeat_ip_count >= 3:
                logger.warning("3 repeat IPs in a row — pool too small. Stopping.")
                break
            continue
        seen_ips[ip] = 0
        repeat_ip_count = 0

        # Quick quota check on first account
        status = await quick_quota_check(accounts[0])
        logger.info(f"Quota check (account 1): HTTP {status}")
        if status != 200:
            logger.warning(f"  IP exhausted on account 1 — skipping")
            seen_ips[ip] += 1
            consecutive_exhausted += 1
            if consecutive_exhausted >= 3:
                logger.warning("3 consecutive exhausted IPs. Stopping.")
                break
            continue
        consecutive_exhausted = 0

        # Scrape
        logger.info("Scraping...")
        rows = await scrape_round(accounts)
        logger.info(f"Round {round_num} written: {rows:,} rows")
        total_rows += rows

        if rows == 0:
            logger.info("No new rows — likely all pending communes failed. Stopping.")
            break

        # Cooldown before next round
        logger.info(f"Cooldown {args.cooldown}s...")
        time.sleep(args.cooldown)

    # Final state
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"DONE — total rows: {total_rows:,} across {round_num} rounds")

    # Final commune count
    try:
        cp = json.loads((DATA_DIR / "datainmobiliaria_checkpoint.json").read_text(encoding="utf-8"))
        complete_now = sum(1 for v in cp.values() if not v.get("partial"))
        logger.info(f"Communes complete: {total_communes_at_start} → {complete_now}/40 (+{complete_now - total_communes_at_start})")
    except Exception:
        pass

    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
