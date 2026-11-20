"""
app.py — the Sector Pulse dashboard (run with:  streamlit run app.py)

Layout: a sidebar with filters, and six tabs:
  Pulse Overview · Top Stories & Topics · Jobs · LinkedIn Lens · AI Briefing · About & Responsible Use
"""

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

import ai
import analysis as an
import sources as src
from config import (APP_NAME, APP_TAGLINE, MAX_AI_CALLS_PER_SESSION, PALETTE, REGIONS,
                    SECTORS, TIME_WINDOWS)

st.set_page_config(page_title=APP_NAME, page_icon="📡", layout="wide")

st.markdown("""
<style>
  .block-container {padding-top: 2rem; max-width: 1200px;}
  .sp-chip {display:inline-block; padding:2px 10px; margin:2px 4px 2px 0; border-radius:999px;
            background:rgba(42,120,214,.12); font-size:.85rem;}
  .sp-muted {opacity:.7; font-size:.85rem;}
  .sp-story {margin-bottom:.55rem; line-height:1.35;}
  div[data-testid="stMetricValue"] {font-size:1.8rem;}
</style>
""", unsafe_allow_html=True)


def chart_style(fig, height=320):
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=36, b=8), font=dict(size=13),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      hoverlabel=dict(font_size=13), showlegend=False)
    fig.update_xaxes(showgrid=False, title=None)
    fig.update_yaxes(gridcolor="rgba(128,128,128,.18)", title=None)
    return fig


def hbar(df, x, y, title, color=PALETTE[0]):
    fig = px.bar(df.iloc[::-1], x=x, y=y, orientation="h", title=title, text=x)
    fig.update_traces(marker_color=color, marker_line_width=0, textposition="outside", cliponaxis=False)
    fig = chart_style(fig, height=max(260, 28 * len(df) + 70))
    fig.update_xaxes(showticklabels=False, gridcolor="rgba(0,0,0,0)")
    return fig


CACHE_DIR = Path(__file__).parent / ".data_cache"


def _cache_file(fn, args) -> Path:
    key = hashlib.sha1(repr((fn.__name__, args)).encode()).hexdigest()[:16]
    return CACHE_DIR / f"{fn.__name__}-{key}.pkl"


def safe(fn, *args):
    """Run a data fetch; on failure return (None, friendly message).

    Successful results are also saved to disk, so if a free API is briefly down
    the app can show the last good copy (clearly labelled with its age)."""
    try:
        result = fn(*args)
        try:
            CACHE_DIR.mkdir(exist_ok=True)
            result.to_pickle(_cache_file(fn, args))
        except Exception:
            pass
        return result, None
    except Exception as exc:  # never let one source crash the app
        msg = str(exc) if isinstance(exc, src.SourceError) else \
            f"Something went wrong with this data source ({exc.__class__.__name__})."
        path = _cache_file(fn, args)
        if isinstance(exc, src.SourceError) and path.exists() and "Secrets" not in msg:
            try:
                age_min = (time.time() - path.stat().st_mtime) / 60
                age = f"{age_min:.0f} minutes" if age_min < 120 else f"{age_min / 60:.0f} hours"
                note = f"{msg} Showing the last saved copy from {age} ago."
                if note not in stale_notes:
                    stale_notes.append(note)
                return pd.read_pickle(path), None
            except Exception:
                pass
        return None, msg


stale_notes: list[str] = []


@st.cache_resource
def gdelt_executor():
    """Run GDELT off the Streamlit script thread so other sources can render."""
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="gdelt")


def _fetch_gdelt_data(terms, country, timespan):
    first_new_note = len(stale_notes)
    news, news_err = safe(src.fetch_news, terms, country, timespan)
    timeline, timeline_err = safe(src.fetch_news_timeline, terms, country, timespan)
    failed = bool(
        news_err or timeline_err
        or any("global news (gdelt)" in note.lower() for note in stale_notes[first_new_note:])
    )
    return news, news_err, timeline, timeline_err, failed


