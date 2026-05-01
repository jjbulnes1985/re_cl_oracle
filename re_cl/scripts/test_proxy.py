"""
test_proxy.py
-------------
Quick validation of proxy / VPN setup before running the full scraper.

Tests:
  1. Connectivity through the proxy (check public IP)
  2. Whether datainmobiliaria.cl quota is available via that proxy

Usage:
  py scripts/test_proxy.py                            # Direct (no proxy)
  py scripts/test_proxy.py --proxy http://host:port   # Open proxy
  py scripts/test_proxy.py --proxy http://user:pass@host:port  # Auth proxy
  py scripts/test_proxy.py --account 2 --proxy ...    # Test specific account+proxy
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"


def _cookie_path(account: int) -> Path:
    if account == 1:
        return DATA_DIR / "datainmobiliaria_cookies.json"
    return DATA_DIR / f"di_cookies_{account}.json"


async def check_ip(proxy_url: str | None) -> str | None:
    """Check public IP via proxy (or direct)."""
    from playwright.async_api import async_playwright

    context_kwargs = {}
    if proxy_url:
        from urllib.parse import urlparse
        parsed = urlparse(proxy_url)
        proxy_config = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
        if parsed.username:
            proxy_config["username"] = parsed.username
        if parsed.password:
            proxy_config["password"] = parsed.password
        context_kwargs["proxy"] = proxy_config

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        try:
            await page.goto("https://api.ipify.org/?format=json", wait_until="domcontentloaded", timeout=20000)
            content = await page.content()
            import re
            m = re.search(r'"ip":"([^"]+)"', content)
            ip = m.group(1) if m else None
            return ip
        except Exception as e:
            logger.error(f"  IP check failed: {e}")
            return None
        finally:
            await browser.close()


async def check_quota(account: int, proxy_url: str | None) -> dict:
    """Login with cookies and check DI quota via proxy."""
    from playwright.async_api import async_playwright

    cookie_file = _cookie_path(account)
    if not cookie_file.exists():
        return {"status": "no_cookies", "error": f"{cookie_file.name} not found"}

    context_kwargs = {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    if proxy_url:
        from urllib.parse import urlparse
        parsed = urlparse(proxy_url)
        proxy_config = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
        if parsed.username: proxy_config["username"] = parsed.username
        if parsed.password: proxy_config["password"] = parsed.password
        context_kwargs["proxy"] = proxy_config

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(**context_kwargs)

        try:
            cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
            await context.add_cookies(cookies)
        except Exception as e:
            await browser.close()
            return {"status": "cookie_load_failed", "error": str(e)}

        page = await context.new_page()
        try:
            await page.goto("https://datainmobiliaria.cl/reports/busqueda_poligono",
                            wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # Verify login (check for csrf token)
            csrf = await page.evaluate('() => document.querySelector("meta[name=csrf-token]")?.content || ""')

            # Test API call
            test_body = {
                "polygon": [{"lat": -33.47, "lng": -70.68}, {"lat": -33.47, "lng": -70.63},
                            {"lat": -33.42, "lng": -70.63}, {"lat": -33.42, "lng": -70.68}],
                "fuente": "ventas", "page": 1
            }
            result = await page.evaluate(f'''async () => {{
                const r = await fetch('/reports/busqueda_poligono_data', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'X-CSRF-Token': document.querySelector('meta[name=csrf-token]')?.content || ''
                    }},
                    body: JSON.stringify({json.dumps(test_body)})
                }});
                return {{status: r.status}};
            }}''')

            return {
                "status": "ok" if result.get("status") == 200 else "exhausted" if result.get("status") == 402 else "unknown",
                "http_status": result.get("status"),
                "csrf_present": bool(csrf),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
        finally:
            await browser.close()


async def main():
    parser = argparse.ArgumentParser(description="Test proxy/VPN setup against Data Inmobiliaria")
    parser.add_argument("--proxy", type=str, default=None, help="Proxy URL (http://[user:pass@]host:port)")
    parser.add_argument("--account", type=int, default=1, help="Account index to test (1, 2, 3...)")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("DI PROXY TEST")
    logger.info("=" * 60)

    # Default to env if no flag
    if not args.proxy:
        args.proxy = os.getenv(f"DI_PROXY_{args.account}")

    masked = args.proxy
    if args.proxy and "@" in args.proxy:
        masked = "http://****:****@" + args.proxy.split("@")[-1]
    logger.info(f"Proxy: {masked or '(direct, no proxy)'}")
    logger.info(f"Account: {args.account} ({_cookie_path(args.account).name})")
    logger.info("")

    # Step 1: Check IP
    logger.info("Step 1: Checking public IP...")
    ip = await check_ip(args.proxy)
    if ip:
        logger.info(f"  Public IP: {ip}")
    else:
        logger.error("  FAILED — proxy unreachable")
        sys.exit(1)

    # Step 2: Check quota
    logger.info("")
    logger.info("Step 2: Checking DI quota via this IP...")
    result = await check_quota(args.account, args.proxy)
    logger.info(f"  Result: {json.dumps(result, indent=2)}")

    logger.info("")
    logger.info("=" * 60)
    if result.get("status") == "ok":
        logger.info("OK — quota available, ready to scrape")
    elif result.get("status") == "exhausted":
        logger.warning("QUOTA EXHAUSTED — try a different IP/proxy or wait until midnight")
    elif result.get("status") == "no_cookies":
        logger.error(f"NO COOKIES — run: py scripts/di_setup_accounts.py --account {args.account}")
    else:
        logger.error(f"FAILED — {result.get('error', 'unknown')}")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
