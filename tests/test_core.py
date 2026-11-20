"""Basic checks for the parts of Sector Pulse that enforce guardrails.
Run with:  python -m pytest -q
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai  # noqa: E402
import analysis as an  # noqa: E402

SOURCES = [{"id": "S1", "url": "https://a.example/1"}, {"id": "S2", "url": "https://a.example/2"}]


def test_valid_citations_become_links():
    text, report = ai.link_citations("- Chip exports were restricted this week, per coverage [S1][S2].", SOURCES)
    assert "[[S1]](https://a.example/1)" in text
    assert report["citations"] == 2 and report["invalid"] == []


def test_invented_citations_are_flagged_and_removed():
    text, report = ai.link_citations("- A claim backed by a source that does not exist at all [S9].", SOURCES)
    assert report["invalid"] == ["S9"]
    assert "[S9]" not in text and "source not found" in text


def test_uncited_lines_are_reported():
    _, report = ai.link_citations("- This sentence is long enough to count but has no citation in it.", SOURCES)
    assert report["coverage"] == 0 and len(report["uncited_lines"]) == 1


def test_redaction_removes_email_and_phone():
    out = an.redact("Contact me at jane.doe@example.com or +1 (555) 123-4567 about the role.")
    assert "example.com" not in out and "555" not in out


def test_pasted_posts_are_split():
    posts = an.split_pasted_posts("First post about climate finance and policy.\n---\nSecond post about grid storage and batteries.")
    assert len(posts) == 2


def test_linkedin_csv_export_is_parsed():
    csv = b"Date,ShareLink,ShareCommentary\n2026-01-01,https://x,Excited to share our new report on clean energy jobs in India\n"
    assert an.posts_from_csv(csv) == ["Excited to share our new report on clean energy jobs in India"]


def test_rising_keywords_detects_newer_terms():
    now = pd.Timestamp.now(tz="UTC")
    rows = [{"title": "Battery storage boom hits grid", "published": now} for _ in range(3)]
    rows += [{"title": "Coal plant closures continue", "published": now - pd.Timedelta(days=5)} for _ in range(3)]
    kw = an.rising_keywords(pd.DataFrame(rows), exclude=set())
    battery = kw[kw.keyword.str.contains("battery")].iloc[0]
    coal = kw[kw.keyword.str.contains("coal")].iloc[0]
    assert battery.momentum > 0 > coal.momentum
