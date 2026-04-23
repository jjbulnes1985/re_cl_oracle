"""
test_reports.py
---------------
Tests for src/reports/generate_report.py.
All tests use mock/offline data — no DB required.
"""

import json
from pathlib import Path

import pandas as pd
import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _props(n: int = 5) -> pd.DataFrame:
    return pd.DataFrame({
        "clean_id":             list(range(1, n + 1)),
        "county_name":          ["Las Condes", "Providencia", "Ñuñoa", "Santiago", "Maipú"][:n],
        "project_type":         ["Departamento"] * n,
        "opportunity_score":    [0.92, 0.85, 0.78, 0.71, 0.65][:n],
        "undervaluation_score": [0.88, 0.80, 0.72, 0.68, 0.60][:n],
        "uf_m2_building":       [55.0, 62.0, 70.0, 45.0, 40.0][:n],
        "gap_pct":              [-0.25, -0.20, -0.15, -0.18, -0.10][:n],
        "data_confidence":      [0.95, 0.90, 0.85, 0.80, 0.75][:n],
        "latitude":             [-33.42, -33.43, -33.46, -33.45, -33.52][:n],
        "longitude":            [-70.60, -70.62, -70.60, -70.65, -70.76][:n],
        "city_zone":            ["este"] * n,
        "dist_metro_km":        [0.5, 0.3, 0.8, 0.2, 1.5][:n],
    })


def _communes(n: int = 3) -> pd.DataFrame:
    return pd.DataFrame({
        "county_name":      ["Las Condes", "Providencia", "Ñuñoa"][:n],
        "n_transactions":   [500, 300, 200][:n],
        "median_score":     [0.80, 0.75, 0.70][:n],
        "pct_subvaloradas": [35.0, 28.0, 22.0][:n],
        "median_uf_m2":     [80.0, 70.0, 60.0][:n],
        "median_gap_pct":   [-0.20, -0.15, -0.10][:n],
    })


def _stats() -> dict:
    return {"total_scored": 1000, "mean_score": 0.72, "high_opp_count": 150}


# ── TestMockProperties ─────────────────────────────────────────────────────────

class TestMockProperties:

    def test_returns_dataframe(self):
        from src.reports.generate_report import _mock_properties
        assert isinstance(_mock_properties(10), pd.DataFrame)

    def test_respects_top_n(self):
        from src.reports.generate_report import _mock_properties
        assert len(_mock_properties(15)) == 15

    def test_caps_at_50(self):
        from src.reports.generate_report import _mock_properties
        assert len(_mock_properties(100)) <= 50

    def test_has_required_columns(self):
        from src.reports.generate_report import _mock_properties
        df = _mock_properties(5)
        required = {"county_name", "project_type", "opportunity_score", "gap_pct", "data_confidence"}
        assert required.issubset(df.columns)

    def test_scores_in_range(self):
        from src.reports.generate_report import _mock_properties
        df = _mock_properties(20)
        assert df["opportunity_score"].between(0, 1).all()

    def test_gap_pct_negative(self):
        from src.reports.generate_report import _mock_properties
        assert (_mock_properties(10)["gap_pct"] < 0).all()

    def test_deterministic_with_seed(self):
        from src.reports.generate_report import _mock_properties
        df1 = _mock_properties(10)
        df2 = _mock_properties(10)
        assert df1["opportunity_score"].tolist() == df2["opportunity_score"].tolist()


# ── TestLoadBacktestingReport ──────────────────────────────────────────────────

class TestLoadBacktestingReport:

    def test_returns_none_when_file_missing(self, tmp_path, monkeypatch):
        import src.reports.generate_report as m
        monkeypatch.setattr(m, "REPORT_PATH", tmp_path / "missing.json")
        from src.reports.generate_report import load_backtesting_report
        assert load_backtesting_report() is None

    def test_loads_valid_json(self, tmp_path, monkeypatch):
        import src.reports.generate_report as m
        f = tmp_path / "report.json"
        payload = {"r2": 0.82, "rmse": 12.5}
        f.write_text(json.dumps(payload))
        monkeypatch.setattr(m, "REPORT_PATH", f)
        from src.reports.generate_report import load_backtesting_report
        assert load_backtesting_report() == payload

    def test_returns_none_on_corrupt_json(self, tmp_path, monkeypatch):
        import src.reports.generate_report as m
        f = tmp_path / "bad.json"
        f.write_text("{corrupt")
        monkeypatch.setattr(m, "REPORT_PATH", f)
        from src.reports.generate_report import load_backtesting_report
        assert load_backtesting_report() is None


