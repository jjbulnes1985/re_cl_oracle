"""
test_scoring.py
---------------
Tests for opportunity_score.py computation logic.
Uses synthetic fixtures — no real DB or model required.
"""

import json

import numpy as np
import pandas as pd
import pytest

from src.scoring.opportunity_score import compute_opportunity_score


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_score_input(n=50, uv_seed=1, conf_seed=2) -> pd.DataFrame:
    """Synthetic DataFrame with undervaluation_score and data_confidence."""
    rng = np.random.default_rng(uv_seed)
    return pd.DataFrame({
        "id":                  range(1, n + 1),
        "undervaluation_score": rng.uniform(0.0, 1.0, n).round(4),
        "data_confidence":      np.random.default_rng(conf_seed).uniform(0.4, 1.0, n).round(4),
    })


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestComputeOpportunityScore:
    def test_output_in_unit_interval(self):
        df = make_score_input(100)
        result = compute_opportunity_score(df)
        valid = result["opportunity_score"].dropna()
        assert (valid >= 0.0).all(), "Scores below 0"
        assert (valid <= 1.0).all(), "Scores above 1"

    def test_all_rows_scored_when_no_nulls(self):
        df = make_score_input(60)
        result = compute_opportunity_score(df)
        assert result["opportunity_score"].notna().all()

    def test_null_undervaluation_produces_null_score(self):
        df = make_score_input(10)
        df.loc[0, "undervaluation_score"] = None
        result = compute_opportunity_score(df)
        assert pd.isna(result.loc[0, "opportunity_score"])

    def test_null_confidence_produces_null_score(self):
        df = make_score_input(10)
        df.loc[3, "data_confidence"] = None
        result = compute_opportunity_score(df)
        assert pd.isna(result.loc[3, "opportunity_score"])

    def test_weights_sum_correctly(self):
        """Score for perfect property (both inputs = 1.0) must be 1.0."""
        df = pd.DataFrame({
            "id": [1],
            "undervaluation_score": [1.0],
            "data_confidence": [1.0],
        })
        result = compute_opportunity_score(df)
        assert result.loc[0, "opportunity_score"] == pytest.approx(1.0, abs=1e-4)

    def test_zero_inputs_produce_zero_score(self):
        df = pd.DataFrame({
            "id": [1],
            "undervaluation_score": [0.0],
            "data_confidence": [0.0],
        })
        result = compute_opportunity_score(df)
        assert result.loc[0, "opportunity_score"] == pytest.approx(0.0, abs=1e-4)

    def test_scores_rounded_to_4_decimals(self):
        df = make_score_input(20)
        result = compute_opportunity_score(df)
        valid = result["opportunity_score"].dropna()
        # No value should have more than 4 decimal places
        for v in valid:
            assert v == round(v, 4)

    def test_higher_undervaluation_gives_higher_score(self):
        """Holding confidence constant, higher undervaluation → higher score."""
        df = pd.DataFrame({
            "id": [1, 2],
            "undervaluation_score": [0.2, 0.8],
            "data_confidence": [0.5, 0.5],
        })
        result = compute_opportunity_score(df)
        assert result.loc[1, "opportunity_score"] > result.loc[0, "opportunity_score"]

    def test_monotone_in_confidence(self):
        """Holding undervaluation constant, higher confidence → higher score."""
        df = pd.DataFrame({
            "id": [1, 2],
            "undervaluation_score": [0.6, 0.6],
            "data_confidence": [0.3, 0.9],
        })
        result = compute_opportunity_score(df)
        assert result.loc[1, "opportunity_score"] > result.loc[0, "opportunity_score"]

    def test_correlation_with_undervaluation(self):
        """Opportunity score should be strongly correlated with undervaluation_score."""
        df = make_score_input(200)
        result = compute_opportunity_score(df)
        corr = result["opportunity_score"].corr(result["undervaluation_score"])
        assert corr > 0.8, f"Expected correlation > 0.8, got {corr:.3f}"

    def test_original_df_not_mutated(self):
        df = make_score_input(30)
        original_cols = set(df.columns)
        _ = compute_opportunity_score(df)
        assert set(df.columns) == original_cols, "compute_opportunity_score mutated input df"


class TestShapFormat:
    """Test SHAP output format expectations (without running actual model)."""

    def test_shap_feature_structure(self):
        shap_record = [
            {"feature": "county_name", "shap": -0.42, "direction": "down"},
            {"feature": "dist_km_centroid", "shap": 0.18, "direction": "up"},
            {"feature": "surface_m2", "shap": -0.11, "direction": "down"},
        ]
        json_str = json.dumps(shap_record)
        parsed = json.loads(json_str)

        assert len(parsed) == 3
        for item in parsed:
            assert "feature" in item
            assert "shap" in item
            assert "direction" in item
            assert item["direction"] in ("up", "down")
            assert isinstance(item["shap"], float)

    def test_shap_direction_matches_sign(self):
        records = [
            {"feature": "f1", "shap": 0.3,  "direction": "up"},
            {"feature": "f2", "shap": -0.1, "direction": "down"},
        ]
        for r in records:
            if r["shap"] > 0:
                assert r["direction"] == "up"
            else:
                assert r["direction"] == "down"
