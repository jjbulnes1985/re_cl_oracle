---
phase: 09
plan: 02
subsystem: scraping
tags: [parallel, asyncio, toctoc, portal-inmobiliario, wave-2]
completed: "2026-04-22"
duration_minutes: 20

dependency_graph:
  requires:
    - 09-01 (RM_COMMUNES 40 entries + _build_scraper_engine() from Wave 1)
  provides:
    - toctoc.run_parallel() — 4 types concurrently via asyncio.gather
    - portal_inmobiliario.run_parallel() — 160 (commune × type) pairs in batched asyncio.gather
    - 9 new unit tests (4 toctoc + 5 PI), 17 total in test_scraping_parallel.py
  affects:
    - re_cl/src/scraping/toctoc.py (run_parallel + _scrape_toctoc_all_types_async added)
    - re_cl/src/scraping/portal_inmobiliario.py (run_parallel + _scrape_pi_communes_async added)

tech_stack:
  added: []
  patterns:
    - asyncio.gather(return_exceptions=True) for concurrent I/O without cancellation on failure
    - Batched gather: range(0, len(tasks), batch_size) + asyncio.sleep(2) inter-batch politeness
    - Sync wrapper pattern: run_parallel() = asyncio.run(_async_coroutine())

key_files:
  modified:
    - re_cl/src/scraping/toctoc.py
    - re_cl/src/scraping/portal_inmobiliario.py
    - re_cl/tests/test_scraping_parallel.py
  created: []

decisions:
  - "Used asyncio.sleep(random.uniform(0, 2)) in toctoc one_type() to stagger 4 browser launches and avoid simultaneous TCP handshakes"
  - "PI run_parallel default max_pages=1 per MeLi Pitfall 2 — page-1 per commune is free, pagination requires session cookies"
  - "asyncio.sleep(2) between PI batches placed inside loop only when more batches remain (if i + batch_size < len(tasks)) to avoid unnecessary trailing sleep"
  - "test_pi_run_parallel_isolates_failures uses odd-indexed call_count rather than commune index to avoid ordering assumptions in asyncio.gather"

metrics:
  tasks_completed: 2
  tasks_total: 2
  files_created: 0
  files_modified: 3
---

# Phase 9 Plan 02: Parallel Wrappers — toctoc + Portal Inmobiliario Summary

**One-liner:** Added asyncio.gather-based parallel runners to both scrapers — toctoc scrapes 4 types concurrently, Portal Inmobiliario scrapes 160 (commune × type) pairs in configurable batches — with return_exceptions=True isolation and backward-compatible serial run() preserved.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | toctoc.run_parallel() + 4 unit tests | db2f0d5 | toctoc.py, test_scraping_parallel.py |
| 2 | portal_inmobiliario.run_parallel() + 5 unit tests | 1285ccc | portal_inmobiliario.py, test_scraping_parallel.py |

## What Was Built

### Task 1: toctoc.run_parallel() (toctoc.py)

Added at module level (before existing `def run()`):

- `import asyncio` added to top-level imports
- `_scrape_toctoc_all_types_async(engine, max_pages)` — async coroutine that fans out over all 4 `TYPE_MAP` keys via `asyncio.gather(*[one_type(pt) for pt in TYPE_MAP.keys()], return_exceptions=True)`. Each `one_type()` closure creates a fresh `ToctocScraper` instance with its own Playwright context. Stagger delay `asyncio.sleep(random.uniform(0, 2))` per type launch.
- `run_parallel(engine=None, max_pages=50)` — sync wrapper via `asyncio.run()`

Exception handling: results that are `Exception` instances are logged as warnings; only numeric results accumulate to `total`. Failed types are reported in aggregate but do not abort the run.

### Task 2: portal_inmobiliario.run_parallel() (portal_inmobiliario.py)

Added at module level (before existing `def run()`):

- `import asyncio` added to top-level imports (was previously only imported locally inside `if args.dump_html` block)
- `_scrape_pi_communes_async(engine, batch_size=6, max_pages=1)` — builds a flat list of 160 `(ptype, cname, cslug)` tuples (4 types × 40 communes), then iterates in `batch_size` slices using `asyncio.gather(return_exceptions=True)` per batch. `asyncio.sleep(2)` between batches (skipped after final batch). Inner `one_request()` wraps `PortalInmobiliarioScraper.scrape_async()` in try/except so individual failures return 0 rather than propagating.
- `run_parallel(engine=None, batch_size=6, max_pages=1)` — sync wrapper via `asyncio.run()`

The `max_pages=1` default encodes the MeLi constraint: page-1 per commune is publicly accessible; deeper pagination requires session cookies.

### Test Coverage (test_scraping_parallel.py — 17 total, 9 new)

**Toctoc (4 new tests):**
- `test_toctoc_run_parallel_returns_int` — monkeypatch returns 12 per type → total == 48
- `test_toctoc_run_parallel_isolates_failures` — land raises RuntimeError → total == 30 (3×10), no exception propagates
- `test_toctoc_run_parallel_invokes_all_4_types` — seen set == {"apartments", "residential", "land", "retail"}
- `test_toctoc_uses_gather_not_loop` — source file text contains `asyncio.gather` and `return_exceptions=True`

**Portal Inmobiliario (5 new tests):**
- `test_pi_run_parallel_returns_int` — 5 per call × 160 calls == 800
- `test_pi_run_parallel_batch_size_respected` — peak concurrent active <= batch_size=3
- `test_pi_run_parallel_covers_all_160_combinations` — seen == {(pt, cs) for pt in TYPE_MAP for cs in RM_COMMUNES.values()} with len==160
- `test_pi_run_parallel_uses_max_pages_1_default` — all captured max_pages == 1, count == 160
- `test_pi_run_parallel_isolates_failures` — odd-indexed calls raise, no exception propagates, n >= 0

**Full suite result:** 17 passed in 310.91s (test duration dominated by real asyncio.sleep(2) inter-batch delays in batch_size tests)

## Deviations from Plan

None — plan executed exactly as written. The 5 PI tests match the plan's behavior spec. The `test_pi_run_parallel_isolates_failures` implementation used call_count parity (odd/even) rather than commune index to avoid ordering assumptions in concurrent gather execution — this is an implementation detail, not a deviation from the spec.

## Known Stubs

None — both parallel runners are fully implemented. No hardcoded returns, no TODO markers in production code.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes. Both functions are pure scraping wrappers using existing Playwright infrastructure.

## Self-Check: PASSED

- [x] `re_cl/src/scraping/toctoc.py` contains `def run_parallel` (line 273) and `asyncio.gather` (line 255)
- [x] `re_cl/src/scraping/portal_inmobiliario.py` contains `def run_parallel` (line 741), `import asyncio` (line 26), `asyncio.gather` (line 718), `asyncio.sleep(2)` (line 735)
- [x] `re_cl/tests/test_scraping_parallel.py` has 17 tests, all passing
- [x] Commit db2f0d5 (Task 1) verified in git log
- [x] Commit 1285ccc (Task 2) verified in git log
- [x] `py src/scraping/toctoc.py --dry-run` exits 0 (backward compat)
- [x] `py src/scraping/portal_inmobiliario.py --dry-run` exits 0 (backward compat)
- [x] `callable(toctoc.run_parallel)` == True
- [x] `callable(portal_inmobiliario.run_parallel)` == True
