"""
tests/test_alerts.py
--------------------
Tests for webhook alert functionality in src/alerts/notifier.py.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make project root importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts.notifier import send_alert, send_webhook


# ── send_webhook unit tests ────────────────────────────────────────────────────

class TestSendWebhook:

    def test_send_webhook_posts_correct_payload(self):
        """send_webhook POSTs JSON with all required keys to the given URL."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_response) as mock_post:
            result = send_webhook(
                title="Test title",
                body="Test body",
                level="warning",
                url="https://hooks.example.com/re_cl",
            )

        assert result is True
        mock_post.assert_called_once()

        _, kwargs = mock_post.call_args
        payload = kwargs["json"]

        assert payload["title"] == "Test title"
        assert payload["body"] == "Test body"
        assert payload["level"] == "warning"
        assert payload["source"] == "re_cl"
        assert "timestamp" in payload

    def test_send_webhook_silently_ignores_connection_error(self):
        """send_webhook returns False and does not raise on ConnectionError."""
        with patch("requests.post", side_effect=ConnectionError("refused")):
            result = send_webhook(
                title="Title",
                body="Body",
                level="warning",
                url="https://hooks.example.com/re_cl",
            )

        assert result is False

    def test_send_webhook_not_called_when_no_url(self, monkeypatch):
        """send_alert does not call requests.post when ALERT_WEBHOOK_URL is unset."""
        monkeypatch.setattr("src.alerts.notifier.ALERT_WEBHOOK_URL", "")

        with patch("requests.post") as mock_post:
            send_alert("No webhook", "Should not POST", level="warning")

        mock_post.assert_not_called()

    def test_send_webhook_includes_timestamp(self):
        """Webhook payload timestamp is a valid ISO 8601 string."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_response) as mock_post:
            send_webhook(
                title="Timestamp test",
                body="Body",
                level="info",
                url="https://hooks.example.com/re_cl",
            )

        _, kwargs = mock_post.call_args
        ts = kwargs["json"]["timestamp"]

        # Must parse without error and be timezone-aware (contains + or Z)
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None

    def test_send_webhook_called_when_url_set(self, monkeypatch):
        """send_alert delegates to send_webhook when ALERT_WEBHOOK_URL is configured."""
        monkeypatch.setattr(
            "src.alerts.notifier.ALERT_WEBHOOK_URL",
            "https://hooks.example.com/re_cl",
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_response) as mock_post:
            send_alert("Alert with webhook", "Body text", level="warning")

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["source"] == "re_cl"

    def test_send_webhook_uses_timeout_5(self):
        """requests.post is called with timeout=5."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None

        with patch("requests.post", return_value=mock_response) as mock_post:
            send_webhook("T", "B", "info", "https://hooks.example.com/re_cl")

        _, kwargs = mock_post.call_args
        assert kwargs["timeout"] == 5

    def test_send_webhook_silently_ignores_http_error(self):
        """send_webhook returns False and does not raise on HTTP 4xx/5xx."""
        import requests as req_lib

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = req_lib.HTTPError("500")

        with patch("requests.post", return_value=mock_response):
            result = send_webhook("T", "B", "critical", "https://hooks.example.com/re_cl")

        assert result is False


# ── TestFormatAlertRow ─────────────────────────────────────────────────────────

import json

def _sample_alert(**overrides) -> dict:
    base = {
        "score_id": 1, "opportunity_score": 0.85, "undervaluation_score": 0.78,
        "gap_pct": -0.20, "data_confidence": 0.90, "predicted_uf_m2": 80.0,
        "actual_uf_m2": 64.0, "county_name": "Las Condes",
        "project_type": "Departamento", "price_uf": None, "surface_m2": 70.0,
        "url": "https://example.com/prop/1", "source": "cbr",
        "scored_at": "2026-04-20T12:00:00", "shap_top_features": None,
    }
    return {**base, **overrides}


class TestFormatAlertRow:

    def test_returns_string(self):
        from src.alerts.notifier import format_alert_row
        assert isinstance(format_alert_row(_sample_alert()), str)

    def test_contains_county_name(self):
        from src.alerts.notifier import format_alert_row
        assert "Providencia" in format_alert_row(_sample_alert(county_name="Providencia"))

    def test_contains_score(self):
        from src.alerts.notifier import format_alert_row
        assert "0.910" in format_alert_row(_sample_alert(opportunity_score=0.91))

    def test_shap_features_parsed(self):
        from src.alerts.notifier import format_alert_row
        shap = json.dumps([{"feature": "dist_metro_km", "direction": "up", "shap": 0.12}])
        assert "dist_metro_km" in format_alert_row(_sample_alert(shap_top_features=shap))

    def test_invalid_shap_does_not_raise(self):
        from src.alerts.notifier import format_alert_row
        result = format_alert_row(_sample_alert(shap_top_features="{bad json"))
        assert isinstance(result, str)

    def test_no_url_shows_na(self):
        from src.alerts.notifier import format_alert_row
        assert "N/A" in format_alert_row(_sample_alert(url=None))


# ── TestBuildEmailHtml ─────────────────────────────────────────────────────────

