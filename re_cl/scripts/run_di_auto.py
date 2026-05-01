"""
run_di_auto.py — auto-orchestrator de scraping DI con rotación de IP automática

Pipeline en cascada:
  1. Probar quota con IP actual + cuenta 1
  2. Si OK → scrapear hasta agotar
  3. Si quota agotada en TODAS las cuentas:
     a) Intentar Cloudflare WARP (si está instalado y activo)
     b) Sugerir tethering / reset módem / Oracle Cloud
     c) Esperar hasta 06:00 día siguiente

Uso:
  py scripts/run_di_auto.py                 # auto-detect, scrape lo que pueda
  py scripts/run_di_auto.py --max-comunas 5 # limita a 5 comunas
  py scripts/run_di_auto.py --check-only    # solo reporta estado actual

El script registra en data/logs/di_auto.log toda la actividad.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine

load_dotenv()

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
LOG_DIR = Path(__file__).resolve().parents[1] / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_COOKIE = DATA_DIR / "datainmobiliaria_cookies.json"


def get_public_ip() -> str | None:
    """Get current public IP via multiple endpoints (fallback chain)."""
    for url in ["https://ifconfig.me/ip", "https://api.ipify.org", "https://icanhazip.com"]:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                ip = r.text.strip()
                if ip and "." in ip:
                    return ip
        except Exception:
            continue
    return None


def discover_accounts() -> list[Path]:
    """Find all DI cookie files: default + di_cookies_*.json"""
    files = []
    if DEFAULT_COOKIE.exists():
        files.append(DEFAULT_COOKIE)
    extras = sorted(DATA_DIR.glob("di_cookies_*.json"))
    for f in extras:
        if f not in files:
            files.append(f)
    return files


async def quick_quota_check(cookie_file: Path) -> dict:
    """Verifica quota de una cuenta sin scrapear. Retorna {status, http_code}."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        try:
            cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
            await context.add_cookies(cookies)
        except Exception as e:
            await browser.close()
            return {"status": "cookie_error", "error": str(e)}

        page = await context.new_page()
        try:
            await page.goto("https://datainmobiliaria.cl/reports/busqueda_poligono",
                            wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            test_body = json.dumps({
                "polygon": [
                    {"lat": -33.47, "lng": -70.68},
                    {"lat": -33.47, "lng": -70.63},
                    {"lat": -33.42, "lng": -70.63},
                    {"lat": -33.42, "lng": -70.68}
                ],
                "fuente": "ventas", "page": 1
            })
            result = await page.evaluate(f'''async () => {{
                const r = await fetch('/reports/busqueda_poligono_data', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'X-CSRF-Token': document.querySelector('meta[name=csrf-token]')?.content || ''
                    }},
                    body: JSON.stringify({test_body})
                }});
                return {{status: r.status}};
            }}''')

            status_code = result.get("status", 0)
            return {
                "status": "ok" if status_code == 200 else "exhausted" if status_code == 402 else "unknown",
                "http_code": status_code,
                "cookie_file": cookie_file.name,
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "cookie_file": cookie_file.name}
        finally:
            await browser.close()


def cloudflare_warp_status() -> str:
    """Detecta si Cloudflare WARP está instalado/activo en Windows."""
    try:
        result = subprocess.run(
            ["warp-cli", "status"],
            capture_output=True, text=True, timeout=5
        )
        out = (result.stdout or "") + (result.stderr or "")
        if "Connected" in out:
            return "connected"
        if "Disconnected" in out:
            return "installed_disconnected"
        return "unknown"
    except FileNotFoundError:
        return "not_installed"
    except Exception:
        return "error"


def cloudflare_warp_connect() -> bool:
    """Intenta conectar Cloudflare WARP automáticamente."""
    try:
        subprocess.run(["warp-cli", "connect"], timeout=15, capture_output=True)
        time.sleep(3)
        return cloudflare_warp_status() == "connected"
    except Exception:
        return False


def cloudflare_warp_disconnect():
    try:
        subprocess.run(["warp-cli", "disconnect"], timeout=10, capture_output=True)
    except Exception:
        pass


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


async def scrape_with_account(cookie_file: Path, max_comunas: int | None) -> int:
    """Lanza el scraper bulk con una cuenta específica."""
    from src.scraping.datainmobiliaria import scrape_all, RM_COMMUNE_POLYGONS
    from scripts.run_di_bulk_multi import _load_checkpoint, _pending_communes_sorted

    pending = _pending_communes_sorted()
    if max_comunas:
        pending = pending[:max_comunas]

    if not pending:
        logger.info("All communes already scraped per checkpoint")
        return 0

    logger.info(f"  Scraping {len(pending)} pending comunas with cookie {cookie_file.name}")

    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    total = await scrape_all(
        engine,
        communes=pending,
        fuente="ventas",
        dry_run=False,
        max_pages=100,
        min_year=2019,
        headless=True,
        use_checkpoint=True,
        cookie_file=cookie_file,
    )

    return total


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-comunas", type=int, default=None)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--no-warp", action="store_true", help="No intentar Cloudflare WARP")
    args = parser.parse_args()

    log_file = LOG_DIR / "di_auto.log"
    logger.add(log_file, rotation="10 MB")

    logger.info("=" * 60)
    logger.info(f"DI AUTO-ORCHESTRATOR · {datetime.now().isoformat()}")
    logger.info("=" * 60)

    # Step 1: detectar IP actual
    initial_ip = get_public_ip()
    logger.info(f"Public IP: {initial_ip or 'unknown'}")

    # Step 2: descubrir cuentas
    accounts = discover_accounts()
    logger.info(f"Accounts: {len(accounts)} configured")
    for a in accounts:
        logger.info(f"  - {a.name}")

    if not accounts:
        logger.error("No cookie files found. Run di_setup_accounts.py first.")
        sys.exit(1)

    # Step 3: probar quota en cada cuenta
    logger.info("")
    logger.info("Step 3: checking quota per account...")
    quota_status = []
    for cookie_file in accounts:
        result = await quick_quota_check(cookie_file)
        logger.info(f"  {cookie_file.name}: {result['status']} (HTTP {result.get('http_code')})")
        quota_status.append((cookie_file, result))

    available = [(f, s) for f, s in quota_status if s.get("status") == "ok"]

    if args.check_only:
        logger.info("")
        logger.info(f"Available accounts: {len(available)}/{len(accounts)}")
        return

    # Step 4: si hay quota, scrapear
    if available:
        logger.info("")
        logger.info(f"Step 4: scraping with {len(available)} available account(s)...")
        cookie_file, _ = available[0]
        total = await scrape_with_account(cookie_file, args.max_comunas)
        logger.info(f"Scraped {total:,} rows total.")
        return

    # Step 5: todas agotadas → intentar Cloudflare WARP
    logger.warning("All accounts exhausted with current IP.")

    if not args.no_warp:
        warp_state = cloudflare_warp_status()
        logger.info(f"Cloudflare WARP status: {warp_state}")

        if warp_state == "installed_disconnected":
            logger.info("Attempting WARP connect...")
            if cloudflare_warp_connect():
                new_ip = get_public_ip()
                logger.info(f"WARP connected. New IP: {new_ip}")

                # Re-test quota
                cookie_file = accounts[0]
                result = await quick_quota_check(cookie_file)
                if result.get("status") == "ok":
                    logger.info("WARP IP has fresh quota. Scraping...")
                    total = await scrape_with_account(cookie_file, args.max_comunas)
                    logger.info(f"Scraped {total:,} rows via WARP.")
                    cloudflare_warp_disconnect()
                    return
                else:
                    logger.warning(f"WARP IP also exhausted ({result.get('http_code')}). Disconnecting.")
                    cloudflare_warp_disconnect()
            else:
                logger.warning("WARP connect failed.")
        elif warp_state == "not_installed":
            logger.info("WARP not installed. Install: https://1.1.1.1/")

    # Step 6: sugerir alternativas manuales
    logger.info("")
    logger.info("=" * 60)
    logger.info("ALL IPs EXHAUSTED. Suggestions:")
    logger.info("  1. Tethering del celular (5 min): activar punto de acceso, conectar PC al WiFi del cel")
    logger.info("  2. Reset módem (2 min): apagar router 2 min, encender, esperar IP nueva")
    logger.info("  3. Oracle Cloud (60 min setup, después automático): ver prompts/vpn_free_alternatives.md")
    logger.info("  4. Esperar a las 00:00 (UTC-4) cuando se renueva quota DI")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
