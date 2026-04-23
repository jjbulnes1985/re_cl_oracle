"""Tests for Phase 9 parallel scraping foundation + wrappers."""
import re
from pathlib import Path
import pytest


# ── Task 1: RM_COMMUNES integrity ──────────────────────────────────────────────

def test_rm_communes_has_40_unique_entries():
    from src.scraping.portal_inmobiliario import RM_COMMUNES
    assert len(RM_COMMUNES) == 40, f"Expected 40 unique communes, got {len(RM_COMMUNES)}"


def test_rm_communes_has_providencia():
    from src.scraping.portal_inmobiliario import RM_COMMUNES
    assert "Providencia" in RM_COMMUNES
    assert RM_COMMUNES["Providencia"] == "providencia"


def test_rm_communes_no_pudahuel_duplicate():
    src = Path(__file__).resolve().parents[1] / "src" / "scraping" / "portal_inmobiliario.py"
    text = src.read_text(encoding="utf-8")
    # Count how many times "Pudahuel": appears as a dict key (allow any leading whitespace)
    count = len(re.findall(r'^\s*"Pudahuel"\s*:', text, re.MULTILINE))
    assert count == 1, f'"Pudahuel": appears {count} times in portal_inmobiliario.py — should be exactly 1'


def test_rm_communes_all_values_unique():
    from src.scraping.portal_inmobiliario import RM_COMMUNES
    assert len(set(RM_COMMUNES.values())) == 40


def test_rm_communes_no_bustos():
    from src.scraping.portal_inmobiliario import RM_COMMUNES
    assert "Bustos" not in RM_COMMUNES, "'Bustos' is not an RM commune and must not be in RM_COMMUNES"


# ── Task 2: DB pool size stubs (will be implemented in Task 2) ─────────────────

def test_scraper_engine_pool_size(monkeypatch):
    from src.pipelines import tasks as t
    captured = {}

    class _FakeEngine:
        pass

    def fake_create(url, **kw):
        captured.update(kw)
        return _FakeEngine()

    monkeypatch.setattr(t, "create_engine", fake_create)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@localhost/re_cl")
    engine = t._build_scraper_engine()
    assert engine is not None
    assert captured.get("pool_size") == 10, f"pool_size expected 10, got {captured.get('pool_size')}"
    assert captured.get("max_overflow") == 5, f"max_overflow expected 5, got {captured.get('max_overflow')}"
    assert captured.get("pool_pre_ping") is True


def test_task_scrape_portal_uses_large_pool(monkeypatch):
    import logging
    from src.pipelines import tasks as t
    captured = {}

    class _FakeEngine:
        def dispose(self):
            pass

    def fake_create(url, **kw):
        captured.update(kw)
        return _FakeEngine()

    monkeypatch.setattr(t, "create_engine", fake_create)
    # Prefect's get_run_logger() requires an active flow/task context; stub it out
    monkeypatch.setattr("src.pipelines.tasks.get_run_logger", lambda: logging.getLogger("test"))
    # Stub the actual scrape_run to avoid Playwright launch
    monkeypatch.setattr("src.scraping.portal_inmobiliario.run", lambda **kw: 0)
    t.task_scrape_portal.fn(max_pages=1)
    assert captured.get("pool_size") == 10, f"pool_size expected 10, got {captured.get('pool_size')}"
    assert captured.get("max_overflow") == 5, f"max_overflow expected 5, got {captured.get('max_overflow')}"


def test_task_scrape_toctoc_uses_large_pool(monkeypatch):
    import logging
    from src.pipelines import tasks as t
    captured = {}

    class _FakeEngine:
        def dispose(self):
            pass

    def fake_create(url, **kw):
        captured.update(kw)
        return _FakeEngine()

    monkeypatch.setattr(t, "create_engine", fake_create)
    # Prefect's get_run_logger() requires an active flow/task context; stub it out
    monkeypatch.setattr("src.pipelines.tasks.get_run_logger", lambda: logging.getLogger("test"))
    # Stub the actual scrape_run to avoid Playwright launch
    monkeypatch.setattr("src.scraping.toctoc.run", lambda **kw: 0)
    t.task_scrape_toctoc.fn(max_pages=1)
    assert captured.get("pool_size") == 10, f"pool_size expected 10, got {captured.get('pool_size')}"
    assert captured.get("max_overflow") == 5, f"max_overflow expected 5, got {captured.get('max_overflow')}"


