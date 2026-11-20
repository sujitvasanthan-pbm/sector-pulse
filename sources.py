"""
sources.py — fetches data from official, public APIs only. No scraping.

  * GDELT DOC 2.0 API   — global news coverage (free, no key, max 1 request / 5 s)
  * Hacker News (Algolia) — tech discussions (free, no key)
  * Adzuna API          — private-sector job listings (free key)
  * USAJobs API         — US federal government jobs (free key)

Every function returns a pandas DataFrame, or raises SourceError with a
plain-English message. The app catches those errors so one broken source never
takes down the rest of the dashboard. Results are cached for an hour.
"""

import os
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import pandas as pd
import requests
import streamlit as st

from config import CACHE_SECONDS

USER_AGENT = "SectorPulse/1.0 (student dashboard; uses official APIs only)"
TIMEOUT = 25
GDELT_TIMEOUT = 15
GDELT_RETRY_DELAY = 6
GDELT_FAILURE_TTL = 180
GDELT_MIN_INTERVAL = 5.5
logger = logging.getLogger(__name__)
NEWS_COLUMNS = [
    "title", "url", "outlet", "published", "source_country",
    "outlets_carrying", "news_source", "google_url",
]
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"


class SourceError(Exception):
    """A data source failed or is not configured. The message is shown to users."""


def get_secret(name: str) -> str | None:
    """Read a key from Replit Secrets / environment variables, then Streamlit secrets."""
    value = os.environ.get(name)
    if value:
        return value.strip()
    try:
        value = st.secrets.get(name)  # used on Streamlit Community Cloud
        return str(value).strip() if value else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# GDELT — global news
# --------------------------------------------------------------------------- #
_gdelt_lock = threading.Lock()
_gdelt_last_call = [0.0]
_gdelt_down_until = [0.0]  # short failure cooldown, separate from successful-result caching
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def _gdelt_request(params: dict) -> dict:
    """Fetch and validate a GDELT response, with one bounded retry."""
    if time.monotonic() < _gdelt_down_until[0]:
        raise SourceError("Global news (GDELT) is temporarily unavailable.")
    last_problem = "no response"
    for attempt in range(2):
        with _gdelt_lock:
            wait = GDELT_MIN_INTERVAL - (time.time() - _gdelt_last_call[0])
            if wait > 0:
                time.sleep(wait)
            try:
                resp = requests.get(GDELT_URL, params=params, timeout=GDELT_TIMEOUT,
                                    headers={"User-Agent": USER_AGENT})
            except requests.RequestException as exc:
                last_problem = f"network error ({exc.__class__.__name__})"
                _gdelt_last_call[0] = time.time()
                logger.warning("GDELT request failed: status=unavailable response=%r", str(exc)[:200])
                if attempt == 0:
                    time.sleep(GDELT_RETRY_DELAY)
                    continue
                break
            _gdelt_last_call[0] = time.time()

        text = resp.text.strip()
        if not 200 <= resp.status_code < 300:
            last_problem = f"HTTP {resp.status_code}"
        elif not text:
            _gdelt_down_until[0] = 0.0
            return {}  # GDELT may return an empty body when nothing matches
        else:
            try:
                data = resp.json()
            except ValueError:
                data = None
                last_problem = "response was not valid JSON"

            expected_key = "articles" if params.get("mode") == "artlist" else \
                "timeline" if params.get("mode") == "timelinevolraw" else None
            if data is not None and not isinstance(data, dict):
                last_problem = "JSON response was not an object"
                data = None
            elif data is not None and expected_key and (
                    expected_key not in data or not isinstance(data[expected_key], list)):
                last_problem = f"JSON response did not contain a valid {expected_key} list"
                data = None
            elif data is not None:
                _gdelt_down_until[0] = 0.0
                return data

        logger.warning("GDELT request failed: status=%s response=%r",
                       resp.status_code, text[:200])
        if attempt == 0:
            time.sleep(GDELT_RETRY_DELAY)

    _gdelt_down_until[0] = time.monotonic() + GDELT_FAILURE_TTL
    raise SourceError(f"Global news (GDELT) is temporarily unavailable ({last_problem}).")


