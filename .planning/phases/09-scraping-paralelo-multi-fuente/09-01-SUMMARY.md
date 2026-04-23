---
phase: 09
plan: 01
subsystem: scraping
tags: [foundation, portal-inmobiliario, db-pool, communes, prefect]
completed: "2026-04-22"
duration_minutes: 25

dependency_graph:
  requires:
    - Phase 8 (scraped_listings table must exist)
  provides:
    - RM_COMMUNES with 40 unique entries (Buin + Melipilla added, Bustos removed, duplicate Pudahuel removed)
    - _build_scraper_engine() helper with pool_size=10, max_overflow=5
    - Wave 1 test scaffold (test_scraping_parallel.py, 8 tests)
  affects:
    - re_cl/src/scraping/portal_inmobiliario.py (commune coverage)
    - re_cl/src/pipelines/tasks.py (DB pool capacity for parallel scrapers)

tech_stack:
  added: []
  patterns:
    - SQLAlchemy engine helper pattern (shared _build_scraper_engine for pool config)
    - Prefect task unit testing via .fn bypass + get_run_logger monkeypatch

key_files:
  modified:
    - re_cl/src/scraping/portal_inmobiliario.py
    - re_cl/src/pipelines/tasks.py
  created:
    - re_cl/tests/test_scraping_parallel.py

decisions:
  - "Added Buin and Melipilla (from datainmobiliaria RM_COMMUNE_POLYGONS) rather than only restoring Providencia (already present) — plan's interface block was stale relative to actual file state"
  - "Monkeypatched get_run_logger in pool tests to avoid MissingContextError outside Prefect flow context"
  - "test_scraper_engine_pool_size uses monkeypatched create_engine (not real SQLite) because SQLite rejects pool_size/max_overflow kwargs"

metrics:
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 2
---

# Phase 9 Plan 01: Foundation — RM_COMMUNES Fix + DB Pool Size Summary

**One-liner:** Fixed portal_inmobiliario RM_COMMUNES to 40 unique RM communes (Buin + Melipilla added, Bustos removed, Pudahuel deduplicated) and increased SQLAlchemy pool to pool_size=10/max_overflow=5 via shared _build_scraper_engine() helper.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix RM_COMMUNES + Wave 1 test scaffold | f61ed3e | portal_inmobiliario.py, test_scraping_parallel.py |
| 2 | _build_scraper_engine() + scraper task updates | f61ed3e | tasks.py, test_scraping_parallel.py |

## Pre-flight Result

**Preflight OK:** `scraped_listings` table confirmed present via `docker exec re_cl_db psql`. Phase 8 dependency satisfied.

## What Was Built

### Task 1: RM_COMMUNES fix (portal_inmobiliario.py)

The dict had 3 issues causing exactly 39 unique entries instead of 40:
1. **Duplicate key** — `"Pudahuel": "pudahuel"` appeared twice (lines 70 and 89). Python silently keeps the last value; both were identical so no data loss, but the source code was misleading.
2. **Invalid entry** — `"Bustos": "bustos"` was present. Bustos is an urban district name within a commune, not an RM commune itself; it 404s on MeLi.
3. **Missing communes** — Cross-referencing against `datainmobiliaria.RM_COMMUNE_POLYGONS` (which has exactly 40 RM entries) revealed `Buin` and `Melipilla` were absent.

Note: The plan's context block stated Providencia was missing — but the actual file already had it at line 59. The plan's interface description was stale. The deviation was auto-detected and the correct fix (add Buin + Melipilla) was applied.

### Task 2: _build_scraper_engine() helper (tasks.py)

Added a shared helper immediately after `_build_db_url()`:

```python
def _build_scraper_engine():
    return create_engine(
        _build_db_url(),
        pool_size=10,
        max_overflow=5,
        pool_timeout=30,
        pool_pre_ping=True,
    )
```

