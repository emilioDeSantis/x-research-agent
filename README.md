# X Research Agent

Ask a question; a Claude lead agent researches it across X (Twitter) and the web and writes a sourced briefing.

## How it works
- **Lead** (Claude Opus 5.5) plans the question, sends parallel **workers** after distinct angles (`delegate`), chases gaps, then writes the briefing.
- **Sources** (each enabled only if its key is set):
  - `x_search_grok` — xAI Grok `x_search`: semantic + keyword discovery over all of X.
  - `x_search` / `x_thread` / `x_user_posts` — official X API v2 (pay-per-use, last 7 days, exact operators, real engagement).
  - `web_search` / `web_fetch` — Claude's server-side web tools for primary sources.
- **Depth**: `quick` (lead only), `deep` (≤6 workers), `max` (≤10 workers per round, higher effort).
- Reports, the full research log and every X post seen are stored in `data/research.db` (SQLite) — groundwork for the daily-feed mode.

## Run
```bash
cp .env.example .env   # fill in keys
./run.sh               # http://localhost:8787
```

## Layout
- `app/agent.py` — lead/worker loop, prompts, tool dispatch
- `app/sources/grok.py`, `app/sources/xapi.py` — X data sources
- `app/server.py` — FastAPI + SSE
- `static/index.html` — UI