def _gdelt_query(terms: list[str], country: str | None) -> str:
    phrases = " OR ".join(f'"{t}"' if " " in t else t for t in terms)
    query = f"({phrases}) sourcelang:english"
    if country:
        query += f" sourcecountry:{country}"
    return query


def _clean_title(title) -> str:
    """GDELT strips punctuation oddly ("Human - Made"); tidy it up."""
    title = re.sub(r"(\w) - (\w)", r"\1-\2", title or "")
    return re.sub(r"\s{2,}", " ", title).strip()


def _parse_gdelt_date(value: str):
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return pd.NaT


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def fetch_news(terms: tuple, country: str | None, timespan: str) -> pd.DataFrame:
    """Most relevant English-language articles for the sector in the time window."""
    data = _gdelt_request({
        "query": _gdelt_query(list(terms), country),
        "mode": "artlist", "format": "json", "maxrecords": 250,
        "timespan": timespan, "sort": "hybridrel",
    })
    rows = [{
        "title": _clean_title(a.get("title")),
        "url": a.get("url"),
        "outlet": a.get("domain"),
        "published": _parse_gdelt_date(a.get("seendate")),
        "source_country": a.get("sourcecountry"),
        "outlets_carrying": 1,
        "news_source": "GDELT",
        "google_url": None,
    } for a in data.get("articles", [])]
    df = pd.DataFrame(rows, columns=NEWS_COLUMNS)
    if df.empty:
        return df
    # Remove syndicated duplicates (same headline published by many outlets),
    # but remember how many outlets carried it — a useful "coverage" signal.
    df["key"] = df["title"].str.lower().str.replace(r"[^a-z0-9 ]", "", regex=True).str.strip()
    df = df[df["key"].str.len() > 15]
    counts = df.groupby("key")["outlet"].nunique().rename("outlets_carrying")
    df = df.drop(columns="outlets_carrying").drop_duplicates("key").merge(
        counts, on="key"
    ).drop(columns="key")
    return df.reset_index(drop=True)


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def fetch_google_news(terms: tuple, region: str, timespan: str) -> pd.DataFrame:
    """Fetch one no-key Google News RSS search for the complete sector keyword set."""
    editions = {
        "Global": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
        "India": {"hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
        "United States": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
    }
    edition = editions.get(region)
    if edition is None:
        raise ValueError(f"Unsupported Google News edition: {region}")
    when = {"1 day": "1d", "7 days": "7d", "30 days": "30d"}.get(timespan, timespan)
    query = " OR ".join(f'"{term}"' for term in terms)
    if when:
        query = f"({query}) when:{when}"
    try:
        response = requests.get(
            GOOGLE_NEWS_RSS_URL,
            params={"q": query, **edition},
            timeout=15,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
    except (requests.RequestException, ElementTree.ParseError) as exc:
        raise SourceError(f"Google News RSS is unavailable ({exc.__class__.__name__}).")

    country = {"India": "IN", "United States": "US"}.get(region)
    rows = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        source = item.find("source")
        outlet = (source.text or "").strip() if source is not None else ""
        if outlet and title.endswith(f" - {outlet}"):
            title = title[:-(len(outlet) + 3)].strip()
        published_text = item.findtext("pubDate")
        try:
            published = parsedate_to_datetime(published_text) if published_text else pd.NaT
            if not pd.isna(published) and published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            published = pd.NaT
        rows.append({
            "title": title,
            "url": link,
            "outlet": outlet or "Google News",
            "published": published,
            "source_country": country,
            "outlets_carrying": 1,
            "news_source": "Google News",
            "google_url": None,
        })
    return pd.DataFrame(rows, columns=NEWS_COLUMNS)


def merge_news_sources(gdelt: pd.DataFrame | None, google: pd.DataFrame | None) -> pd.DataFrame:
    """Merge both feeds by normalized headline while retaining provider links."""
    frames = []
    for frame, provider in ((gdelt, "GDELT"), (google, "Google News")):
        if frame is None or frame.empty:
            continue
        normalized = frame.copy()
        for column, default in (
            ("outlet", "Unknown outlet"),
            ("source_country", None),
            ("outlets_carrying", 1),
            ("google_url", None),
        ):
            if column not in normalized:
                normalized[column] = default
        if "news_source" not in normalized:
            normalized["news_source"] = provider
        normalized["_key"] = normalized["title"].fillna("").str.lower().str.replace(
            r"[^a-z0-9 ]", "", regex=True
        ).str.strip()
        frames.append(normalized[normalized["_key"] != ""])

    if not frames:
        return pd.DataFrame(columns=NEWS_COLUMNS)

    combined = pd.concat(frames, ignore_index=True, sort=False)
    rows = []
    for _, group in combined.groupby("_key", sort=False):
        sources = []
        for value in group["news_source"].fillna(""):
            for label in str(value).split(" + "):
                if label and label not in sources:
                    sources.append(label)
        preferred = group[group["news_source"].str.contains("GDELT", na=False)]
        primary = (preferred.iloc[0] if not preferred.empty else group.iloc[0])
        google_rows = group[group["news_source"].str.contains("Google News", na=False)]
        has_gdelt = any("GDELT" in label for label in sources)
        google_url = None
        if has_gdelt and not google_rows.empty:
            google_url = next(
                (url for url in google_rows["url"].tolist() if isinstance(url, str) and url),
                None,
            )
        outlet_count = pd.to_numeric(group["outlets_carrying"], errors="coerce").max()
        if pd.isna(outlet_count):
            outlet_count = 1
        rows.append({
            "title": primary["title"],
            "url": primary["url"],
            "outlet": primary["outlet"],
            "published": primary["published"],
            "source_country": primary["source_country"],
            "outlets_carrying": outlet_count,
            "news_source": " + ".join(sources),
            "google_url": google_url,
        })
    return pd.DataFrame(rows, columns=NEWS_COLUMNS).reset_index(drop=True)


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def fetch_news_timeline(terms: tuple, country: str | None, timespan: str) -> pd.DataFrame:
    """Number of matching articles over time (GDELT's coverage-volume timeline)."""
    data = _gdelt_request({
        "query": _gdelt_query(list(terms), country),
        "mode": "timelinevolraw", "format": "json", "timespan": timespan,
    })
    series = (data.get("timeline") or [{}])[0].get("data", [])
    df = pd.DataFrame([{"date": _parse_gdelt_date(p.get("date")),
                        "articles": p.get("value", 0),
                        "all_articles": p.get("norm", 0)} for p in series])
    return df.dropna(subset=["date"]) if not df.empty else df


# --------------------------------------------------------------------------- #
# Hacker News — tech community discussion
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def fetch_hn(terms: tuple, days: int) -> pd.DataFrame:
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    rows = []
    for term in terms:
        try:
            resp = requests.get("https://hn.algolia.com/api/v1/search", timeout=TIMEOUT, params={
                "query": term, "tags": "story", "hitsPerPage": 30,
                "numericFilters": f"created_at_i>{since},points>10",
            }, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise SourceError(f"Hacker News is unavailable right now ({exc.__class__.__name__}).")
        for h in resp.json().get("hits", []):
            rows.append({
                "title": h.get("title"),
                "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                "discussion": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                "points": h.get("points") or 0,
                "comments": h.get("num_comments") or 0,
                "published": pd.to_datetime(h.get("created_at"), utc=True),
            })
    df = pd.DataFrame(rows, columns=["title", "url", "discussion", "points", "comments", "published"])
    return df.drop_duplicates("discussion").sort_values("points", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Jobs — Adzuna (private sector) and USAJobs (US government)
# --------------------------------------------------------------------------- #
JOB_COLUMNS = ["title", "organisation", "location", "posted", "url", "source", "description"]


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def fetch_adzuna(terms: tuple, countries: tuple, days: int) -> pd.DataFrame:
    app_id, app_key = get_secret("ADZUNA_APP_ID"), get_secret("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise SourceError("Adzuna jobs are switched off: add ADZUNA_APP_ID and ADZUNA_APP_KEY "
                          "to the app's Secrets (free at developer.adzuna.com).")
    words = " ".join(sorted({w.lower() for t in terms for w in t.split()}))
    rows = []
    for country in countries:
        try:
            resp = requests.get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", timeout=TIMEOUT,
                                params={"app_id": app_id, "app_key": app_key, "what_or": words,
                                        "results_per_page": 50, "max_days_old": max(days, 1),
                                        "sort_by": "date", "content-type": "application/json"})
        except requests.RequestException as exc:
            raise SourceError(f"Adzuna is unavailable right now ({exc.__class__.__name__}).")
        if resp.status_code in (401, 403):
            raise SourceError("Adzuna rejected the API key. Check ADZUNA_APP_ID / ADZUNA_APP_KEY in Secrets.")
        if resp.status_code != 200:
            raise SourceError(f"Adzuna returned an error (HTTP {resp.status_code}).")
        for j in resp.json().get("results", []):
            rows.append({
                "title": j.get("title", "").replace("<strong>", "").replace("</strong>", ""),
                "organisation": (j.get("company") or {}).get("display_name", "—"),
                "location": (j.get("location") or {}).get("display_name", country.upper()),
                "posted": pd.to_datetime(j.get("created"), utc=True, errors="coerce"),
                "url": j.get("redirect_url"),
                "source": f"Adzuna ({country.upper()})",
                "description": (j.get("description") or "")[:600],
            })
    return pd.DataFrame(rows, columns=JOB_COLUMNS)


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def fetch_usajobs(terms: tuple, days: int) -> pd.DataFrame:
    key, email = get_secret("USAJOBS_API_KEY"), get_secret("USAJOBS_EMAIL")
    if not (key and email):
        raise SourceError("US government jobs are switched off: add USAJOBS_API_KEY and USAJOBS_EMAIL "
                          "to the app's Secrets (free at developer.usajobs.gov).")
    rows = []
    for term in terms:
        try:
            resp = requests.get("https://data.usajobs.gov/api/search", timeout=TIMEOUT,
                                params={"Keyword": term, "DatePosted": min(max(days, 1), 60),
                                        "ResultsPerPage": 40},
                                headers={"Host": "data.usajobs.gov", "User-Agent": email,
                                         "Authorization-Key": key})
        except requests.RequestException as exc:
            raise SourceError(f"USAJobs is unavailable right now ({exc.__class__.__name__}).")
        if resp.status_code in (401, 403):
            raise SourceError("USAJobs rejected the API key. Check USAJOBS_API_KEY and USAJOBS_EMAIL.")
        if resp.status_code != 200:
            raise SourceError(f"USAJobs returned an error (HTTP {resp.status_code}).")
        items = resp.json().get("SearchResult", {}).get("SearchResultItems", [])
        for item in items:
            d = item.get("MatchedObjectDescriptor", {})
            rows.append({
                "title": d.get("PositionTitle"),
                "organisation": d.get("OrganizationName") or d.get("DepartmentName"),
                "location": d.get("PositionLocationDisplay"),
                "posted": pd.to_datetime(d.get("PublicationStartDate"), utc=True, errors="coerce"),
                "url": d.get("PositionURI"),
                "source": "USAJobs",
                "description": (d.get("QualificationSummary") or "")[:600],
            })
    return pd.DataFrame(rows, columns=JOB_COLUMNS).drop_duplicates("url")