class TestBuildEmailHtml:

    def test_returns_html(self):
        from src.alerts.notifier import build_email_html
        html = build_email_html([_sample_alert()])
        assert "<html>" in html and "</html>" in html

    def test_contains_county_name(self):
        from src.alerts.notifier import build_email_html
        assert "Ñuñoa" in build_email_html([_sample_alert(county_name="Ñuñoa")])

    def test_empty_list(self):
        from src.alerts.notifier import build_email_html
        html = build_email_html([])
        assert "0 nuevas oportunidades" in html

    def test_multiple_alerts_count(self):
        from src.alerts.notifier import build_email_html
        html = build_email_html([_sample_alert(score_id=i) for i in range(3)])
        assert "3 nuevas oportunidades" in html


# ── TestSeenIds ────────────────────────────────────────────────────────────────

class TestSeenIds:

    def test_empty_when_no_file(self, tmp_path, monkeypatch):
        import src.alerts.notifier as m
        monkeypatch.setattr(m, "SEEN_FILE", tmp_path / ".seen.json")
        from src.alerts.notifier import load_seen_ids
        assert load_seen_ids() == set()

    def test_save_and_reload(self, tmp_path, monkeypatch):
        import src.alerts.notifier as m
        monkeypatch.setattr(m, "SEEN_FILE", tmp_path / ".seen.json")
        monkeypatch.setattr(m, "EXPORTS_DIR", tmp_path)
        from src.alerts.notifier import save_seen_ids, load_seen_ids
        save_seen_ids({1, 2, 3})
        assert load_seen_ids() == {1, 2, 3}

    def test_corrupt_file_returns_empty(self, tmp_path, monkeypatch):
        import src.alerts.notifier as m
        seen_file = tmp_path / ".seen.json"
        seen_file.write_text("{corrupt}")
        monkeypatch.setattr(m, "SEEN_FILE", seen_file)
        from src.alerts.notifier import load_seen_ids
        assert load_seen_ids() == set()


# ── TestNotifyJson ─────────────────────────────────────────────────────────────

class TestNotifyJson:

    def test_creates_file(self, tmp_path, monkeypatch):
        import src.alerts.notifier as m
        monkeypatch.setattr(m, "EXPORTS_DIR", tmp_path)
        from src.alerts.notifier import notify_json
        out = notify_json([_sample_alert()])
        assert out.exists()

    def test_file_content_correct(self, tmp_path, monkeypatch):
        import src.alerts.notifier as m
        monkeypatch.setattr(m, "EXPORTS_DIR", tmp_path)
        from src.alerts.notifier import notify_json
        out = notify_json([_sample_alert(county_name="Vitacura")])
        content = json.loads(out.read_text())
        assert any(a["county_name"] == "Vitacura" for a in content)

    def test_appends_on_second_call(self, tmp_path, monkeypatch):
        import src.alerts.notifier as m
        monkeypatch.setattr(m, "EXPORTS_DIR", tmp_path)
        from src.alerts.notifier import notify_json
        notify_json([_sample_alert(score_id=1)])
        out = notify_json([_sample_alert(score_id=2)])
        assert len(json.loads(out.read_text())) == 2


# ── TestNotifyEmail ───────────────────────────────────────────────────────────

class TestNotifyEmail:

    def test_returns_false_when_unconfigured(self, monkeypatch):
        import src.alerts.notifier as m
        monkeypatch.setattr(m, "ALERT_EMAIL_TO", "")
        monkeypatch.setattr(m, "SMTP_USER", "")
        monkeypatch.setattr(m, "SMTP_PASSWORD", "")
        from src.alerts.notifier import notify_email
        assert notify_email([_sample_alert()]) is False

    def test_calls_smtp_when_configured(self, monkeypatch):
        import src.alerts.notifier as m
        monkeypatch.setattr(m, "ALERT_EMAIL_TO",   "to@example.com")
        monkeypatch.setattr(m, "SMTP_USER",        "from@example.com")
        monkeypatch.setattr(m, "SMTP_PASSWORD",    "secret")
        monkeypatch.setattr(m, "ALERT_EMAIL_FROM", "from@example.com")
        monkeypatch.setattr(m, "SMTP_HOST",        "smtp.example.com")
        monkeypatch.setattr(m, "SMTP_PORT",        587)
        mock_smtp = MagicMock()
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)
        with patch("smtplib.SMTP", return_value=mock_smtp):
            from src.alerts.notifier import notify_email
            result = notify_email([_sample_alert()])
        assert result is True
        mock_smtp.starttls.assert_called_once()

    def test_smtp_exception_returns_false(self, monkeypatch):
        import src.alerts.notifier as m
        monkeypatch.setattr(m, "ALERT_EMAIL_TO",   "to@example.com")
        monkeypatch.setattr(m, "SMTP_USER",        "from@example.com")
        monkeypatch.setattr(m, "SMTP_PASSWORD",    "secret")
        monkeypatch.setattr(m, "ALERT_EMAIL_FROM", "from@example.com")
        monkeypatch.setattr(m, "SMTP_HOST",        "bad")
        monkeypatch.setattr(m, "SMTP_PORT",        587)
        with patch("smtplib.SMTP", side_effect=ConnectionRefusedError):
            from src.alerts.notifier import notify_email
            assert notify_email([_sample_alert()]) is False
