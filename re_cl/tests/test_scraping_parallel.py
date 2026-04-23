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