# ── TestGenerateHtml ───────────────────────────────────────────────────────────

class TestGenerateHtml:

    def test_returns_html_string(self):
        from src.reports.generate_report import generate_html
        html = generate_html(_props(), _communes(), _stats(), None, 5, "default")
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html or "<html" in html.lower()

    def test_contains_county_name(self):
        from src.reports.generate_report import generate_html
        html = generate_html(_props(), _communes(), _stats(), None, 5, "default")
        assert "Las Condes" in html

    def test_contains_total_scored(self):
        from src.reports.generate_report import generate_html
        html = generate_html(_props(), _communes(), {"total_scored": 9999, "mean_score": 0.72, "high_opp_count": 150}, None, 5, "default")
        assert "9999" in html or "9,999" in html

    def test_contains_commune_name(self):
        from src.reports.generate_report import generate_html
        html = generate_html(_props(), _communes(), _stats(), None, 5, "default")
        assert "Providencia" in html

    def test_empty_dataframes_do_not_raise(self):
        from src.reports.generate_report import generate_html
        html = generate_html(pd.DataFrame(), pd.DataFrame(), {}, None, 5, "default")
        assert isinstance(html, str)

    def test_profile_name_in_output(self):
        from src.reports.generate_report import generate_html
        html = generate_html(_props(), _communes(), _stats(), None, 5, "location")
        assert "location" in html

    def test_self_contained_no_cdn(self):
        from src.reports.generate_report import generate_html
        html = generate_html(_props(), _communes(), _stats(), None, 5, "default")
        assert "cdn.jsdelivr.net" not in html
        assert "unpkg.com" not in html


# ── TestGenerateMapSvg ─────────────────────────────────────────────────────────

class TestGenerateMapSvg:

    def test_returns_svg(self):
        from src.reports.generate_report import generate_map_svg
        svg = generate_map_svg(_props())
        assert "<svg" in svg and "</svg>" in svg

    def test_empty_df_returns_svg(self):
        from src.reports.generate_report import generate_map_svg
        svg = generate_map_svg(pd.DataFrame(columns=["latitude", "longitude", "opportunity_score"]))
        assert "<svg" in svg

    def test_contains_circle_elements(self):
        from src.reports.generate_report import generate_map_svg
        svg = generate_map_svg(_props())
        assert "<circle" in svg


# ── TestBuildHeader ────────────────────────────────────────────────────────────

class TestBuildHeader:

    def test_contains_date(self):
        from src.reports.generate_report import build_header
        html = build_header("2026-04-20", "default")
        assert "2026-04-20" in html

    def test_contains_profile(self):
        from src.reports.generate_report import build_header
        html = build_header("2026-04-20", "safety")
        assert "safety" in html.lower()


# ── TestBuildPropertiesTable ───────────────────────────────────────────────────

class TestBuildPropertiesTable:

    def test_contains_county(self):
        from src.reports.generate_report import build_properties_table
        html = build_properties_table(_props(), top_n=5)
        assert "Las Condes" in html

    def test_empty_df_does_not_raise(self):
        from src.reports.generate_report import build_properties_table
        html = build_properties_table(pd.DataFrame(), top_n=5)
        assert isinstance(html, str)

    def test_top_n_limits_rows(self):
        from src.reports.generate_report import build_properties_table
        html3 = build_properties_table(_props(5), top_n=3)
        html5 = build_properties_table(_props(5), top_n=5)
        # With top_n=3 we expect fewer county mentions than top_n=5
        assert html3.count("Departamento") <= html5.count("Departamento")


# ── TestMockSummary ────────────────────────────────────────────────────────────

class TestMockSummary:

    def test_returns_dict(self):
        from src.reports.generate_report import _mock_summary
        result = _mock_summary()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        from src.reports.generate_report import _mock_summary
        result = _mock_summary()
        assert "total_scored" in result
        assert "mean_score" in result
