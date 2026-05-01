"""
di_setup_accounts.py
--------------------
Setup script for Data Inmobiliaria multi-account cookies.

Usage:
  py scripts/di_setup_accounts.py --account 2                          # manual browser login
  py scripts/di_setup_accounts.py --account 2 --email E --password P  # automated Devise login (headless)
  py scripts/di_setup_accounts.py --list                               # show all configured accounts
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
DEFAULT_COOKIES = DATA_DIR / "datainmobiliaria_cookies.json"
LOGIN_URL   = "https://datainmobiliaria.cl/users/sign_in"
SEARCH_PAGE = "https://datainmobiliaria.cl/reports/busqueda_poligono"


def _cookie_path(account: int) -> Path:
    if account == 1:
        return DEFAULT_COOKIES
    return DATA_DIR / f"di_cookies_{account}.json"


def _list_accounts():
    files = [DEFAULT_COOKIES] + sorted(DATA_DIR.glob("di_cookies_*.json"))
    seen = set()
    idx = 1
    for f in files:
        if f in seen:
            continue
        seen.add(f)
        status = "OK" if f.exists() else "MISSING"
        label = "(default)" if f == DEFAULT_COOKIES else ""
        print(f"  Account {idx}: {f.name} [{status}] {label}")
        idx += 1


async def _auto_login(account: int, email: str, password: str):
    """Headless login via Devise email/password form."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    path = _cookie_path(account)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Auto-login account {account} ({email}) -> {path.name}")
    print(f"{'='*60}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)

        # Fill Devise form
        email_sel    = 'input[name="user[email]"], input[type="email"], #user_email'
        password_sel = 'input[name="user[password]"], input[type="password"], #user_password'
        submit_sel   = 'input[type="submit"], button[type="submit"]'

        await page.fill(email_sel, email)
        await page.fill(password_sel, password)
        await page.click(submit_sel)
        await page.wait_for_timeout(3000)

        current = page.url
        print(f"  After login URL: {current}")

        # Verify session on search page
        await page.goto(SEARCH_PAGE, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        csrf = await page.evaluate('() => document.querySelector("meta[name=csrf-token]")?.content || ""')

        if not csrf:
            print("\n  WARNING: no CSRF token — login may have failed (wrong password or Google-only account).")
        else:
            print("\n  Login verified (CSRF token present)")

        cookies = await context.cookies()
        path.write_text(json.dumps(cookies, indent=2, ensure_ascii=False))
        print(f"  Cookies saved -> {path}")
        print(f"  Total cookies: {len(cookies)}")

        test_body = json.dumps({"polygon": [{"lat": -33.47, "lng": -70.68}, {"lat": -33.47, "lng": -70.63}, {"lat": -33.42, "lng": -70.63}, {"lat": -33.42, "lng": -70.68}], "fuente": "ventas", "page": 1})
        result = await page.evaluate(f'''async () => {{
            const r = await fetch('/reports/busqueda_poligono_data', {{
                method: 'POST',
                headers: {{'Content-Type':'application/json','Accept':'application/json','X-CSRF-Token': document.querySelector('meta[name=csrf-token]')?.content||''}},
                body: JSON.stringify({test_body})
            }});
            return {{status: r.status}};
        }}''')
        status = result.get("status", 0)
        quota = "OK (200 — ready to scrape)" if status == 200 else "EXHAUSTED (402)" if status == 402 else f"Unknown ({status})"
        print(f"  Quota status: {quota}")

        await browser.close()

    print(f"\n  Account {account} configured. Run all accounts via:")
    print(f"    py scripts/run_di_bulk_multi.py")


async def _manual_login(account: int):
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    path = _cookie_path(account)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Setup account {account} -> {path.name}")
    print(f"{'='*60}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")

        print("  Browser abierto en datainmobiliaria.cl")
        print("  1. Haz login con Google (u otro método)")
        print("  2. Espera a que cargue la página principal")
        print("  3. Vuelve aquí y presiona ENTER")
        print()

        await asyncio.get_event_loop().run_in_executor(None, input, "  -> Presiona ENTER cuando estes logueado: ")
        await page.wait_for_timeout(2000)

        # Verify login succeeded
        await page.goto(SEARCH_PAGE, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        csrf = await page.evaluate('() => document.querySelector("meta[name=csrf-token]")?.content || ""')

        if not csrf:
            print("\n  WARNING: no CSRF token - login may have failed. Saving cookies anyway.")
        else:
            print("\n  Login verified (CSRF token present)")

        cookies = await context.cookies()
        path.write_text(json.dumps(cookies, indent=2, ensure_ascii=False))
        print(f"  Cookies saved -> {path}")
        print(f"  Total cookies: {len(cookies)}")

        # Quick quota check
        test_body = json.dumps({"polygon": [{"lat": -33.47, "lng": -70.68}, {"lat": -33.47, "lng": -70.63}, {"lat": -33.42, "lng": -70.63}, {"lat": -33.42, "lng": -70.68}], "fuente": "ventas", "page": 1})
        result = await page.evaluate(f'''async () => {{
            const r = await fetch('/reports/busqueda_poligono_data', {{
                method: 'POST',
                headers: {{'Content-Type':'application/json','Accept':'application/json','X-CSRF-Token': document.querySelector('meta[name=csrf-token]')?.content||''}},
                body: JSON.stringify({test_body})
            }});
            return {{status: r.status}};
        }}''')
        status = result.get("status", 0)
        quota = "OK (200 — ready to scrape)" if status == 200 else f"EXHAUSTED (402)" if status == 402 else f"Unknown ({status})"
        print(f"  Quota status: {quota}")

        await browser.close()

    print(f"\n  Account {account} configured. Use with:")
    if account == 1:
        print(f"    py src/scraping/datainmobiliaria.py --next-commune")
    else:
        print(f"    py src/scraping/datainmobiliaria.py --next-commune --cookie-file data/processed/{path.name}")
    print(f"  Or run all accounts via:")
    print(f"    py scripts/run_di_bulk_multi.py")


def main():
    parser = argparse.ArgumentParser(description="Setup Data Inmobiliaria account cookies")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--account", type=int, metavar="N", help="Account number to set up (1=default, 2, 3, ...)")
    group.add_argument("--list",    action="store_true",   help="List all configured accounts")
    parser.add_argument("--email",    type=str, default=None, help="Email for automated Devise login (headless)")
    parser.add_argument("--password", type=str, default=None, help="Password for automated Devise login (headless)")
    args = parser.parse_args()

    if args.list:
        print("\nConfigured accounts:")
        _list_accounts()
        return

    if args.email and args.password:
        asyncio.run(_auto_login(args.account, args.email, args.password))
    else:
        asyncio.run(_manual_login(args.account))


if __name__ == "__main__":
    main()
