---
phase: 09
plan: 03
subsystem: scraping
tags: [parallel, prefect, threadpoolexecutor, flows, cli, wave-3]
completed: "2026-04-22"
duration_minutes: 30

dependency_graph:
  requires:
    - 09-01 (_build_scraper_engine, RM_COMMUNES 40 entries)
    - 09-02 (portal_inmobiliario.run_parallel, toctoc.run_parallel)
  provides:
    - task_scrape_pi_parallel (Prefect task, module-import pattern)
    - task_scrape_toctoc_parallel (Prefect task, module-import pattern)
    - task_scrape_di_next_commune (Prefect task, manual_login=False)
    - task_normalize_county (Prefect task, inspect-based sig compat)
    - task_score_scraped (Prefect task, inspect-based sig compat)
    - parallel_scrape_flow (PI+Toctoc concurrent via ThreadPoolExecutor)
    - scripts/run_parallel_scrape.py (one-command CLI entry)
  affects:
    - re_cl/src/pipelines/tasks.py (5 new tasks added)
    - re_cl/src/pipelines/flows.py (new flow + CLI choice + imports)
    - re_cl/tests/test_scraping_parallel.py (12 new tests, 29 total)

tech_stack:
  added: []
  patterns:
    - concurrent.futures.ThreadPoolExecutor(max_workers=2) for PI+Toctoc concurrency
    - Module-level import pattern (import src.X as mod) for monkeypatch compatibility
    - inspect.signature() for backward-compatible task wrappers
    - spec_from_file_location for non-package script import in tests

key_files:
  modified:
    - re_cl/src/pipelines/tasks.py
    - re_cl/src/pipelines/flows.py
    - re_cl/tests/test_scraping_parallel.py
  created:
    - re_cl/scripts/run_parallel_scrape.py

decisions:
  - "Used concurrent.futures.ThreadPoolExecutor(max_workers=2) rather than asyncio.gather — each Playwright scraper runs asyncio.run() internally, so two asyncio.run() calls in the same thread would raise RuntimeError; separate threads give each scraper its own event loop"
  - "Module-level imports (import src.X as pi_mod) inside task functions rather than from-imports — ensures monkeypatch.setattr on the module attribute is observed at task call time"
  - "inspect.signature() in task_normalize_county and task_score_scraped for forward/backward compatibility with keyword parameters (dry_run, min_score)"
  - "DI task uses manual_login=False unconditionally — relies on saved cookies; never blocks for interactive login in Prefect context"
  - "spec_from_file_location (not importlib.import_module) for script test — scripts/ has no __init__.py so module path import is fragile across environments"

metrics:
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 3
---

# Phase 9 Plan 03: Wire Prefect Tasks + parallel_scrape_flow + CLI Summary

**One-liner:** Wired Wave 2 parallel runners into 5 Prefect tasks and a new `parallel_scrape_flow` that runs PI+Toctoc concurrently via `ThreadPoolExecutor(max_workers=2)`, then DI sequentially, then normalize+score — all callable from `py scripts/run_parallel_scrape.py`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | 5 Prefect task wrappers in tasks.py | ce6d742 | tasks.py, test_scraping_parallel.py |
| 2 | parallel_scrape_flow + run_parallel_scrape.py CLI | ef9085e | flows.py, run_parallel_scrape.py, test_scraping_parallel.py |

## What Was Built

### Task 1: 5 Prefect task wrappers (tasks.py)

Five new `@task` definitions appended to `tasks.py`:

**`task_scrape_pi_parallel(batch_size=6, max_pages=1) -> int`**
- Imports `src.scraping.portal_inmobiliario` as a module object (not a symbol) so `monkeypatch.setattr(pi_mod, "run_parallel", ...)` is observed at call time
- Calls `_build_scraper_engine()` for pool_size=10 engine
- Retries: 2, delay: 60s

**`task_scrape_toctoc_parallel(max_pages=50) -> int`**
- Same module-import pattern for `src.scraping.toctoc`
- Retries: 2, delay: 60s

**`task_scrape_di_next_commune(min_year=2019, max_pages=100, dry_run=False) -> dict`**
- Calls `di_mod._next_unscraped_commune()` — returns early if all 40 communes done
- Runs `asyncio.run(di_mod.scrape_all(..., manual_login=False, use_checkpoint=True))`
- Never blocks for interactive login; relies on `data/processed/datainmobiliaria_cookies.json`
- Returns `{"commune": str, "rows_written": int, "communes_done": int, "communes_total": int}`
- Retries: 1, delay: 120s

**`task_normalize_county(dry_run=False, min_score=85)`**
- Uses `inspect.signature()` to detect which kwargs `normalize_county()` accepts
- Passes `dry_run` and `min_score` only if present in signature (forward-compat)

**`task_score_scraped(dry_run=False)`**
- Same inspect pattern for `scraped_to_scored.main()`
- Note: the function's parameter is `profile_name` (not `profile`) — inspect handles this transparently