def _gdelt_completion_watch():
    future = st.session_state.get("_gdelt_future")
    if future is None:
        return
    if future.done():
        try:
            st.session_state["_gdelt_result"] = future.result()
        except Exception as exc:
            message = f"Global news (GDELT) is temporarily unavailable ({exc.__class__.__name__})."
            st.session_state["_gdelt_result"] = (None, message, None, message, True)
        st.session_state["_gdelt_future"] = None
        st.rerun()
    else:
        st.caption("Global news is loading in the background; other sources are available meanwhile.")


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown(f"## 📡 {APP_NAME}")
    sector = st.selectbox("Sector", list(SECTORS), format_func=lambda s: f"{SECTORS[s]['emoji']} {s}")
    window = st.radio("Time window", list(TIME_WINDOWS), index=1, horizontal=False)
    region = st.radio("Region (where the news outlet / job is based)", list(REGIONS), horizontal=False)
    if st.button("🔄 Refresh data", width="stretch",
                 help="Data is cached for an hour to respect API limits. This forces a fresh fetch."):
        st.cache_data.clear()
        st.rerun()

    with st.expander("Edit search keywords"):
        st.caption("Change what counts as this sector (one phrase per line). Applies to this session only.")
        default_terms = "\n".join(SECTORS[sector]["news_terms"])
        custom = st.text_area("News keywords", default_terms, height=150, key=f"kw_{sector}")
    news_terms = tuple(t.strip() for t in custom.splitlines() if len(t.strip()) >= 3) or tuple(SECTORS[sector]["news_terms"])

    st.divider()
    st.markdown("**Data sources**")
    st.markdown(
        f"- 📰 Global news (GDELT) ✅\n"
        f"- 💬 Hacker News ✅\n"
        f"- 💼 Adzuna jobs {'✅' if src.get_secret('ADZUNA_APP_ID') else '⚪ not set up'}\n"
        f"- 🏛️ USAJobs {'✅' if src.get_secret('USAJOBS_API_KEY') else '⚪ not set up'}\n"
        f"- 🤖 AI (Claude) {'✅' if ai.ai_available() else '⚪ not set up'}")
    st.caption("Official APIs only. No LinkedIn scraping. Nothing you paste is stored.")

cfg = SECTORS[sector]
win = TIME_WINDOWS[window]
reg = REGIONS[region]

# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.title(f"{cfg['emoji']} {sector} — Pulse")
st.caption(f"{APP_TAGLINE}  ·  {region} · {window.lower()}")
with st.expander("👋 How to use Sector Pulse", expanded=False):
    st.markdown("""
1. **Pick a sector, time window and region** in the left sidebar (on mobile, tap **›** at the top-left).
2. **Pulse Overview** shows how much the sector is in the news and which keywords are rising.
3. **Top Stories & Topics** lists the most-covered stories, grouped into themes, each linked to the original source.
4. **Jobs** shows live openings from official job databases, plus the most-requested skills.
5. **LinkedIn Lens**: paste LinkedIn posts you've seen (or upload your own LinkedIn data export) to compare them with the news.
6. **AI Briefing** writes a one-page, source-cited summary you can download for interview or networking prep.

Data refreshes hourly. Always open the source links before relying on anything here.
""")

# --------------------------------------------------------------------------- #
# Fetch data (each source fails independently)
# --------------------------------------------------------------------------- #
gdelt_key = (news_terms, reg["gdelt_country"], win["gdelt"])
if st.session_state.get("_gdelt_key") != gdelt_key:
    st.session_state["_gdelt_key"] = gdelt_key
    st.session_state["_gdelt_result"] = None
    st.session_state["_gdelt_future"] = gdelt_executor().submit(
        _fetch_gdelt_data, news_terms, reg["gdelt_country"], win["gdelt"])

gdelt_future = st.session_state.get("_gdelt_future")
gdelt_result = st.session_state.get("_gdelt_result")
if gdelt_result is None and gdelt_future is not None and gdelt_future.done():
    try:
        gdelt_result = gdelt_future.result()
    except Exception as exc:
        message = f"Global news (GDELT) is temporarily unavailable ({exc.__class__.__name__})."
        gdelt_result = (None, message, None, message, True)
    st.session_state["_gdelt_result"] = gdelt_result
    st.session_state["_gdelt_future"] = None
    gdelt_future = None

if gdelt_result is None:
    news, news_err = None, None
    timeline, timeline_err = None, None
else:
    news, news_err, timeline, timeline_err, gdelt_failed = gdelt_result

