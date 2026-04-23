# Phase 9: Scraping Paralelo Multi-fuente (sin credenciales) - Research

**Researched:** 2026-04-22
**Domain:** Playwright asyncio parallelism, Prefect V2 task scheduling, real estate portal anti-bot
**Confidence:** HIGH

---

## Summary

Phase 9 targets a single concrete goal: maximize scraped listing count by converting the three existing serial scrapers into a coordinated parallel system. The codebase is already well-structured — `BaseScraper.scrape_async()` is fully async, `PortalInmobiliarioScraper.scrape_async()` overrides it correctly, and `ToctocScraper` inherits the base loop without modification. All three scrapers write via `_write_batch()` which issues a PostgreSQL `ON CONFLICT (source, external_id) DO UPDATE` upsert, so concurrent writes from multiple coroutines are safe as long as they use separate SQLAlchemy connections (which they do — each `engine.begin()` call gets its own connection from the pool).

The core work is: (1) an `asyncio.gather()`-based parallel runner for Toctoc's 4 property types, (2) a batched-commune parallel runner for Portal Inmobiliario's 160 commune×type requests, (3) a Prefect task wrapper for `datainmobiliaria.py --next-commune`, and (4) a new `parallel_scrape_flow` that chains all three sources plus the existing `normalize_county` + `scraped_to_scored` pipeline.

**Primary recommendation:** Use `asyncio.gather()` within a single Python process for Toctoc and PI parallelism. Do NOT use `ProcessPoolExecutor` or `multiprocessing` — Playwright's asyncio API cannot be shared across OS processes, and each process would need its own Chromium instance consuming 200-400 MB RAM each.

---

## Project Constraints (from CLAUDE.md)

- Stack: Python 3.11, Playwright (already installed), Prefect V2
- Platform: Windows 11 + PowerShell
- **NEEDS APPROVAL** before: truncating tables, modifying schema in production, launching scrapers against live sites, consuming paid APIs
- **SAFE**: creating new files, adding Prefect tasks, dry-run testing
- No proxies, no rotating IPs — single IP, politeness required
- Credentials: never hardcode; use `.env` + `python-dotenv`
- Idempotency: upsert by `(source, external_id)` — already implemented in `_write_batch()`

---

## Standard Stack

### Core (already installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| playwright | already installed | Browser automation | Used throughout codebase, async API verified |
| asyncio | stdlib | Coroutine concurrency | Single-event-loop model matches Playwright's async API |
| prefect | V2, already installed | Flow/task scheduling | Used throughout codebase for all pipeline orchestration |
| sqlalchemy | already installed | DB writes | `_write_batch()` uses engine.begin() — thread/coroutine safe via connection pool |
| loguru | already installed | Structured logging | Consistent with all existing scrapers |

### No New Dependencies Required
All libraries needed for Phase 9 are already in `requirements.txt`. Phase 9 adds zero new packages. [VERIFIED: reading requirements.txt and existing imports across codebase]

---

## Architecture Patterns

### Pattern 1: asyncio.gather() for Toctoc 4-type parallelism

**What:** Launch all 4 property-type scrapers as concurrent coroutines within a single `async_playwright()` context. Each type gets its own browser context and page — Playwright supports multiple browser contexts within one `async_playwright()` session.

**When to use:** When tasks are I/O-bound (network + page render), share a process, and can run concurrently. Toctoc's 4 types are completely independent — no shared state.

**Critical constraint:** Each `ToctocScraper` instance must create its own browser context. The existing `scrape_async()` already creates browser+context+page privately, so running 4 instances concurrently via `asyncio.gather()` is safe. [VERIFIED: reading base.py lines 225-284]