### Task 2: parallel_scrape_flow + CLI (flows.py + run_parallel_scrape.py)

**`parallel_scrape_flow` in `flows.py`:**

```
Stage 1: PI + Toctoc CONCURRENT
  ThreadPoolExecutor(max_workers=2)
    executor.submit(task_scrape_pi_parallel, ...)   → pi_future
    executor.submit(task_scrape_toctoc_parallel, .) → tt_future
  pi_future.result()   # blocks until PI done
  tt_future.result()   # blocks until Toctoc done
  Wall time ≈ max(PI, Toctoc) instead of PI + Toctoc

Stage 2: DI sequential (guest quota per-IP)
  if skip_di: skip
  else: task_scrape_di_next_commune(...)

Stage 3: Post-processing (DB-only)
  task_normalize_county(dry_run=dry_run)
  task_score_scraped(dry_run=dry_run)
```

**CLI additions to `flows.py`:**
- `--flow parallel` added to choices
- `--skip-di`, `--batch-size`, `--max-pages-toctoc` argparse flags added

**`scripts/run_parallel_scrape.py`:**
- Standalone CLI: `py scripts/run_parallel_scrape.py`
- Args: `--batch-size`, `--pi-max-pages`, `--max-pages-toctoc`, `--di-min-year`, `--di-max-pages`, `--skip-di`, `--dry-run`
- Imports `parallel_scrape_flow` and prints structured result log

### Test Coverage (test_scraping_parallel.py — 29 total, 12 new in Wave 3)

**Task 1 tests (7 new):**
- `test_task_scrape_pi_parallel_exists` — `.fn` callable
- `test_task_scrape_toctoc_parallel_exists` — `.fn` callable
- `test_task_scrape_di_next_commune_exists` — `.fn` callable
- `test_task_normalize_county_exists` — `.fn` callable
- `test_task_score_scraped_exists` — `.fn` callable
- `test_task_pi_parallel_calls_run_parallel` — monkeypatch verifies engine=sentinel, batch_size=3
- `test_task_di_uses_saved_cookies_no_manual_login` — asserts `manual_login=False`, `use_checkpoint=True`

**Task 2 tests (5 new):**
- `test_parallel_scrape_flow_exists` — `callable(parallel_scrape_flow)`
- `test_parallel_scrape_flow_uses_threadpoolexecutor` — source contains "ThreadPoolExecutor"
- `test_parallel_scrape_flow_submits_pi_and_toctoc_concurrently` — FakeExecutor captures 2 submit calls, both PI+Toctoc names present
- `test_parallel_scrape_flow_skip_di_flag` — DI not called when `skip_di=True`, PI+Toctoc still submitted
- `test_run_parallel_scrape_script_importable` — `spec_from_file_location` loads script, `main` callable

## Deviations from Plan

None — plan executed exactly as written. All interfaces matched the verified signatures. The `scraped_to_scored.main()` parameter is `profile_name` (not `profile` as the plan's interface block noted), but this is handled transparently by the inspect-based wrapper (only `dry_run` is forwarded).

## Known Stubs

None — all 5 tasks and the flow are fully implemented. No hardcoded returns or TODO markers in production code.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced. The `run_parallel_scrape.py` script is a local CLI wrapper; it does not expose any new surface.

## Self-Check: PASSED

- [x] `re_cl/src/pipelines/tasks.py` contains `def task_scrape_pi_parallel` (1 line)
- [x] `re_cl/src/pipelines/tasks.py` contains `def task_scrape_toctoc_parallel` (1 line)
- [x] `re_cl/src/pipelines/tasks.py` contains `def task_scrape_di_next_commune` (1 line)
- [x] `re_cl/src/pipelines/tasks.py` contains `def task_normalize_county` (1 line)
- [x] `re_cl/src/pipelines/tasks.py` contains `def task_score_scraped` (1 line)
- [x] `re_cl/src/pipelines/tasks.py` contains `manual_login=False` (DI task)
- [x] `re_cl/src/pipelines/flows.py` contains `def parallel_scrape_flow` (1 line)
- [x] `re_cl/src/pipelines/flows.py` contains `ThreadPoolExecutor` (import + usage)
- [x] `re_cl/src/pipelines/flows.py` contains `import concurrent.futures` (1 line)
- [x] `re_cl/scripts/run_parallel_scrape.py` exists with `def main`
- [x] Commit ce6d742 verified (Task 1)
- [x] Commit ef9085e verified (Task 2)
- [x] `py -m pytest tests/test_scraping_parallel.py -v` → 29 passed
- [x] `py -c "from src.pipelines.flows import parallel_scrape_flow; print('ok')"` exits 0
- [x] `py -c "from src.pipelines.tasks import task_scrape_pi_parallel, ..."` exits 0
- [x] `py -c "assert 'ThreadPoolExecutor' in inspect.getsource(parallel_scrape_flow)"` exits 0
- [x] `py scripts/run_parallel_scrape.py --help` prints all flags