Both `task_scrape_portal` and `task_scrape_toctoc` now call `_build_scraper_engine()` instead of the bare `create_engine(_build_db_url(), pool_pre_ping=True)`. The default pool of 5 would exhaust under 6+ concurrent coroutines calling `engine.begin()` in `_write_batch()`.

### Test Scaffold (test_scraping_parallel.py)

8 tests covering Wave 1 assertions:
- `test_rm_communes_has_40_unique_entries` — len == 40
- `test_rm_communes_has_providencia` — "Providencia" present with correct slug
- `test_rm_communes_no_pudahuel_duplicate` — source file has exactly 1 "Pudahuel": line
- `test_rm_communes_all_values_unique` — all 40 slugs are distinct
- `test_rm_communes_no_bustos` — "Bustos" not in dict
- `test_scraper_engine_pool_size` — _build_scraper_engine passes pool_size=10, max_overflow=5
- `test_task_scrape_portal_uses_large_pool` — task uses large pool
- `test_task_scrape_toctoc_uses_large_pool` — task uses large pool

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan interface block described stale file state**
- **Found during:** Task 1 pre-implementation check
- **Issue:** Plan stated "Providencia is NOT currently in the dict — must be ADDED". Actual file had Providencia at line 59. The real missing communes were Buin and Melipilla.
- **Fix:** Added `"Buin": "buin"` and `"Melipilla": "melipilla"` (both in datainmobiliaria.RM_COMMUNE_POLYGONS) instead of re-adding Providencia. Result: 40 unique entries as required.
- **Files modified:** re_cl/src/scraping/portal_inmobiliario.py
- **Commit:** f61ed3e

**2. [Rule 1 - Bug] test_scraper_engine_pool_size used SQLite which rejects pool kwargs**
- **Found during:** Task 2 test run
- **Issue:** `monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")` then calling real `create_engine()` with `pool_size=10, max_overflow=5` — SQLite's StaticPool does not accept these kwargs and raises.
- **Fix:** Switched test to monkeypatch `create_engine` and capture kwargs, then assert captured values. SQLite bypass avoided; test now truly verifies kwargs passed to create_engine.
- **Files modified:** re_cl/tests/test_scraping_parallel.py
- **Commit:** f61ed3e

**3. [Rule 1 - Bug] Prefect get_run_logger() raises MissingContextError outside flow context**
- **Found during:** Task 2 test run (test_task_scrape_portal_uses_large_pool, test_task_scrape_toctoc_uses_large_pool)
- **Issue:** Calling `task.fn()` bypasses Prefect task execution but the function body still calls `get_run_logger()` which requires an active Prefect flow/task run context.
- **Fix:** Added `monkeypatch.setattr("src.pipelines.tasks.get_run_logger", lambda: logging.getLogger("test"))` in both portal and toctoc pool tests.
- **Files modified:** re_cl/tests/test_scraping_parallel.py
- **Commit:** f61ed3e

## Verification Results

```
cd re_cl && py -m pytest tests/test_scraping_parallel.py -v
8 passed in 3.04s

py -c "from src.scraping.portal_inmobiliario import RM_COMMUNES; assert len(RM_COMMUNES)==40"
# exits 0

py -c "from src.pipelines.tasks import _build_scraper_engine; print('OK')"
# OK

docker exec re_cl_db psql -U re_cl_user -d re_cl -c "\dt scraped_listings"
# public | scraped_listings | table | re_cl_user  (1 row)
```

## Known Stubs

None — all functionality is fully implemented.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced.

## Self-Check: PASSED

- [x] `re_cl/src/scraping/portal_inmobiliario.py` exists and len(RM_COMMUNES)==40
- [x] `re_cl/src/pipelines/tasks.py` contains `_build_scraper_engine` (3 occurrences: 1 def + 2 uses)
- [x] `re_cl/tests/test_scraping_parallel.py` exists with 8 tests all passing
- [x] Commit f61ed3e verified in git log