**Pattern:**
```python
import asyncio
from src.scraping.toctoc import ToctocScraper

async def scrape_toctoc_parallel(engine, max_pages: int = 50) -> int:
    """Run all 4 Toctoc property types concurrently."""
    property_types = ["apartments", "residential", "land", "retail"]
    
    async def scrape_one(ptype):
        scraper = ToctocScraper(engine=engine)
        return await scraper.scrape_async(max_pages=max_pages, property_type=ptype)
    
    results = await asyncio.gather(
        *[scrape_one(pt) for pt in property_types],
        return_exceptions=True  # don't let one failure kill others
    )
    
    total = 0
    for ptype, result in zip(property_types, results):
        if isinstance(result, Exception):
            logger.warning(f"Toctoc {ptype} failed: {result}")
        else:
            total += result
            logger.info(f"Toctoc {ptype}: {result} listings")
    return total

def run_toctoc_parallel(engine, max_pages: int = 50) -> int:
    return asyncio.run(scrape_toctoc_parallel(engine, max_pages))
```

**Source:** [VERIFIED: Playwright docs confirm multiple browser contexts within one async_playwright() session are supported. ASSUMED: no explicit Playwright docs URL verified this session, but the pattern is confirmed by the existing codebase using `browser.new_context()` per rotation cycle in base.py]

### Pattern 2: Batched commune parallelism for Portal Inmobiliario

**What:** The existing `by_commune` mode in `portal_inmobiliario.py run()` iterates serially through 40 communes × 4 types = 160 requests. Replace this with `asyncio.gather()` over configurable batch sizes.

**Key constraint from codebase:** MeLi does NOT allow direct navigation to paginated `_Desde_N` URLs without session cookies. However, page 1 per commune is free and does not require pagination — this is the `by_commune=True` mode that already exists. The `scrape_async()` for PI with `max_pages=1` makes a single page request per commune, so parallel commune batches are safe (no pagination click dependency). [VERIFIED: reading portal_inmobiliario.py lines 596-646, especially the comment about MeLi session cookie requirement]

**Batch size recommendation:** 5-8 concurrent commune requests. At 3-5 second delay per request, 40 communes ÷ 6 parallel = ~6-7 batches, reducing wall time from ~25-30 min to ~5-6 min. Do not exceed 10 concurrent Chromium instances — Windows 11 RAM constraint (each instance ~150-200 MB).

**Pattern:**
```python
import asyncio
from src.scraping.portal_inmobiliario import PortalInmobiliarioScraper, RM_COMMUNES, TYPE_MAP

async def scrape_pi_commune_batch(engine, batch_size: int = 6, max_pages: int = 1) -> int:
    """Scrape Portal Inmobiliario by-commune in parallel batches."""
    
    async def scrape_one(ptype: str, cname: str, cslug: str) -> int:
        scraper = PortalInmobiliarioScraper(engine=engine)
        try:
            return await scraper.scrape_async(
                max_pages=max_pages, property_type=ptype, commune_slug=cslug
            )
        except Exception as e:
            logger.warning(f"PI {cname}/{ptype} error: {e}")
            return 0
    
    # Build all (ptype, cname, cslug) tasks
    tasks = [
        (ptype, cname, cslug)
        for ptype in TYPE_MAP.keys()
        for cname, cslug in RM_COMMUNES.items()
    ]
    
    total = 0
    # Process in batches to avoid overwhelming single IP
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i + batch_size]
        results = await asyncio.gather(
            *[scrape_one(pt, cn, cs) for pt, cn, cs in batch],
            return_exceptions=True
        )
        for (pt, cn, _), result in zip(batch, results):
            if isinstance(result, int):
                total += result
            else:
                logger.warning(f"PI batch error {cn}/{pt}: {result}")
        # Inter-batch delay for IP politeness
        await asyncio.sleep(2)
    
    return total

def run_pi_parallel(engine, batch_size: int = 6) -> int:
    return asyncio.run(scrape_pi_commune_batch(engine, batch_size=batch_size))
```

### Pattern 3: Prefect task for Data Inmobiliaria --next-commune

**What:** Wrap the existing `datainmobiliaria_daily_flow` (already exists in flows.py) as a Prefect task callable from the new `parallel_scrape_flow`. The flow already handles `--next-commune` logic internally via `_next_unscraped_commune()`.