gdelt_pending = gdelt_future is not None
if gdelt_pending:
    st.fragment(run_every=1)(_gdelt_completion_watch)()
gdelt_unavailable = bool(
    (gdelt_result is not None and gdelt_failed) or news_err or timeline_err
    or any("global news (gdelt) is temporarily unavailable" in note.lower() for note in stale_notes)
)
news = news if news is not None else pd.DataFrame(columns=["title", "url", "outlet", "published", "source_country", "outlets_carrying"])

hn, hn_err = (pd.DataFrame(columns=["title", "url", "discussion", "points", "comments", "published"]), None)
if cfg["hn_terms"]:
    res, hn_err = safe(src.fetch_hn, tuple(cfg["hn_terms"]), win["days"])
    hn = res if res is not None else hn

job_frames, job_errs = [], []
res, err = safe(src.fetch_adzuna, tuple(cfg["job_terms"]), tuple(reg["adzuna"]), win["days"])
if res is not None:
    job_frames.append(res)
else:
    job_errs.append(err)
if reg["usajobs"]:
    res, err = safe(src.fetch_usajobs, tuple(cfg["usajobs_terms"]), max(win["days"], 7))
    if res is not None:
        job_frames.append(res)
    else:
        job_errs.append(err)
jobs = pd.concat([f for f in job_frames if not f.empty], ignore_index=True) if any(
    not f.empty for f in job_frames) else pd.DataFrame(columns=src.JOB_COLUMNS)

exclude = an.sector_words(news_terms) | {sector.lower()}
keywords = an.rising_keywords(news, exclude)
sources_list = ai.build_sources(news, hn, jobs)

tabs = st.tabs(["📊 Pulse Overview", "📰 Top Stories & Topics", "💼 Jobs", "🔎 LinkedIn Lens",
                "🤖 AI Briefing", "ℹ️ About & Responsible Use"])

