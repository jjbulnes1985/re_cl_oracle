---
phase: 9
slug: phase-9-scraping-paralelo-multi-fuente-sin-credenciales
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-22
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (already configured) |
| **Config file** | `re_cl/` (run from re_cl/ directory) |
| **Quick run command** | `cd re_cl && pytest tests/test_scraping_parallel.py -v` |
| **Full suite command** | `cd re_cl && pytest tests/ -v` |
| **Estimated runtime** | ~30 seconds (unit tests only, no live browser) |

---

## Sampling Rate

- **After every task commit:** `pytest tests/test_scraping_parallel.py -x`
- **After every plan wave:** `cd re_cl && pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green + `SELECT COUNT(*) FROM scraped_listings` > 5000
- **Max feedback latency:** ~30 seconds (unit), ~90 min (live scrape)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| 09-01-01 | 01 | 1 | PI RM_COMMUNES 40 unique entries | unit | `pytest tests/test_scraping_parallel.py::test_rm_communes_no_duplicates -x` | ⬜ pending |
| 09-01-02 | 01 | 1 | DB engine pool_size=10 | unit | `pytest tests/test_scraping_parallel.py::test_engine_pool_size -x` | ⬜ pending |
| 09-02-01 | 02 | 2 | Toctoc 4 types run concurrently via asyncio.gather | unit | `pytest tests/test_scraping_parallel.py::test_toctoc_parallel_returns_int -x` | ⬜ pending |
| 09-02-02 | 02 | 2 | PI 160 requests in batches via asyncio.gather | unit | `pytest tests/test_scraping_parallel.py::test_pi_batch_splits_correctly -x` | ⬜ pending |
| 09-03-01 | 03 | 3 | Prefect tasks for normalize + score exist | unit | `pytest tests/test_scraping_parallel.py::test_task_normalize_county_exists -x` | ⬜ pending |
| 09-03-02 | 03 | 3 | run_parallel_scrape.py CLI entrypoint | unit | `cd re_cl && py scripts/run_parallel_scrape.py --help` | ⬜ pending |
| 09-04-01 | 04 | 4 | validate_parallel_scrape.py exists | unit | `cd re_cl && py scripts/validate_parallel_scrape.py --help` | ⬜ pending |
| 09-04-02 | 04 | 4 | >5000 listings in scraped_listings | integration | Manual: `psql -c "SELECT COUNT(*) FROM scraped_listings"` | ⬜ pending |
| 09-04-03 | 04 | 4 | DI 402 quota handled gracefully | unit | `pytest tests/test_scraping_parallel.py::test_di_quota_exhausted_handled -x` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `re_cl/tests/test_scraping_parallel.py` — new file; covers all 9 test cases above (no live browser needed for units)
- [ ] No new framework install needed — pytest already configured in re_cl/

---

## Phase Gate Criteria

All of the following must be true before Phase 9 is marked complete:

1. `cd re_cl && pytest tests/ -v` — 0 failures (all 296 + new parallel tests pass)
2. `SELECT COUNT(*) FROM scraped_listings` — returns > 5000
3. `py scripts/run_parallel_scrape.py --help` — exits 0
4. `py scripts/validate_parallel_scrape.py --help` — exits 0
5. `prefect deployment inspect datainmobiliaria-daily` — shows cron schedule