**Key finding:** `datainmobiliaria_daily_flow` is ALREADY implemented in `flows.py` (lines 288-363). It is already scheduled separately. Phase 9 does not need to reimplement it — it needs to ensure it runs before or after the PI/Toctoc parallel scrape, and that its output feeds into `normalize_county` + `scraped_to_scored`. [VERIFIED: reading flows.py lines 288-363]

**The DI scraper uses a blocking `asyncio.run()` internally** (flows.py line 340). This means it CANNOT be awaited as a coroutine from within a running event loop — it must be called in a Prefect task (separate sync context) or via `loop.run_in_executor()`. Since Prefect tasks already run in separate thread contexts, the existing pattern is correct.

### Pattern 4: Unified parallel_scrape_flow

**What:** A new Prefect flow that orchestrates all three sources in sequence (DI first since it has the quota constraint), then PI + Toctoc in parallel (via Prefect's concurrent task submission), then normalize + score.

**Prefect V2 concurrent task pattern:** [VERIFIED: reading existing flows.py — all task calls are sequential. For true Prefect-level concurrency, Prefect V2 supports `.submit()` on tasks with a `ConcurrentTaskRunner`. However, since PI and Toctoc each internally manage their own asyncio event loops via `asyncio.run()`, calling them from concurrent Prefect tasks is clean.] [ASSUMED: ConcurrentTaskRunner is available in the installed Prefect V2 version. Verify with `pip show prefect`.]

```python
# In flows.py — add new flow
from prefect.task_runners import ConcurrentTaskRunner

@flow(
    name="RE_CL Parallel Scrape",
    description="Parallel scraping: PI (by-commune batches) + Toctoc (4 types async) + DI (next commune)",
    task_runner=ConcurrentTaskRunner(),
)
def parallel_scrape_flow(
    max_pages_toctoc: int = 50,
    pi_batch_size: int = 6,
    run_di: bool = True,
    dry_run: bool = False,
) -> dict:
    results = {}
    
    # PI and Toctoc can run concurrently (different domains, different IPs budget)
    pi_future   = task_scrape_pi_parallel.submit(batch_size=pi_batch_size)
    tt_future   = task_scrape_toctoc_parallel.submit(max_pages=max_pages_toctoc)
    
    # DI: sequential — uses quota; must not run at same time as other DI tasks
    if run_di:
        results["n_di"] = task_scrape_di_next_commune()
    
    results["n_pi"]     = pi_future.result()
    results["n_toctoc"] = tt_future.result()
    
    # Post-scraping pipeline
    task_normalize_county()
    task_score_scraped()
    
    return results
```

### Pattern 5: New Prefect task wrappers needed in tasks.py

The following task wrappers do NOT yet exist and must be added:

| Task | Wraps | Notes |
|------|-------|-------|
| `task_scrape_pi_parallel` | `run_pi_parallel()` in new `parallel_pi.py` or inline | Replaces serial `task_scrape_portal` for Phase 9 |
| `task_scrape_toctoc_parallel` | `run_toctoc_parallel()` in new `parallel_toctoc.py` or toctoc.py | Replaces serial `task_scrape_toctoc` |
| `task_scrape_di_next_commune` | `datainmobiliaria.scrape_all(communes=[next_c])` | Already exists as a full flow — needs task wrapper too |
| `task_normalize_county` | `normalize_county.normalize_county(engine)` | Does not yet exist in tasks.py |
| `task_score_scraped` | `scraped_to_scored.main()` | Does not yet exist in tasks.py |

[VERIFIED: reading tasks.py — `task_normalize_county` and `task_score_scraped` are absent. `task_scrape_portal` and `task_scrape_toctoc` exist but are serial.]

### Anti-patterns to Avoid

- **Sharing Playwright browser objects across coroutines:** Each `scrape_async()` call must create its own `async with async_playwright() as p:` context. Never share a `Browser` or `BrowserContext` between concurrent coroutines. [VERIFIED: each existing scraper creates its own context in scrape_async()]
- **ProcessPoolExecutor with Playwright:** Playwright's async API uses asyncio which is not picklable — cannot be passed between processes. [ASSUMED: standard Python multiprocessing constraint — not Playwright-specific docs verified this session]
- **asyncio.run() inside a running event loop:** The DI scraper uses `asyncio.run()` internally (flows.py:340). Calling it from within an async context will raise `RuntimeError: This event loop is already running`. Must call DI from a sync Prefect task, not from within another coroutine.
- **Too many concurrent Chromium instances:** On Windows 11 with 16GB RAM, more than 8-10 concurrent headless Chromium instances will cause OOM. Batch size of 6 for PI communes is a safe default.
- **Ignoring `return_exceptions=True` in gather():** Without this, a single failed commune scrape cancels the entire batch. Always use `return_exceptions=True`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async concurrency | Custom thread pool for browser workers | `asyncio.gather()` | Already matches Playwright's event loop model |
| Upsert / dedup | Custom dedup logic | Existing `_write_batch()` `ON CONFLICT DO UPDATE` | Already idempotent; concurrent writers safe via connection pool |
| County name normalization | New normalization logic | Existing `normalize_county.py` | Already has 50+ overrides, rapidfuzz, and all 40 RM communes |
| Scoring pipeline | Re-implement scoring | Existing `scraped_to_scored.main()` | Full pipeline: normalize → predict → undervaluation → opportunity_score |
| Checkpoint tracking | New file-based state | Existing `datainmobiliaria_checkpoint.json` system | Already tracks 40 communes with timestamps |

---

## Common Pitfalls

### Pitfall 1: asyncio.run() called inside running event loop
**What goes wrong:** `RuntimeError: This event loop is already running` when calling DI's `asyncio.run(scrape_all(...))` from within a Prefect async context or another coroutine.
**Why it happens:** `flows.py:340` wraps `scrape_all()` with `asyncio.run()`. If a parent coroutine is already running, a nested `asyncio.run()` is forbidden.
**How to avoid:** Always call `task_scrape_di_next_commune` as a synchronous Prefect task (decorated with `@task`), not from within an async gather. Prefect tasks run in thread pool executors by default — they have their own sync context.
**Warning signs:** `RuntimeError: This event loop is already running` in Prefect logs.

### Pitfall 2: MeLi blocks direct navigation to paginated _Desde_N URLs
**What goes wrong:** PI scraper returns 0 listings on pages 2+ when launched without session cookies.
**Why it happens:** MeLi requires established session cookies for paginated URLs. The `by_commune` mode only requests page 1 per commune — this is the intended workaround. Each parallel commune scraper starts fresh (new context), requests page 1 only, and exits cleanly.
**How to avoid:** Keep `max_pages=1` for all parallel PI commune requests. Do not attempt to parallelize multi-page PI scraping without a session cookie sharing mechanism (which would require complex context sharing — out of scope).
**Warning signs:** 0 listings extracted on page 2+ in logs; JSON-LD strategy returns empty on subsequent pages.

### Pitfall 3: Toctoc __NEXT_DATA__ structure changes
**What goes wrong:** Toctoc scraper returns 0 listings silently — falls back to DOM which also returns 0.
**Why it happens:** Next.js data path `props.pageProps.propiedades.results` is version-specific and can change on deployment.
**How to avoid:** Run `python re_cl/src/scraping/toctoc.py --dump-html` before deploying Phase 9 tasks. Verify structure in `data/exports/toctoc_debug.html`. The parallel runner should log per-type result counts — zero across all 4 types simultaneously is the diagnostic signal.
**Warning signs:** All 4 parallel Toctoc tasks report 0 listings; `--dump-html` shows different JSON structure.

### Pitfall 4: Concurrent DB writes causing connection pool exhaustion
**What goes wrong:** `sqlalchemy.exc.TimeoutError: QueuePool limit` when 6+ concurrent scrapers try to write simultaneously.
**Why it happens:** SQLAlchemy's default pool size is 5 connections. With 6+ concurrent scraper coroutines all calling `_write_batch()` at the same time, pool is exhausted.
**How to avoid:** Create the SQLAlchemy engine with an appropriate pool size for the concurrency level: `create_engine(url, pool_size=10, max_overflow=5)`. Alternatively, use `NullPool` for scraper engines (creates/drops connections per use — slower but no contention).
**Warning signs:** `TimeoutError` or `QueuePool limit of size 5 overflow 10 reached` in logs.

### Pitfall 5: Data Inmobiliaria 402 quota in the middle of other scraping
**What goes wrong:** DI run stops mid-commune due to guest quota exhaustion (402), leaving checkpoint in inconsistent state — commune partially scraped but not checkpointed as done.
**Why it happens:** Guest quota is ~15k records/IP/day. If a prior DI run in the same day already consumed quota, the daily flow fails immediately on page 1 with 402.
**How to avoid:** Always run `--check-quota` before the DI commune scrape in the Prefect task. The existing `check_quota_only` mode returns status without consuming quota. If 402, skip gracefully and log warning — do not retry.
**Warning signs:** `Quota check: 402 — guest quota exhausted` in DI logs.

### Pitfall 6: Windows asyncio event loop policy
**What goes wrong:** `NotImplementedError` or subprocess errors when running Playwright on Windows with default asyncio event loop.
**Why it happens:** Python 3.8+ on Windows uses `ProactorEventLoop` by default. Playwright requires `ProactorEventLoop` on Windows (which is already the default), but some libraries explicitly set `SelectorEventLoop` which breaks subprocess spawning.
**How to avoid:** Do not set `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())`. Leave Windows asyncio defaults untouched. [VERIFIED: existing codebase never sets event loop policy — correct pattern already in place]
**Warning signs:** `NotImplementedError` at browser launch on Windows; Playwright subprocess timeout.

---

## Code Examples

### Running Toctoc 4 types in parallel (complete, drop-in replacement)
```python
# In re_cl/src/scraping/toctoc.py — add run_parallel() function

import asyncio
from loguru import logger
from src.scraping.toctoc import ToctocScraper, TYPE_MAP

async def _scrape_toctoc_all_types_async(engine, max_pages: int = 50) -> int:
    """Run all 4 Toctoc property types concurrently."""
    async def one_type(ptype: str) -> int:
        scraper = ToctocScraper(engine=engine)
        n = await scraper.scrape_async(max_pages=max_pages, property_type=ptype)
        logger.info(f"[toctoc-parallel] {ptype}: {n} listings")
        return n

    results = await asyncio.gather(
        *[one_type(pt) for pt in TYPE_MAP.keys()],
        return_exceptions=True
    )
    total = sum(r for r in results if isinstance(r, int))
    errors = [r for r in results if isinstance(r, Exception)]
    if errors:
        logger.warning(f"[toctoc-parallel] {len(errors)} type(s) failed: {errors}")
    return total

def run_parallel(engine=None, max_pages: int = 50) -> int:
    """Sync entrypoint for Prefect task."""
    return asyncio.run(_scrape_toctoc_all_types_async(engine, max_pages))
```

### Portal Inmobiliario batched commune runner
```python
# In re_cl/src/scraping/portal_inmobiliario.py — add run_parallel() function

import asyncio
from loguru import logger
from src.scraping.portal_inmobiliario import PortalInmobiliarioScraper, RM_COMMUNES, TYPE_MAP

async def _scrape_pi_communes_async(engine, batch_size: int = 6) -> int:
    """Scrape page-1 per commune×type in parallel batches."""
    tasks = [
        (ptype, cname, cslug)
        for ptype in TYPE_MAP.keys()
        for cname, cslug in RM_COMMUNES.items()
    ]
    logger.info(f"[pi-parallel] {len(tasks)} commune×type requests, batch_size={batch_size}")

    async def one_request(ptype, cname, cslug) -> int:
        scraper = PortalInmobiliarioScraper(engine=engine)
        try:
            n = await scraper.scrape_async(
                max_pages=1, property_type=ptype, commune_slug=cslug
            )
            return n
        except Exception as e:
            logger.warning(f"[pi-parallel] {cname}/{ptype}: {e}")
            return 0

    total = 0
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i + batch_size]
        batch_results = await asyncio.gather(
            *[one_request(pt, cn, cs) for pt, cn, cs in batch],
            return_exceptions=True
        )
        n_batch = sum(r for r in batch_results if isinstance(r, int))
        total += n_batch
        logger.info(f"[pi-parallel] batch {i//batch_size + 1}: {n_batch} listings (total so far: {total})")
        await asyncio.sleep(2)   # inter-batch politeness

    return total

def run_parallel(engine=None, batch_size: int = 6) -> int:
    """Sync entrypoint for Prefect task."""
    return asyncio.run(_scrape_pi_communes_async(engine, batch_size=batch_size))
```

### New Prefect tasks to add to tasks.py
```python
@task(name="scrape-toctoc-parallel", retries=2, retry_delay_seconds=60)
def task_scrape_toctoc_parallel(max_pages: int = 50) -> int:
    from src.scraping.toctoc import run_parallel
    engine = create_engine(_build_db_url(), pool_size=10, max_overflow=5, pool_pre_ping=True)
    return run_parallel(engine=engine, max_pages=max_pages)

@task(name="scrape-pi-parallel", retries=2, retry_delay_seconds=60)
def task_scrape_pi_parallel(batch_size: int = 6) -> int:
    from src.scraping.portal_inmobiliario import run_parallel
    engine = create_engine(_build_db_url(), pool_size=10, max_overflow=5, pool_pre_ping=True)
    return run_parallel(engine=engine, batch_size=batch_size)

@task(name="normalize-county", retries=1)
def task_normalize_county() -> dict:
    from src.ingestion.normalize_county import normalize_county
    engine = create_engine(_build_db_url(), pool_pre_ping=True)
    return normalize_county(engine)

@task(name="score-scraped-listings", retries=1)
def task_score_scraped(dry_run: bool = False) -> int:
    from src.scoring.scraped_to_scored import main as score_main
    return score_main(dry_run=dry_run)
```

### Engine pool sizing for concurrent writers
```python
# Safe engine for parallel scraping — pool large enough for 6-10 concurrent writers
engine = create_engine(
    _build_db_url(),
    pool_size=10,        # up from default 5
    max_overflow=5,      # allow 5 extra connections under burst
    pool_timeout=30,     # wait up to 30s for a connection
    pool_pre_ping=True,  # detect stale connections
)
```

---

## Rate Limiting / Politeness Strategy

| Source | Strategy | Rationale |
|--------|----------|-----------|
| Toctoc | 4 concurrent browser sessions | Different cookies/contexts; Toctoc has no known per-IP rate limit; Next.js SSR is lightweight |
| Portal Inmobiliario | 6 concurrent sessions, 2s inter-batch delay | MeLi has aggressive bot detection; 6 simultaneous sessions from one IP is the safe ceiling; each is a single page-1 request |
| Data Inmobiliaria | 1 commune/day, 0.5s between pages | Guest quota is ~100 pages/day total; hardcoded in existing `_fetch_commune()` with `asyncio.sleep(0.5)` |

**Anti-detection measures already in place (do not remove):**
- Random user-agent rotation per context (`USER_AGENTS` list in base.py)
- Context rotation every 10 pages in base scraper
- `_dismiss_overlays()` in PI scraper to clear MeLi coach marks
- `domcontentloaded` + explicit `wait_for_timeout(3000)` on every page load
- `--disable-blink-features=AutomationControlled` in DI scraper launch args [VERIFIED: datainmobiliaria.py line 361]

**Do NOT add for Phase 9 (out of scope):**
- Proxy rotation
- CAPTCHA solving
- Browser fingerprint spoofing beyond existing user-agent rotation

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (already configured) |
| Config file | `re_cl/` (run from re_cl/ directory) |
| Quick run command | `cd re_cl && pytest tests/test_scraping_parallel.py -v` |
| Full suite command | `cd re_cl && pytest tests/ -v` |

### Phase Requirements → Test Map
| Req | Behavior | Test Type | Command | Notes |
|-----|----------|-----------|---------|-------|
| Toctoc parallel | 4 types run concurrently, not sequentially | unit | `pytest tests/test_scraping_parallel.py::test_toctoc_parallel_returns_int -x` | Mock browser; verify asyncio.gather called |
| PI batch | 160 commune×type split into batches of N | unit | `pytest tests/test_scraping_parallel.py::test_pi_batch_splits_correctly -x` | No browser; verify batch math |
| DB pool | Engine created with pool_size=10 | unit | `pytest tests/test_scraping_parallel.py::test_engine_pool_size -x` | Inspect engine.pool.size() |
| normalize_county task | Prefect task wraps normalize_county | unit | `pytest tests/test_scraping_parallel.py::test_task_normalize_county_exists -x` | Import check |
| score_scraped task | Prefect task wraps scraped_to_scored | unit | `pytest tests/test_scraping_parallel.py::test_task_score_scraped_exists -x` | Import check |
| DI quota check | 402 → graceful skip, no crash | unit | `pytest tests/test_scraping_parallel.py::test_di_quota_exhausted_handled -x` | Mock 402 response |
| End-to-end count | >5000 unique listings in scraped_listings | integration/smoke | Manual: `psql -c "SELECT COUNT(*) FROM scraped_listings"` | Requires live DB + scrape run |

### Sampling Rate
- **Per task commit:** `pytest tests/test_scraping_parallel.py -x`
- **Per wave merge:** `cd re_cl && pytest tests/ -v`
- **Phase gate:** Full suite green + `SELECT COUNT(*) FROM scraped_listings` > 5000

### Wave 0 Gaps
- [ ] `re_cl/tests/test_scraping_parallel.py` — new file; covers all 7 test cases above
- [ ] No new framework install needed — pytest already configured

---

## Environment Availability

| Dependency | Required By | Available | Notes |
|------------|------------|-----------|-------|
| Python 3.11 | All scrapers | Assumed available | CLAUDE.md specifies 3.11 |
| Playwright (chromium) | All scrapers | Already installed | Used in existing PI/Toctoc/DI scrapers |
| Prefect V2 | Flow orchestration | Already installed | `flows.py` imports `from prefect import flow` |
| PostgreSQL (Docker) | DB writes | Available when `docker-compose up -d` | Existing stack |
| asyncio | Concurrency | stdlib, always available | Python 3.11 stdlib |
| rapidfuzz | normalize_county | Already in requirements.txt | `normalize_county.py` imports it |

**Missing dependencies with no fallback:** None.

---

## Runtime State Inventory

This is not a rename/refactor phase. The checkpoint file `data/processed/datainmobiliaria_checkpoint.json` is the only runtime state relevant to Phase 9. Phase 9 reads it (via `_next_unscraped_commune()`) but does not rename or reset it.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | `datainmobiliaria_checkpoint.json` — tracks 40 communes | Read-only by Phase 9; no migration needed |
| Stored data | `datainmobiliaria_cookies.json` — Google OAuth session | Read-only by Phase 9; no migration needed |
| Live service config | None relevant | None |
| OS-registered state | None | None |
| Secrets/env vars | `DATABASE_URL` / `POSTGRES_*` — used by all scrapers | No change |
| Build artifacts | None | None |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Playwright supports multiple browser contexts concurrently within one `async_playwright()` session | Pattern 1 | If wrong: must launch separate playwright processes; complicates implementation significantly |
| A2 | ConcurrentTaskRunner is available in installed Prefect V2 version | Pattern 4 | If wrong: use `asyncio.gather()` at Python level instead of Prefect task concurrency |
| A3 | Toctoc has no aggressive per-IP rate limiting for 4 concurrent sessions | Rate Limiting | If wrong: reduce to 2 concurrent types; add longer inter-type delay |
| A4 | 6 concurrent Chromium instances is safe on the target machine's RAM | Pattern 2 | If wrong: reduce batch_size; monitor RAM during first run |
| A5 | PI page-1 per commune does not require session cookies (only pagination requires them) | Pattern 2, Pitfall 2 | If wrong: must implement cookie-sharing mechanism across concurrent contexts |

---

## Open Questions

1. **Does PI page-1 per commune work without prior session establishment?**
   - What we know: The code comment in `portal_inmobiliario.py` says "MeLi requires login for paginated results (_Desde_N), but page 1 per commune is free" [VERIFIED: line 55-56]
   - What's unclear: Whether parallel cold-start requests to 6 communes simultaneously triggers MeLi's bot detection more aggressively than sequential
   - Recommendation: Implement with batch_size=3 for the first test run; increase if no blocking observed

2. **Prefect V2 ConcurrentTaskRunner availability**
   - What we know: Prefect V2 has `ConcurrentTaskRunner` in `prefect.task_runners` [ASSUMED]
   - What's unclear: Whether the installed version includes it (Prefect V2 API changed across minor versions)
   - Recommendation: Verify with `python -c "from prefect.task_runners import ConcurrentTaskRunner; print('ok')"` before implementing Pattern 4; fall back to pure asyncio.gather() pattern if unavailable

3. **Portal Inmobiliario slug completeness**
   - What we know: `RM_COMMUNES` dict has 40 entries but `Pudahuel` is listed twice (keys deduplicate in Python dicts — so effectively 39 unique communes) [VERIFIED: portal_inmobiliario.py lines 66-98]
   - What's unclear: Which communes are actually missing coverage
   - Recommendation: Fix the `Pudahuel` duplicate in PI's `RM_COMMUNES` as part of Wave 1

---

## Sources

### Primary (HIGH confidence)
- `re_cl/src/scraping/base.py` — BaseScraper implementation, `scrape_async()` pattern, `_write_batch()` upsert
- `re_cl/src/scraping/portal_inmobiliario.py` — `by_commune` mode, MeLi session constraints, RM_COMMUNES dict
- `re_cl/src/scraping/toctoc.py` — `__NEXT_DATA__` strategy, TYPE_MAP, serial run() function
- `re_cl/src/scraping/datainmobiliaria.py` — checkpoint system, cookie management, quota detection, 402 handling
- `re_cl/src/pipelines/flows.py` — existing Prefect flows, `datainmobiliaria_daily_flow` already implemented
- `re_cl/src/pipelines/tasks.py` — existing task wrappers, missing normalize_county + score_scraped tasks
- `re_cl/src/ingestion/normalize_county.py` — fuzzy normalization pipeline, RM_COMMUNES_CANONICAL
- `re_cl/src/scoring/scraped_to_scored.py` — full scoring pipeline for scraped listings

### Secondary (MEDIUM confidence)
- Python asyncio stdlib documentation [ASSUMED: asyncio.gather() behavior and return_exceptions parameter]
- Playwright Python docs [ASSUMED: multiple browser contexts per async_playwright() session]

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in codebase, verified by imports
- Architecture: HIGH — patterns derived directly from reading existing code
- Pitfalls: HIGH — Pitfalls 1-3, 5-6 verified from codebase; Pitfall 4 (pool exhaustion) is MEDIUM (inferred from SQLAlchemy default pool_size=5)
- Anti-detection: HIGH — existing anti-bot measures verified in base.py and datainmobiliaria.py

**Research date:** 2026-04-22
**Valid until:** 2026-07-22 (stable libraries, 90 days; Toctoc/PI selectors may need re-verification sooner)
