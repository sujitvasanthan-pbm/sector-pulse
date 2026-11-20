"""Regression tests for bounded GDELT failures and dashboard availability."""
import logging
import os
import sys
import threading

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sources  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, text, payload=None, invalid_json=False):
        self.status_code = status_code
        self.text = text
        self.payload = payload
        self.invalid_json = invalid_json

    def json(self):
        if self.invalid_json:
            raise ValueError("not JSON")
        return self.payload


@pytest.fixture
def gdelt_state(monkeypatch):
    monkeypatch.setattr(sources, "_gdelt_last_call", [0.0])
    monkeypatch.setattr(sources, "_gdelt_down_until", [0.0])
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if seconds >= sources.GDELT_RETRY_DELAY:
            sources._gdelt_last_call[0] = sources.time.time() - sources.GDELT_MIN_INTERVAL

    monkeypatch.setattr(sources.time, "sleep", fake_sleep)
    return sleeps


def test_gdelt_retries_once_after_six_seconds_and_uses_timeout(monkeypatch, gdelt_state):
    responses = [
        FakeResponse(200, "Please limit requests to one every 5 seconds", invalid_json=True),
        FakeResponse(200, '{"articles":[]}', {"articles": []}),
    ]
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr(sources.requests, "get", fake_get)
    result = sources._gdelt_request({"mode": "artlist"})

    assert result == {"articles": []}
    assert len(calls) == 2
    assert all(call["timeout"] == 15 for call in calls)
    assert sources.GDELT_RETRY_DELAY in gdelt_state


def test_gdelt_logs_failed_response_and_stops_after_one_retry(monkeypatch, gdelt_state, caplog):
    body = "<html>" + ("bad gateway response " * 20) + "</html>"
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(kwargs)
        return FakeResponse(502, body, invalid_json=True)

    monkeypatch.setattr(sources.requests, "get", fake_get)
    with caplog.at_level(logging.WARNING, logger=sources.__name__):
        with pytest.raises(sources.SourceError, match="temporarily unavailable"):
            sources._gdelt_request({"mode": "artlist"})

    assert len(calls) == 2
    failures = [record for record in caplog.records if record.message.startswith("GDELT request failed")]
    assert len(failures) == 2
    assert all(record.args[0] == 502 for record in failures)
    assert all(record.args[1] == body[:200] for record in failures)


def test_gdelt_rejects_unexpected_json_shape(monkeypatch, gdelt_state, caplog):
    body = '{"articles":"not-a-list"}'
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(kwargs)
        return FakeResponse(200, body, {"articles": "not-a-list"})

    monkeypatch.setattr(sources.requests, "get", fake_get)
    with caplog.at_level(logging.WARNING, logger=sources.__name__):
        with pytest.raises(sources.SourceError, match="valid articles list"):
            sources._gdelt_request({"mode": "artlist"})

    assert len(calls) == 2
    assert all(record.args[0] == 200 for record in caplog.records
               if record.message.startswith("GDELT request failed"))


def test_gdelt_failure_cooldown_avoids_repeated_network_calls(monkeypatch, gdelt_state):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(kwargs)
        return FakeResponse(503, "upstream unavailable", invalid_json=True)

    monkeypatch.setattr(sources.requests, "get", fake_get)
    with pytest.raises(sources.SourceError):
        sources._gdelt_request({"mode": "artlist"})
    with pytest.raises(sources.SourceError, match="temporarily unavailable"):
        sources._gdelt_request({"mode": "artlist"})

    assert len(calls) == 2
    assert sources._gdelt_down_until[0] > sources.time.monotonic()
    assert sources.GDELT_FAILURE_TTL == 180


def test_dashboard_renders_other_tabs_when_gdelt_fails(monkeypatch):
    from streamlit.testing.v1 import AppTest

    started = threading.Event()
    release = threading.Event()

    def fail_news(*args, **kwargs):
        started.set()
        release.wait(timeout=10)
        raise sources.SourceError("Global news (GDELT) is temporarily unavailable.")

    def fail_timeline(*args, **kwargs):
        raise sources.SourceError("Global news (GDELT) is temporarily unavailable.")

    # Preserve cache filenames so this also exercises the stale-copy fallback.
    fail_news.__name__ = "fetch_news"
    fail_timeline.__name__ = "fetch_news_timeline"
    monkeypatch.setattr(sources, "fetch_news", fail_news)
    monkeypatch.setattr(sources, "fetch_news_timeline", fail_timeline)
    monkeypatch.setattr(
        sources, "fetch_hn",
        lambda *args, **kwargs: pd.DataFrame(
            columns=["title", "url", "discussion", "points", "comments", "published"]),
    )
    monkeypatch.setattr(
        sources, "fetch_adzuna",
        lambda *args, **kwargs: pd.DataFrame(columns=sources.JOB_COLUMNS),
    )
    monkeypatch.setattr(
        sources, "fetch_usajobs",
        lambda *args, **kwargs: pd.DataFrame(columns=sources.JOB_COLUMNS),
    )

    app = AppTest.from_file(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"),
        default_timeout=60,
    ).run()

    future = app.session_state.get("_gdelt_future")
    assert started.wait(timeout=3)
    assert future is not None and not future.done()
    assert not app.exception
    assert len(app.tabs) == 6

    release.set()
    if future is not None:
        future.result(timeout=10)
        app.run()

    assert not app.exception
    assert len(app.tabs) == 6
    assert any(
        warning.value == "Global news is temporarily unavailable, showing other sources"
        for warning in app.warning
    )
