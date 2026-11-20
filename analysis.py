"""
analysis.py — turns raw data into insights without any AI.

Everything here is plain, transparent counting, so the dashboard is useful even
when no AI key is configured: rising keywords, simple topic groups, top outlets,
common job titles and skills, and LinkedIn-vs-news keyword comparisons.
"""

import io
import re
from collections import Counter

import pandas as pd

STOPWORDS = set("""
a about above after again against all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had
has have having he her here hers him his how i if in into is it its itself just me more most my
new no nor not now of off on once only or other our out over own same she should so some such
than that the their them then there these they this those through to too under until up very
was we were what when where which while who whom why will with would you your says said say
amid after over into via vs year years day days week weeks month months today report reports
news latest update live first last next big top how what why could may might must one two three
time times us uk get gets got make makes made back still people world group set sets plan plans
deal deals call calls take takes amid around against show shows know new need needs use used
against first second watch video photos read here inside former chief top s t don isn
tech data company companies firm firms stock stocks share shares global industry sector
""".split())

SKILLS = ["python", "sql", "excel", "tableau", "power bi", "r ", "machine learning", "statistics",
          "policy analysis", "research", "stakeholder", "project management", "communication",
          "data analysis", "financial modeling", "aws", "azure", "java", "javascript", "react",
          "product management", "marketing", "sales", "writing", "economics", "gis", "budget",
          "grant", "regulatory", "compliance", "climate", "sustainability", "leadership",
          "negotiation", "customer", "operations", "strategy", "deep learning", "llm", "nlp"]


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z\-']+", text or "")
    return [w.lower().strip("'-") for w in words]


def _terms(text: str, exclude: set) -> list[str]:
    """Meaningful single words and two-word phrases from a headline."""
    toks = [t for t in _tokens(text) if len(t) > 2]
    unigrams = [t for t in toks if t not in STOPWORDS and t not in exclude]
    bigrams = [f"{a} {b}" for a, b in zip(toks, toks[1:])
               if a not in STOPWORDS and b not in STOPWORDS and a not in exclude and b not in exclude]
    return unigrams + bigrams


def sector_words(terms) -> set:
    return {w for t in terms for w in _tokens(t)}


def rising_keywords(news: pd.DataFrame, exclude: set, top_n: int = 15) -> pd.DataFrame:
    """Most frequent headline terms, plus 'momentum': are they more common in the
    newer half of the time window than in the older half?"""
    if news.empty:
        return pd.DataFrame(columns=["keyword", "mentions", "momentum"])
    df = news.dropna(subset=["published"]).sort_values("published")
    midpoint = df["published"].median() if not df.empty else None
    total, recent, older = Counter(), Counter(), Counter()
    for _, row in df.iterrows():
        terms = set(_terms(row["title"], exclude))
        total.update(terms)
        (recent if midpoint is not None and row["published"] >= midpoint else older).update(terms)
    # Drop single words that are only frequent because they belong to a frequent phrase.
    rows = []
    for term, n in total.most_common(200):
        if n < 2:
            continue
        r, o = recent[term], older[term]
        rows.append({"keyword": term, "mentions": n, "momentum": round((r - o) / max(r + o, 1), 2)})
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["keyword", "mentions", "momentum"])
    phrases = [k for k in out["keyword"] if " " in k]
    out = out[~out["keyword"].apply(lambda k: " " not in k and any(
        k in p.split() and out.loc[out.keyword == p, "mentions"].iloc[0] >= 0.8 * out.loc[out.keyword == k, "mentions"].iloc[0]
        for p in phrases))]
    return out.head(top_n).reset_index(drop=True)


def keyword_themes(news: pd.DataFrame, keywords: pd.DataFrame, n_themes: int = 6) -> list[dict]:
    """Simple, non-AI grouping: each headline joins the first top keyword it mentions."""
    themes = []
    used = set()
    for kw in keywords["keyword"].head(n_themes * 2):
        mask = news["title"].str.lower().str.contains(re.escape(kw), na=False) & ~news.index.isin(used)
        group = news[mask]
        if len(group) >= 2:
            used.update(group.index)
            themes.append({"name": kw.title(), "summary": f"{len(group)} headlines mention “{kw}”.",
                           "articles": group.head(6)})
        if len(themes) == n_themes:
            break
    return themes


