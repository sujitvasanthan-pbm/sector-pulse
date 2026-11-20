"""
config.py — every setting you might want to change lives here.

To add or tweak a sector, edit the SECTORS dictionary below. No other file
needs to change. Each sector has:
  - news_terms:  phrases searched in global news (GDELT). Use full phrases;
                 GDELT ignores very short words like "AI".
  - job_terms:   single words sent to the Adzuna job search (matched with OR).
  - usajobs_terms: short keyword searches sent to USAJobs (US government jobs).
  - hn_terms:    Hacker News searches (tech-flavoured sectors only), or [].
"""

APP_NAME = "Sector Pulse"
APP_TAGLINE = "What is each industry talking about right now — with every item linked to its source."

SECTORS = {
    "AI & Tech": {
        "emoji": "🤖",
        "news_terms": ["artificial intelligence", "machine learning", "generative AI",
                       "large language model", "semiconductor", "AI regulation"],
        "job_terms": ["machine learning", "AI", "data scientist", "software engineer"],
        "usajobs_terms": ["artificial intelligence", "data scientist"],
        "hn_terms": ["AI", "LLM", "startup"],
    },
    "Public Policy & Government": {
        "emoji": "🏛️",
        "news_terms": ["public policy", "legislation", "policy reform",
                       "government budget", "regulation", "think tank"],
        "job_terms": ["policy", "analyst", "government", "legislative"],
        "usajobs_terms": ["policy analyst", "program analyst"],
        "hn_terms": [],
    },
    "Climate & Energy": {
        "emoji": "🌍",
        "news_terms": ["climate change", "renewable energy", "clean energy",
                       "carbon emissions", "energy transition", "solar power"],
        "job_terms": ["sustainability", "climate", "renewable", "energy"],
        "usajobs_terms": ["climate", "energy"],
        "hn_terms": ["climate", "battery", "solar"],
    },
    "Finance & Fintech": {
        "emoji": "💹",
        "news_terms": ["fintech", "central bank", "interest rates",
                       "venture capital", "digital payments", "private equity"],
        "job_terms": ["finance", "fintech", "investment", "analyst"],
        "usajobs_terms": ["financial analyst", "economist"],
        "hn_terms": ["fintech", "payments"],
    },
    "Healthcare": {
        "emoji": "🩺",
        "news_terms": ["healthcare", "public health", "health policy",
                       "biotech", "drug pricing", "digital health"],
        "job_terms": ["healthcare", "health", "clinical", "biotech"],
        "usajobs_terms": ["public health", "health policy"],
        "hn_terms": [],
    },
    "Consumer & D2C": {
        "emoji": "🛍️",
        "news_terms": ["consumer brands", "direct-to-consumer", "e-commerce",
                       "retail sales", "consumer spending", "quick commerce"],
        "job_terms": ["ecommerce", "brand", "marketing", "retail"],
        "usajobs_terms": ["marketing specialist"],
        "hn_terms": [],
    },
    "Social Impact & Development": {
        "emoji": "🤝",
        "news_terms": ["international development", "nonprofit", "World Bank",
                       "poverty", "humanitarian aid", "social enterprise"],
        "job_terms": ["nonprofit", "development", "program", "impact"],
        "usajobs_terms": ["international development", "program manager"],
        "hn_terms": [],
    },
    "Sports Business": {
        "emoji": "🏟️",
        "news_terms": ["sports business", "media rights", "sports sponsorship",
                       "sports league", "franchise valuation", "sports betting"],
        "job_terms": ["sports", "sponsorship", "athletics"],
        "usajobs_terms": ["sports", "recreation"],
        "hn_terms": [],
    },
}

# Region -> settings for each data source.
#   gdelt_country: GDELT "sourcecountry" filter (where the outlet is based); None = worldwide
#   adzuna:        Adzuna country codes to search
#   usajobs:       whether to include US federal jobs
REGIONS = {
    "Global": {"gdelt_country": None, "adzuna": ["us", "gb", "in"], "usajobs": True},
    "India": {"gdelt_country": "IN", "adzuna": ["in"], "usajobs": False},
    "United States": {"gdelt_country": "US", "adzuna": ["us"], "usajobs": True},
}

TIME_WINDOWS = {
    "Last 24 hours": {"gdelt": "1d", "days": 1},
    "Last 7 days": {"gdelt": "7d", "days": 7},
    "Last 30 days": {"gdelt": "30d", "days": 30},
}

# How long (seconds) to reuse fetched data before asking the APIs again.
CACHE_SECONDS = 60 * 60

# Safety limit: AI calls allowed per visitor session (protects the API budget).
MAX_AI_CALLS_PER_SESSION = 8

# Default AI model. Override by adding a secret called ANTHROPIC_MODEL
# (e.g. "claude-haiku-5-5" is far cheaper, "claude-opus-5-5" is the most capable).
DEFAULT_MODEL = "claude-opus-5-5"

# Chart colours (validated colour-blind-safe categorical palette, in fixed order).
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
