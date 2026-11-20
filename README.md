# 📡 Sector Pulse

**What is each industry talking about right now?** Sector Pulse is a dashboard that shows the trending stories, rising topics, community discussions and live job openings for a chosen sector, along with an AI-written briefing. Every item links to its source.

It's built for students and early-career professionals who want an up-to-date, well-sourced picture of a field before an interview, a networking chat or a policy memo, without spending hours scrolling LinkedIn and news sites.

> Built as a Level 3+ class project: a dynamic web app connected to external APIs (GDELT, Hacker News, Adzuna, USAJobs and the Anthropic Claude API).

---

## What it does

| Tab | What you get |
|---|---|
| 📊 **Pulse Overview** | Coverage volume over time, rising keywords, top headline keywords, most active outlets, most widely carried stories |
| 📰 **Top Stories & Topics** | Stories grouped into themes (by keyword, or by AI if a key is set), a searchable table of top stories with links, and Hacker News discussions for tech-related sectors |
| 💼 **Jobs** | Live listings from Adzuna (US/UK/India) and USAJobs (US government), with the most common title words, skills and employers |
| 🔎 **LinkedIn Lens** | Paste LinkedIn posts you've seen, or upload your own LinkedIn data export, to compare them with the news: what's shared, what's LinkedIn-only, what's news-only, plus AI talking points |
| 🤖 **AI Briefing** | A one-page briefing (key developments, debates, organisations, job signals, conversation starters) where every claim cites a numbered source, followed by an **automatic citation check**. Downloadable as Markdown |
| ℹ️ **About & Responsible Use** | Data sources, guardrails and limitations in plain language |

**Filters:** 8 sectors (AI & Tech, Public Policy & Government, Climate & Energy, Finance & Fintech, Healthcare, Consumer & D2C, Social Impact & Development, Sports Business) · last 24 hours / 7 days / 30 days · Global / India / United States. Each sector's keywords can be edited in the sidebar or in `config.py`.

## Why there's no LinkedIn scraping

LinkedIn's User Agreement prohibits scraping, and its official APIs don't provide trending posts. Sector Pulse therefore builds the sector picture from **official, public APIs**, and the LinkedIn Lens works only with **content users choose to share**.

## Guardrails

- **No scraping.** Only official APIs are used, within their rate limits (GDELT allows one request per 5 seconds, and the app spaces its calls accordingly).
- **No profiles of individuals.** The app tracks topics, organisations and outlets. The AI is instructed not to profile or rate people.
- **No stored user data.** There are no logins and no database. Pasted or uploaded LinkedIn content stays in the browser session, is never cached, and has emails and phone numbers removed before any AI analysis.
- **Grounded, cited AI.** The AI sees only the data fetched by the app, has to cite a numbered source for each claim, and is told to flag thin data. The app checks every citation against the real source list, turns valid ones into links, and flags invented ones. All AI output is labelled *"AI-generated summary — verify with sources."*
- **Prompt-injection defence.** Headlines and pasted posts reach the AI as untrusted data, and it is told never to follow instructions inside them.
- **Budget protection.** Each visitor session gets 8 AI requests, and AI results on public data are cached for an hour.
- **Graceful failure.** If one source is down, the others keep working. If the news API is busy, the app shows the last saved copy and labels its age.
- **Secrets stay secret.** API keys are read from environment variables (Replit Secrets) and are never in the code.

## Limitations

- GDELT returns headlines and links, not full articles, so all analysis works from headlines.
- Coverage volume is not the same as importance. GDELT's mix of outlets leans toward English-language online media.
- "Rising keywords" are a simple comparison between the newer and older halves of the time window.
- Job listings are a keyword-filtered sample, not the whole market.
- The LinkedIn Lens only knows what you paste or upload, so it can't show what's trending across all of LinkedIn.
- AI can still make mistakes. Open the sources before you quote anything.

---

## Run it on Replit (recommended)

1. On Replit, click **Create App → Import from GitHub** and paste this repository's URL. Replit reads the `.replit` file and sets everything up.
2. Open **Tools → Secrets** and add whichever keys you have. All of them are optional:

   | Secret name | Where to get it | Unlocks |
   |---|---|---|
   | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | [developer.adzuna.com](https://developer.adzuna.com/) → Register (free) | Private-sector jobs |
   | `USAJOBS_API_KEY`, `USAJOBS_EMAIL` | [developer.usajobs.gov](https://developer.usajobs.gov/apirequest/) → Request API key (free; key is emailed) | US government jobs |
   | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/) → API Keys (prepaid credit) | AI themes, briefing, LinkedIn Lens analysis |
   | `ANTHROPIC_MODEL` *(optional)* | e.g. `claude-haiku-5-5` | A much cheaper model. The default is `claude-opus-5-5` |

   News, keywords, charts, Hacker News and the keyword-based LinkedIn Lens all work **with no keys at all**.
3. Click **Run**. The dashboard opens in the Webview. The first load takes about 15 seconds because of GDELT's rate limit, and after that results are cached.
4. Click **Publish** (Deploy) to get a public link. Check the price shown on the Publish screen before you confirm.

## Alternative free hosting: Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, click **Create app**, and pick this repo with `app.py` as the main file.
2. Under **Advanced settings → Secrets**, paste your keys in the format shown in `.streamlit/secrets.toml.example`.
3. Deploy. Public apps are free, and an app sleeps after about 12 hours without visitors. The first visitor clicks "wake up".

## Run it on your own computer

```bash
pip install -r requirements.txt
streamlit run app.py
```

Set keys as environment variables (`export ADZUNA_APP_ID=...`) or in `.streamlit/secrets.toml`. That file is git-ignored.

## Project structure

| File | What it does |
|---|---|
| `app.py` | The dashboard: sidebar filters, six tabs, charts and tables |
| `config.py` | Sectors, keywords, regions, time windows, AI limits and colours. Edit this file to customise the app |
| `sources.py` | Fetches data from GDELT, Hacker News, Adzuna and USAJobs, with caching, rate limiting and friendly errors |
| `analysis.py` | Non-AI analysis: rising keywords, keyword themes, job skills, LinkedIn export parsing, PII redaction |
| `ai.py` | Claude prompts with guardrails, numbered-source citations and the automatic citation checker |
| `tests/test_core.py` | Checks for the citation checker, redaction, post parsing and keyword analysis (`python -m pytest`) |
| `.replit` | Tells Replit how to run and publish the app |

## Data sources & credits

[GDELT Project](https://www.gdeltproject.org/) · [Hacker News Search API by Algolia](https://hn.algolia.com/api) · [Adzuna](https://www.adzuna.com/) · [USAJobs](https://developer.usajobs.gov/) · [Anthropic Claude](https://www.anthropic.com/)
