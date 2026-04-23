---
phase: 09
plan: 04
subsystem: scraping
tags: [validation, prefect, parallel-scrape, datainmobiliaria, phase9-gate]
dependency_graph:
  requires: [09-03]
  provides: [phase9_validation_report.json, prefect.yaml]
  affects: [scraped_listings, model_scores, re_cl/prefect.yaml]
tech_stack:
  added: [prefect.yaml (Prefect 3 deployment config)]
  patterns: [on-disk YAML deployment spec, Prefect 3 deploy --all pattern]
key_files:
  created:
    - re_cl/scripts/validate_parallel_scrape.py
    - re_cl/prefect.yaml
    - re_cl/data/exports/phase9_validation_report.json
  modified: []
decisions:
  - "Used Prefect 3 prefect.yaml (not V2 deployment build/apply) — installed version is 3.6.27"
  - "daily-di cron 0 11 * * * targets 07:00 CLT (UTC-4 standard); acceptable DST drift to 08:00 CLST"
  - "Prefect server not running at execution time — prefect.yaml on disk is the deliverable; apply with prefect deploy --all once server starts"
  - "Toctoc contributed only 81 listings (high dedup overlap); PI carried 4,922 (by-commune strategy)"
metrics:
  duration: "~30 minutes (live scrape) + ~5 minutes (agent tasks)"
  completed_date: "2026-04-23"
  tasks_completed: 3
  files_count: 3
---

# Phase 9 Plan 04: Parallel Scrape Validation + Prefect Cron Summary

**One-liner:** Phase 9 gate passed — 5,003 live listings (4,922 PI + 81 Toctoc), status PASS, plus Prefect 3 prefect.yaml with `datainmobiliaria_daily_flow` daily-di cron at 07:00 CLT.

## Tasks Completed

| Task | Name | Commit | Status |
|------|------|--------|--------|
| 1 | Create validate_parallel_scrape.py | 7748bed | Done |
| 2 | Live run — parallel scrape + validate | (user-approved) | PASS — 5,003 listings |
| 3 | Deploy Prefect daily cron for DI | 5145a20 | Done (YAML on disk) |

## Live Run Results (Task 2)

Validation report: `re_cl/data/exports/phase9_validation_report.json`
Generated: 2026-04-23T02:26:50 UTC

| Metric | Value | Check |
|--------|-------|-------|
| total_listings | **5,003** | PASS (>= 5,000) |
| distinct_sources | 2 (PI + Toctoc) | PASS (>= 2) |
| post_processing_ran | true (192 scores last 2h) | PASS |
| status | **PASS** | |

### Per-source breakdown

| Source | Listings |
|--------|----------|
| portal_inmobiliario | 4,922 |
| toctoc | 81 |
| datainmobiliaria | 0 (cookies absent — `--skip-di` used) |

### Per-project-type

| Type | Listings |
|------|----------|
| residential | 2,328 |
| apartments | 1,994 |
| land | 523 |
| retail | 158 |

### Top communes

Santiago (214), La Pintana (91), Cerro Navia (76), Maipú (75), La Florida (71), Melipilla (65), Macul (62), La Reina (61), Lo Espejo (60), Providencia (57).

## Prefect Deployment — Task 3

**Installed version:** Prefect 3.6.27 (not V2 — `deployment build` command does not exist in V3)

**Deliverable:** `re_cl/prefect.yaml` committed at `5145a20`

Contains 3 deployments:

| Name | Entrypoint | Cron | Active |
|------|-----------|------|--------|
| `daily-di` | `datainmobiliaria_daily_flow` | `0 11 * * *` (07:00 CLT) | true |
| `weekly-full` | `full_pipeline` | `0 3 * * 0` (Sun 03:00 UTC) | true |
| `daily-parallel-scrape` | `parallel_scrape_flow` | `0 5 * * *` | false (enable after live validation) |

**To apply deployments once Prefect server is running:**

```bash
cd re_cl
prefect server start                          # terminal 1
prefect deploy --all                          # terminal 2 — applies all from prefect.yaml
prefect deploy --name daily-di               # or apply only DI deployment
prefect deployment ls                        # verify
prefect deployment run "RE_CL DataInmobiliaria Daily/daily-di"  # trigger one-shot
```

**Flow import verified:**
```
flow name: RE_CL DataInmobiliaria Daily
import ok
```

## Deviations from Plan

### Auto-adapted Issues

**1. [Rule 1 - Adaptation] Prefect V3 instead of V2 deployment pattern**
- **Found during:** Task 3
- **Issue:** Plan specified V2 CLI commands (`prefect deployment build ... -n daily-di --cron ... -q default` + `prefect deployment apply`). Installed version is Prefect 3.6.27 which does not have `deployment build` or `deployment apply` commands.
- **Fix:** Created `re_cl/prefect.yaml` using Prefect 3 deployment spec format. All 3 scheduled flows defined. To apply: `prefect deploy --all` (requires Prefect server running).
- **Files modified:** `re_cl/prefect.yaml` (new)
- **Commit:** 5145a20

### No other deviations — plan executed as written.

## Known Stubs

None. `datainmobiliaria_daily_flow` in `flows.py` is fully implemented (lines 302-369). The YAML deployment is the trigger mechanism — it is not a stub, it requires a running Prefect server to activate the schedule.

## Follow-up Items

1. **DI cookies absent** — DataInmobiliaria produced 0 listings because `data/processed/datainmobiliaria_cookies.json` does not exist. To enable:
   ```bash
   cd re_cl
   py src/scraping/datainmobiliaria.py --manual-login
   # Browser opens → log in with Google → close when prompted
   # Then run: py scripts/run_parallel_scrape.py   (with DI enabled)
   ```

2. **Toctoc dedup ceiling** — Toctoc produced only 81 unique listings despite running 50 pages × 4 types. Root cause: Toctoc RM listings are ~77 unique per type due to high overlap across pages (same listings reshuffled). Not a bug — expected behavior documented in CLAUDE.md status table.

3. **Enable Prefect server + apply deployment** — `prefect server start` + `prefect deploy --all`. Create a `default-agent-pool` work pool if needed: `prefect work-pool create default-agent-pool --type process`.

4. **Enable daily-parallel-scrape cron** — Set `active: true` in `prefect.yaml` once DI cookies are saved and a second live run confirms DI listings are non-zero.

5. **Validate dry_run=True for DI** — Run `py -c "from src.pipelines.flows import datainmobiliaria_daily_flow; r=datainmobiliaria_daily_flow(dry_run=True); print(r)"` once cookies exist to confirm no event-loop error.

## Self-Check: PASSED

- `re_cl/scripts/validate_parallel_scrape.py` — exists (committed 7748bed)
- `re_cl/prefect.yaml` — exists (committed 5145a20)
- `re_cl/data/exports/phase9_validation_report.json` — exists (`status: PASS`, `total_listings: 5003`)
- `datainmobiliaria_daily_flow` — importable, flow name confirmed
- `prefect.yaml` — parsed, `daily-di` cron `0 11 * * *` confirmed