def top_outlets(news: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    if news.empty:
        return pd.DataFrame(columns=["outlet", "articles"])
    return news["outlet"].value_counts().head(n).rename_axis("outlet").reset_index(name="articles")


def job_title_words(jobs: pd.DataFrame, n: int = 12) -> pd.DataFrame:
    counts = Counter()
    for title in jobs["title"].dropna():
        counts.update({t for t in _terms(title, set()) if " " in t or len(t) > 3})
    return pd.DataFrame(counts.most_common(n), columns=["title phrase", "jobs"])


def skill_counts(jobs: pd.DataFrame, n: int = 12) -> pd.DataFrame:
    text = (jobs["title"].fillna("") + " " + jobs["description"].fillna("")).str.lower() + " "
    counts = {s.strip(): int(text.str.contains(re.escape(s), regex=True).sum()) for s in SKILLS}
    df = pd.DataFrame(sorted(counts.items(), key=lambda kv: -kv[1]), columns=["skill", "jobs"])
    return df[df["jobs"] > 0].head(n)


# --------------------------------------------------------------------------- #
# LinkedIn Lens helpers (user-provided content only; nothing is stored)
# --------------------------------------------------------------------------- #
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\w)(\+?\d[\d\s().-]{8,}\d)(?!\w)")


def redact(text: str) -> str:
    """Remove email addresses and phone numbers before anything reaches the AI."""
    return _PHONE.sub("[phone removed]", _EMAIL.sub("[email removed]", text))


def split_pasted_posts(text: str) -> list[str]:
    """Posts separated by a line with --- or by two blank lines."""
    parts = re.split(r"\n\s*-{3,}\s*\n|\n\s*\n\s*\n", text or "")
    return [p.strip() for p in parts if len(p.strip()) > 30]


def posts_from_csv(file_bytes: bytes) -> list[str]:
    """Read a LinkedIn data-export CSV (e.g. Shares.csv or Comments.csv)."""
    raw = file_bytes.decode("utf-8", errors="ignore")
    df = None
    for skip in range(0, 5):  # some exports start with a few note lines
        try:
            candidate = pd.read_csv(io.StringIO(raw), skiprows=skip)
            if len(candidate.columns) > 1:
                df = candidate
                break
        except Exception:
            continue
    if df is None or df.empty:
        return []
    preferred = ["ShareCommentary", "Message", "Commentary", "Text", "Content", "Post"]
    col = next((c for c in df.columns if c in preferred), None)
    if col is None:  # fall back to the column with the longest text
        text_cols = df.select_dtypes(include="object")
        if text_cols.empty:
            return []
        col = text_cols.apply(lambda s: s.fillna("").str.len().mean()).idxmax()
    return [str(v).strip() for v in df[col].dropna() if len(str(v).strip()) > 30][:200]


def compare_keywords(posts: list[str], news: pd.DataFrame, exclude: set, n: int = 10) -> dict:
    """What LinkedIn posts discuss vs. what the news covers (simple keyword overlap)."""
    post_counts = Counter()
    for p in posts:
        post_counts.update(set(_terms(p, exclude)))
    news_counts = Counter()
    for t in news["title"] if not news.empty else []:
        news_counts.update(set(_terms(t, exclude)))
    post_top = [k for k, c in post_counts.most_common(80) if c >= 2 or len(posts) <= 6][:40]
    news_top = [k for k, _ in news_counts.most_common(80)]
    return {
        "shared": [k for k in post_top if k in news_counts][:n],
        "linkedin_only": [k for k in post_top if k not in news_counts][:n],
        "news_only": [k for k in news_top if k not in post_counts][:n],
    }
