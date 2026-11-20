# Sector Pulse

This imported project uses Python 3.12 and Streamlit. Keep its existing structure and stack.

## Run

Dependencies are listed in `requirements.txt` and installed in the Replit environment.
Use the **Run** button / **Start application** workflow:

```sh
python -m streamlit run app.py --server.port 5000 --server.address 0.0.0.0 --server.headless true --browser.serverAddress "${REPLIT_DEV_DOMAIN:-localhost}"
```

The dashboard appears in Preview. Public news requests may take time because GDELT
requires rate limiting. Source failures are shown in the dashboard.
The browser address flag trusts this workspace's preview host while keeping
Streamlit's CORS and XSRF protections enabled.

## Optional credentials

No credentials are needed to start the app or use its public news features.
AI summaries require `ANTHROPIC_API_KEY`; `ANTHROPIC_MODEL` optionally selects the model.
Private-sector jobs require `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`.
Government jobs require `USAJOBS_API_KEY` and `USAJOBS_EMAIL`.
Configure credentials through Replit Secrets, never in committed files.
These optional services are not configured as part of the basic setup.

## Tests

```sh
python -m pytest -q
```