# ── Task 1 (Wave 2): toctoc.run_parallel() ────────────────────────────────────

def test_toctoc_run_parallel_returns_int(monkeypatch):
    from src.scraping import toctoc

    async def fake_scrape_async(self, max_pages=50, property_type="apartments", **kw):
        return 12

    monkeypatch.setattr(toctoc.ToctocScraper, "scrape_async", fake_scrape_async)
    n = toctoc.run_parallel(engine=None, max_pages=1)
    assert isinstance(n, int)
    assert n == 48  # 12 × 4 types


def test_toctoc_run_parallel_isolates_failures(monkeypatch):
    from src.scraping import toctoc

    async def fake_scrape_async(self, max_pages=50, property_type="apartments", **kw):
        if property_type == "land":
            raise RuntimeError("simulated land failure")
        return 10

    monkeypatch.setattr(toctoc.ToctocScraper, "scrape_async", fake_scrape_async)
    n = toctoc.run_parallel(engine=None, max_pages=1)
    assert n == 30  # 3 successful × 10


def test_toctoc_run_parallel_invokes_all_4_types(monkeypatch):
    from src.scraping import toctoc

    seen = []

    async def fake_scrape_async(self, max_pages=50, property_type="apartments", **kw):
        seen.append(property_type)
        return 1

    monkeypatch.setattr(toctoc.ToctocScraper, "scrape_async", fake_scrape_async)
    toctoc.run_parallel(engine=None, max_pages=1)
    assert set(seen) == {"apartments", "residential", "land", "retail"}


def test_toctoc_uses_gather_not_loop():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "src" / "scraping" / "toctoc.py"
    text = src.read_text(encoding="utf-8")
    assert "asyncio.gather" in text
    assert "return_exceptions=True" in text


# ── Task 2 (Wave 2): portal_inmobiliario.run_parallel() ───────────────────────

def test_pi_run_parallel_returns_int(monkeypatch):
    from src.scraping import portal_inmobiliario as pi

    async def fake_scrape_async(self, max_pages=1, property_type="apartments", commune_slug="", **kw):
        return 5

    monkeypatch.setattr(pi.PortalInmobiliarioScraper, "scrape_async", fake_scrape_async)
    n = pi.run_parallel(engine=None, batch_size=8, max_pages=1)
    assert isinstance(n, int)
    assert n == 800  # 5 × 40 communes × 4 types


def test_pi_run_parallel_batch_size_respected(monkeypatch):
    import asyncio as _aio
    from src.scraping import portal_inmobiliario as pi

    state = {"active": 0, "peak": 0}

    async def fake_scrape_async(self, max_pages=1, property_type="apartments", commune_slug="", **kw):
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        await _aio.sleep(0.01)
        state["active"] -= 1
        return 1

    monkeypatch.setattr(pi.PortalInmobiliarioScraper, "scrape_async", fake_scrape_async)
    state["peak"] = 0
    pi.run_parallel(engine=None, batch_size=3, max_pages=1)
    assert state["peak"] <= 3


def test_pi_run_parallel_covers_all_160_combinations(monkeypatch):
    from src.scraping import portal_inmobiliario as pi

    seen = set()

    async def fake_scrape_async(self, max_pages=1, property_type="apartments", commune_slug="", **kw):
        seen.add((property_type, commune_slug))
        return 0

    monkeypatch.setattr(pi.PortalInmobiliarioScraper, "scrape_async", fake_scrape_async)
    pi.run_parallel(engine=None, batch_size=6, max_pages=1)
    expected = {(pt, cs) for pt in pi.TYPE_MAP.keys() for cs in pi.RM_COMMUNES.values()}
    assert seen == expected
    assert len(seen) == 160