# --------------------------------------------------------------------------- #
# Tab 1 — Overview
# --------------------------------------------------------------------------- #
with tabs[0]:
    if gdelt_unavailable:
        st.warning("Global news is temporarily unavailable, showing other sources")
    elif gdelt_pending:
        st.info("Global news is loading in the background; other sources are available meanwhile.")
    for note in stale_notes:
        st.info(note, icon="🕒")
    c1, c2, c3, c4 = st.columns(4)
    total_cov = int(timeline["articles"].sum()) if timeline is not None and not timeline.empty else None
    c1.metric("Articles in window", f"{total_cov:,}" if total_cov else len(news),
              help="Total matching English-language articles GDELT tracked in this window.")
    c2.metric("Distinct stories analysed", len(news), help="Top stories after removing syndicated duplicates.")
    c3.metric("News outlets", news["outlet"].nunique() if not news.empty else 0)
    c4.metric("Open jobs found", len(jobs) if not jobs.empty else "—",
              help="From Adzuna and USAJobs (if configured).")

    if not keywords.empty:
        rising = keywords.sort_values(["momentum", "mentions"], ascending=False)
        rising = rising[rising["momentum"] > 0].head(5)
        if not rising.empty:
            st.markdown("**🔥 Rising keywords** (more frequent in the newer half of the window): " + " ".join(
                f"<span class='sp-chip'>{k}</span>" for k in rising["keyword"]), unsafe_allow_html=True)

    left, right = st.columns([3, 2])
    with left:
        if timeline is not None and not timeline.empty:
            bucket, unit = ("h", "hour") if win["days"] == 1 else ("D", "day")
            tl = timeline.set_index("date").resample(bucket)["articles"].sum().reset_index()
            fig = px.area(tl, x="date", y="articles", title=f"Coverage volume (articles per {unit})",
                          labels={"articles": "Articles", "date": ""})
            fig.update_traces(line=dict(color=PALETTE[0], width=2), fillcolor="rgba(42,120,214,.15)",
                              hovertemplate="%{x|%d %b %H:%M}<br>%{y:,} articles<extra></extra>")
            st.plotly_chart(chart_style(fig), width="stretch")
        elif not news.empty and news["published"].notna().any():
            # Fallback: chart when the top stories were published (no extra API call).
            freq = "h" if win["days"] == 1 else ("6h" if win["days"] <= 7 else "D")
            fb = (news.dropna(subset=["published"]).set_index("published").resample(freq)["title"]
                  .count().rename("stories").reset_index())
            fig = px.area(fb, x="published", y="stories", title="When the top stories were published")
            fig.update_traces(line=dict(color=PALETTE[0], width=2), fillcolor="rgba(42,120,214,.15)",
                              hovertemplate="%{x|%d %b %H:%M}<br>%{y} stories<extra></extra>")
            st.plotly_chart(chart_style(fig), width="stretch")
            st.caption("The full coverage-volume timeline is temporarily unavailable (the news API is busy), "
                       "so this chart uses the top stories instead. Click Refresh data later for the full view.")
        else:
            st.info(timeline_err or "No coverage timeline available for this selection.")
    with right:
        if not keywords.empty:
            st.plotly_chart(hbar(keywords.head(10), "mentions", "keyword", "Top keywords in headlines"),
                            width="stretch")
    outlets = an.top_outlets(news)
    if not outlets.empty:
        l2, r2 = st.columns([2, 3])
        with l2:
            st.plotly_chart(hbar(outlets.head(8), "articles", "outlet", "Most active outlets", PALETTE[2]),
                            width="stretch")
        with r2:
            st.markdown("**Most widely carried stories**")
            top = news.sort_values("outlets_carrying", ascending=False).head(6)
            for _, r in top.iterrows():
                st.markdown(f"<div class='sp-story'>• <a href='{r['url']}' target='_blank'>{r['title']}</a>"
                            f" <span class='sp-muted'>— {r['outlet']}</span></div>", unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Tab 2 — Stories & topics
# --------------------------------------------------------------------------- #
with tabs[1]:
    if news.empty:
        if gdelt_unavailable:
            st.warning("Global news is temporarily unavailable, showing other sources")
        else:
            st.info("No stories found for this selection. Try a longer time window or Global region.")
    else:
        st.subheader("Themes")
        use_ai = False
        if ai.ai_available():
            use_ai = st.toggle("Group stories with AI (smarter themes, uses 1 AI request)", value=False)
        themes, theme_note = None, None
        if use_ai:
            with st.spinner("Asking the AI to group headlines into themes…"):
                try:
                    themes = ai.ai_themes(sector, sources_list)
                    st.caption(ai.AI_LABEL)
                except ai.AIError as exc:
                    theme_note = str(exc)
        if theme_note:
            st.warning(theme_note + " Showing keyword-based themes instead.")
        if themes:
            for t in themes:
                linked, _ = ai.link_citations(t["summary"], sources_list)
                with st.expander(f"**{t['name']}** · {len(t['sources'])} stories", expanded=False):
                    st.markdown(linked)
                    for s in t["sources"]:
                        st.markdown(f"- [{s['title']}]({s['url']}) <span class='sp-muted'>— {s['outlet']}, {s['date']}</span>",
                                    unsafe_allow_html=True)
        else:
            kthemes = an.keyword_themes(news, keywords)
            if not ai.ai_available():
                st.caption("Themes below are grouped by shared keywords (no AI). Add an Anthropic key for AI-grouped themes.")
            for t in kthemes:
                with st.expander(f"**{t['name']}** · {len(t['articles'])} stories"):
                    for _, r in t["articles"].iterrows():
                        st.markdown(f"- [{r['title']}]({r['url']}) <span class='sp-muted'>— {r['outlet']}</span>",
                                    unsafe_allow_html=True)

        st.subheader("All top stories")
        q = st.text_input("Filter headlines", placeholder="e.g. regulation, India, OpenAI")
        view = news if not q else news[news["title"].str.contains(q, case=False, na=False)]
        st.dataframe(
            view[["published", "title", "outlet", "outlets_carrying", "url"]],
            column_config={
                "published": st.column_config.DatetimeColumn("Seen", format="D MMM, HH:mm"),
                "title": st.column_config.TextColumn("Headline", width="large"),
                "outlet": "Outlet",
                "outlets_carrying": st.column_config.NumberColumn("Outlets", help="How many outlets ran this headline"),
                "url": st.column_config.LinkColumn("Link", display_text="Open ↗"),
            }, hide_index=True, width="stretch", height=420)

    if cfg["hn_terms"]:
        st.subheader("💬 What the tech community is discussing (Hacker News)")
        if hn_err:
            st.warning(hn_err)
        elif hn.empty:
            st.info("No popular Hacker News discussions in this window.")
        else:
            st.dataframe(hn.head(20)[["points", "comments", "title", "discussion"]], column_config={
                "points": st.column_config.NumberColumn("▲ Points"),
                "comments": "Comments",
                "title": st.column_config.TextColumn("Story", width="large"),
                "discussion": st.column_config.LinkColumn("Discussion", display_text="Open ↗"),
            }, hide_index=True, width="stretch")

# --------------------------------------------------------------------------- #
# Tab 3 — Jobs
# --------------------------------------------------------------------------- #
with tabs[2]:
    for e in job_errs:
        st.info(e)
    if jobs.empty:
        if not job_errs:
            st.info("No job postings found for this selection. Try a longer window or another region.")
    else:
        j1, j2, j3 = st.columns(3)
        j1.metric("Open roles", len(jobs))
        j2.metric("Employers", jobs["organisation"].nunique())
        j3.metric("Sources", ", ".join(sorted(jobs["source"].str.split(" ").str[0].unique())))
        a, b = st.columns(2)
        titles = an.job_title_words(jobs)
        skills = an.skill_counts(jobs)
        if not titles.empty:
            a.plotly_chart(hbar(titles.head(10), "jobs", "title phrase", "Most common words in job titles"),
                           width="stretch")
        if not skills.empty:
            b.plotly_chart(hbar(skills.head(10), "jobs", "skill", "Skills mentioned in postings", PALETTE[1]),
                           width="stretch")
        employers = jobs["organisation"].value_counts().head(8).rename_axis("employer").reset_index(name="jobs")
        st.plotly_chart(hbar(employers, "jobs", "employer", "Employers with the most openings", PALETTE[2]),
                        width="stretch")
        jq = st.text_input("Filter jobs", placeholder="e.g. analyst, remote, Bengaluru")
        jv = jobs if not jq else jobs[(jobs["title"] + " " + jobs["organisation"].fillna("") + " " +
                                       jobs["location"].fillna("")).str.contains(jq, case=False, na=False)]
        st.dataframe(jv.sort_values("posted", ascending=False)[["posted", "title", "organisation", "location", "source", "url"]],
                     column_config={
                         "posted": st.column_config.DatetimeColumn("Posted", format="D MMM YYYY"),
                         "title": st.column_config.TextColumn("Role", width="large"),
                         "organisation": "Organisation", "location": "Location", "source": "Source",
                         "url": st.column_config.LinkColumn("Apply", display_text="Open ↗"),
                     }, hide_index=True, width="stretch", height=420)
        st.caption("Listings come from official job APIs and link to the original posting. Always apply via the employer's site.")

# --------------------------------------------------------------------------- #
# Tab 4 — LinkedIn Lens
# --------------------------------------------------------------------------- #
EXAMPLE_POSTS = """Three months into building an AI copilot for our policy team. Biggest lesson: the model is the easy part, getting clean, trusted data and clear accountability is the hard part. Governance first, demos second.
---
Everyone is talking about AI regulation, but the real bottleneck for most mid-sized companies is skills. We surveyed 40 hiring managers and most said they can't find people who can evaluate AI outputs critically.
---
Data centres and energy demand are the story nobody in my feed talks about. If AI keeps scaling, grid capacity and clean power become the constraint, not chips.
---
Hot take: open-weight models are changing procurement in government. Agencies want control over where data lives, and that is shifting vendor conversations."""

with tabs[3]:
    st.markdown("""**See how LinkedIn conversations compare with the wider news picture.**
LinkedIn doesn't allow scraping and has no public API for trending posts, so this tab works only with content
**you choose to share**: paste posts you've seen, or upload your own LinkedIn data export
(LinkedIn → Settings → Data privacy → *Get a copy of your data* → e.g. `Shares.csv`).""")
    st.info("Nothing you paste or upload is saved. It stays in this browser session and disappears when you close the tab. "
            "Email addresses and phone numbers are removed automatically before any AI analysis. "
            "Please don't paste private messages.", icon="🔒")
    if st.button("Load example posts (made up, for a demo)"):
        st.session_state["lens_text"] = EXAMPLE_POSTS
    pasted = st.text_area("Paste LinkedIn posts — separate posts with a line containing ---",
                          key="lens_text", height=200)
    upload = st.file_uploader("…or upload a CSV from your LinkedIn data export", type=["csv"])
    posts = an.split_pasted_posts(pasted)
    if upload is not None:
        posts += an.posts_from_csv(upload.getvalue())
    posts = [an.redact(p) for p in posts]

    if posts:
        st.success(f"{len(posts)} posts ready to analyse.")
        cmp = an.compare_keywords(posts, news, exclude)
        c1, c2, c3 = st.columns(3)
        for col, title, keys in [(c1, "🟦 In both LinkedIn & news", cmp["shared"]),
                                 (c2, "🟧 LinkedIn only", cmp["linkedin_only"]),
                                 (c3, "🟩 News only", cmp["news_only"])]:
            col.markdown(f"**{title}**")
            col.markdown(" ".join(f"<span class='sp-chip'>{k}</span>" for k in keys) or "_none found_",
                         unsafe_allow_html=True)
        st.caption("Keyword comparison above is simple counting (no AI).")
        if ai.ai_available():
            if st.button("🤖 Analyse with AI: themes, gaps & talking points", type="primary"):
                with st.spinner("Comparing your posts with the news…"):
                    try:
                        out = ai.ai_linkedin_lens(sector, posts, sources_list)
                        linked, _ = ai.link_citations(out, sources_list)
                        st.markdown(ai.AI_LABEL)
                        st.markdown(ai.link_post_ids(linked))
                    except ai.AIError as exc:
                        st.warning(str(exc))
        else:
            st.caption("Add an Anthropic API key to unlock AI theme analysis and talking points.")

# --------------------------------------------------------------------------- #
# Tab 5 — AI Briefing
# --------------------------------------------------------------------------- #
with tabs[4]:
    st.markdown(f"A one-page, source-cited briefing on **{sector}** built only from the data on this dashboard.")
    if not ai.ai_available():
        st.info("The AI Briefing needs an Anthropic API key. Add `ANTHROPIC_API_KEY` to the app's Secrets "
                "(see the README). Everything else on the dashboard works without it.")
    elif not sources_list:
        st.info("There isn't enough data for a briefing yet. Try a longer time window.")
    else:
        st.caption(f"Uses {len(sources_list)} numbered sources · model `{ai.model_name()}` · "
                   f"{ai.calls_left()} of {MAX_AI_CALLS_PER_SESSION} AI requests left this session")
        if st.button("✍️ Generate briefing", type="primary"):
            stats = (f"Articles tracked: {int(timeline['articles'].sum()) if timeline is not None and not timeline.empty else 'n/a'}\n"
                     f"Distinct stories: {len(news)}; outlets: {news['outlet'].nunique() if not news.empty else 0}\n"
                     f"Top headline keywords: {', '.join(keywords['keyword'].head(10)) if not keywords.empty else 'n/a'}\n"
                     f"Job postings found: {len(jobs)}")
            with st.spinner("Writing your briefing (about 20–40 seconds)…"):
                try:
                    raw = ai.ai_briefing(sector, region, window, stats, sources_list)
                    st.session_state["briefing"] = (sector, region, window, raw)
                except ai.AIError as exc:
                    st.warning(str(exc))
        saved = st.session_state.get("briefing")
        if saved and saved[:3] == (sector, region, window):
            raw = saved[3]
            linked, report = ai.link_citations(raw, sources_list)
            st.markdown(ai.AI_LABEL)
            st.markdown(linked)
            st.divider()
            st.markdown("**✅ Citation check** (automatic)")
            k1, k2, k3 = st.columns(3)
            k1.metric("Citations", report["citations"])
            k2.metric("Distinct sources cited", report["unique_sources"])
            k3.metric("Lines with a citation", f"{report['coverage']}%")
            if report["invalid"]:
                st.error(f"The AI cited sources that don't exist ({', '.join(report['invalid'])}); they were removed. Treat nearby claims with care.")
            else:
                st.caption("Every citation points to a real source fetched by this app.")
            if report["uncited_lines"]:
                with st.expander("Lines without a citation (check these yourself)"):
                    for ln in report["uncited_lines"]:
                        st.markdown(f"- {ln}")
            ref_list = "\n".join(f"- [{s['id']}] {s['title']} — {s['outlet']}, {s['date']}: {s['url']}" for s in sources_list)
            md = (f"# {sector} briefing — {region}, {window.lower()}\n\n"
                  f"_Generated {datetime.now(timezone.utc):%d %b %Y %H:%M} UTC by Sector Pulse. "
                  f"AI-generated summary — verify with sources._\n\n{linked}\n\n## Sources\n{ref_list}\n")
            st.download_button("⬇️ Download briefing (Markdown)", md, file_name=f"sector-pulse-{sector.split()[0].lower()}-briefing.md",
                               mime="text/markdown")
            st.caption("Tip: to get a PDF, open the downloaded file in Google Docs or Word and export as PDF.")
    with st.expander("See the numbered sources the AI is allowed to use"):
        for s in sources_list:
            st.markdown(f"**[{s['id']}]** [{s['title']}]({s['url']}) <span class='sp-muted'>— {s['type']}, {s['outlet']}, {s['date']}</span>",
                        unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Tab 6 — About
# --------------------------------------------------------------------------- #
with tabs[5]:
    st.markdown("""
### What Sector Pulse is
A dashboard that shows what's happening in an industry right now: trending stories, rising topics, community
discussion, live job openings and an AI-written briefing, with every item linked to its source. It was built for
students and early-career professionals preparing for interviews, networking and policy work.

### Data sources
| Source | What it provides | Access | Refresh |
|---|---|---|---|
| [GDELT DOC 2.0 API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) | Global English-language news coverage & volume | Free, no key | Cached 1 hour |
| [Hacker News (Algolia API)](https://hn.algolia.com/api) | Popular tech-community discussions | Free, no key | Cached 1 hour |
| [Adzuna API](https://developer.adzuna.com/) | Private-sector job listings (US, UK, India) | Free key | Cached 1 hour |
| [USAJobs API](https://developer.usajobs.gov/) | US federal government jobs | Free key | Cached 1 hour |
| [Anthropic Claude API](https://docs.anthropic.com/) | Theme grouping, briefings, LinkedIn Lens analysis | Paid key (small cost) | On request |
| You | LinkedIn posts you paste / your own LinkedIn data export | Your choice | Never stored |

### Guardrails
- **No scraping.** Only official APIs, within their rate limits (e.g. GDELT's one request per 5 seconds). LinkedIn is never scraped.
- **No profiles of people.** The dashboard tracks topics, organisations and outlets, not individuals. The AI is instructed not to profile or rate anyone.
- **No stored user data.** No logins and no database. Pasted or uploaded content lives only in your browser session, is never cached, and has emails and phone numbers stripped before any AI analysis.
- **Honest AI.** The AI may use only the data shown in the app, must cite a numbered source for each claim, and is told to flag thin data. The app automatically checks every citation and flags any that don't match a real source. All AI output is labelled.
- **Prompt-injection defence.** Headlines and pasted posts are passed to the AI as untrusted data, and it is told never to follow instructions inside them.
- **Budget protection.** Each visitor session is limited to a few AI requests, and AI results on public data are cached for an hour.
- **Keys kept secret.** API keys live in the hosting platform's Secrets and are never in the code or on GitHub.

### Limitations
- **Headlines, not full articles.** GDELT returns headlines and links, so the analysis (and the AI) works from headlines only.
- **Coverage ≠ importance.** A topic covered by many outlets isn't necessarily the most important one, and GDELT's outlet mix leans towards English-language online media.
- **"Rising keywords" are simple counts** comparing the newer and older halves of the time window. They're a signal, not a forecast.
- **Job listings are a sample**, filtered by keywords, not the full market.
- **LinkedIn Lens only knows what you give it**, so it can't show what's trending across LinkedIn as a whole.
- **AI can still make mistakes.** Always open the sources before you quote anything.
""")
    st.caption(f"Session AI requests used: {MAX_AI_CALLS_PER_SESSION - ai.calls_left()} / {MAX_AI_CALLS_PER_SESSION}")
