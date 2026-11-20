"""Regression tests for bounded GDELT failures and dashboard availability."""
import logging
import os
import sys
import threading

import pandas as pd
import pytest
from config import SECTORS

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


class FakeRSSResponse:
    status_code = 200
    content = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel><item>
      <title>Policy changes announced - Policy Daily</title>
      <link>https://news.google.com/rss/articles/policy-story</link>
      <pubDate>Fri, 20 Nov 2026 12:00:00 GMT</pubDate>
      <source url="https://policydaily.example">Policy Daily</source>
    </item></channel></rss>"""

    def raise_for_status(self):
        return None


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


@pytest.mark.parametrize("sector", ["AI & Tech", "Public Policy & Government", "Climate & Energy"])
def test_google_news_returns_stories_for_priority_sectors(monkeypatch, sector):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeRSSResponse()

    monkeypatch.setattr(sources.requests, "get", fake_get)
    sources.fetch_google_news.clear()

    stories = sources.fetch_google_news(tuple(SECTORS[sector]["news_terms"]), "Global", "7d")

    assert len(stories) == 1
    assert stories.iloc[0]["title"] == "Policy changes announced"
    assert stories.iloc[0]["news_source"] == "Google News"
    assert stories.iloc[0]["url"].startswith("https://news.google.com/")
    assert len(calls) == 1
    assert calls[0][1]["params"]["gl"] == "US"
    assert " OR " in calls[0][1]["params"]["q"]
    assert "when:7d" in calls[0][1]["params"]["q"]


@pytest.mark.parametrize(
    ("region", "country", "language"),
    [("India", "IN", "en-IN"), ("United States", "US", "en-US")],
)
def test_google_news_uses_regional_edition_and_requested_time_window(
    monkeypatch, region, country, language
):
    captured = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return FakeRSSResponse()

    monkeypatch.setattr(sources.requests, "get", fake_get)
    sources.fetch_google_news.clear()
    sources.fetch_google_news(("public policy", "legislation"), region, "1d")

    assert captured["params"]["hl"] == language
    assert captured["params"]["gl"] == country
    assert captured["params"]["ceid"] == f"{country}:en"
    assert "when:1d" in captured["params"]["q"]


def test_merging_duplicate_headlines_keeps_both_provider_links():
    gdelt = pd.DataFrame([{
        "title": "Policy Changes Announced!",
        "url": "https://publisher.example/policy",
        "outlet": "Policy Daily",
        "published": pd.Timestamp("2026-11-20T12:00:00Z"),
        "source_country": "US",
        "outlets_carrying": 2,
        "news_source": "GDELT",
    }])
    google = pd.DataFrame([{
        "title": "policy changes announced",
        "url": "https://news.google.com/rss/articles/policy",
        "outlet": "Policy Daily",
        "published": pd.Timestamp("2026-11-20T12:00:00Z"),
        "source_country": "US",
        "outlets_carrying": 1,
        "news_source": "Google News",
    }])

    merged = sources.merge_news_sources(gdelt, google)

    assert len(merged) == 1
    assert merged.iloc[0]["news_source"] == "GDELT + Google News"
    assert merged.iloc[0]["url"] == "https://publisher.example/policy"
    assert merged.iloc[0]["google_url"] == "https://news.google.com/rss/articles/policy"


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
    monkeypatch.setattr(
        sources, "fetch_google_news",
        lambda *args, **kwargs: pd.DataFrame(columns=sources.NEWS_COLUMNS),
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
    for future_key in ("_gdelt_future", "_google_news_future"):
        pending_future = app.session_state.get(future_key)
        if pending_future is not None:
            pending_future.result(timeout=10)
    app.run()

    assert not app.exception
    assert len(app.tabs) == 6
    assert any(
        warning.value == "Global news is temporarily unavailable, showing other sources"
        for warning in app.warning
    )