def test_pi_run_parallel_uses_max_pages_1_default(monkeypatch):
    from src.scraping import portal_inmobiliario as pi

    captured = []

    async def fake_scrape_async(self, max_pages=1, property_type="apartments", commune_slug="", **kw):
        captured.append(max_pages)
        return 0

    monkeypatch.setattr(pi.PortalInmobiliarioScraper, "scrape_async", fake_scrape_async)
    pi.run_parallel(engine=None)  # default max_pages=1
    assert all(mp == 1 for mp in captured)
    assert len(captured) == 160


def test_pi_run_parallel_isolates_failures(monkeypatch):
    from src.scraping import portal_inmobiliario as pi

    call_count = [0]

    async def fake_scrape_async(self, max_pages=1, property_type="apartments", commune_slug="", **kw):
        call_count[0] += 1
        if call_count[0] % 2 == 0:
            raise RuntimeError("simulated failure")
        return 3

    monkeypatch.setattr(pi.PortalInmobiliarioScraper, "scrape_async", fake_scrape_async)
    # Should not raise; returns count only from successful calls
    n = pi.run_parallel(engine=None, batch_size=6, max_pages=1)
    assert isinstance(n, int)
    assert n >= 0  # some successes, no exception propagated


# ── Wave 3 Task 1: Prefect task wrappers ─────────────────────────────────────

def test_task_scrape_pi_parallel_exists():
    from src.pipelines.tasks import task_scrape_pi_parallel
    assert callable(task_scrape_pi_parallel.fn)


def test_task_scrape_toctoc_parallel_exists():
    from src.pipelines.tasks import task_scrape_toctoc_parallel
    assert callable(task_scrape_toctoc_parallel.fn)


def test_task_scrape_di_next_commune_exists():
    from src.pipelines.tasks import task_scrape_di_next_commune
    assert callable(task_scrape_di_next_commune.fn)


def test_task_normalize_county_exists():
    from src.pipelines.tasks import task_normalize_county
    assert callable(task_normalize_county.fn)


def test_task_score_scraped_exists():
    from src.pipelines.tasks import task_score_scraped
    assert callable(task_score_scraped.fn)


def test_task_pi_parallel_calls_run_parallel(monkeypatch):
    import logging
    from src.pipelines import tasks as t
    import src.scraping.portal_inmobiliario as pi_mod
    sentinel = object()
    captured = {}
    monkeypatch.setattr(t, "_build_scraper_engine", lambda: sentinel)
    monkeypatch.setattr("src.pipelines.tasks.get_run_logger", lambda: logging.getLogger("test"))

    def fake_rp(engine=None, batch_size=6, max_pages=1):
        captured["engine"] = engine
        captured["batch_size"] = batch_size
        captured["max_pages"] = max_pages
        return 99

    # Rebind the attribute on the module object — the task re-imports the
    # module via `import src.scraping.portal_inmobiliario as pi_mod` so it
    # sees the patched attribute at call time.
    monkeypatch.setattr(pi_mod, "run_parallel", fake_rp)
    n = t.task_scrape_pi_parallel.fn(batch_size=3, max_pages=1)
    assert n == 99
    assert captured["engine"] is sentinel
    assert captured["batch_size"] == 3
    assert captured["max_pages"] == 1


def test_task_di_uses_saved_cookies_no_manual_login(monkeypatch):
    import logging
    from src.pipelines import tasks as t
    import src.scraping.datainmobiliaria as di_mod
    captured = {}
    monkeypatch.setattr(t, "_build_scraper_engine", lambda: object())
    monkeypatch.setattr("src.pipelines.tasks.get_run_logger", lambda: logging.getLogger("test"))
    monkeypatch.setattr(di_mod, "_next_unscraped_commune", lambda: "Las Condes")
    monkeypatch.setattr(di_mod, "_load_checkpoint", lambda: {})

    async def fake_scrape_all(engine, communes, **kw):
        captured.update(kw)
        captured["communes"] = communes
        return 42

    monkeypatch.setattr(di_mod, "scrape_all", fake_scrape_all)
    result = t.task_scrape_di_next_commune.fn(min_year=2019, max_pages=10)
    assert captured.get("manual_login") is False
    assert captured.get("use_checkpoint") is True
    assert captured.get("communes") == ["Las Condes"]
    assert result["commune"] == "Las Condes"
    assert result["rows_written"] == 42
