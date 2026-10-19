# X Research Agent

Ask a question and get a sourced briefing on the current state of things, researched across X (Twitter) and the web. It's built for keeping up with fast-moving fields like AI without scrolling.

## How it works

- A **lead agent** (Claude Opus 5.5) plans the research. On deep runs it sends **parallel workers** after different angles of the question, reads their notes, follows up on gaps, and writes the briefing.
- **Sources.** Each is used only if its key is set:
  - `x_search_grok`: xAI's Grok searches X by meaning and keyword. This is the best way to find things on X.
  - `x_search`, `x_thread`, `x_user_posts`: the official X API. These do exact searches over the last 7 days, read full threads and a person's recent posts, and report real engagement numbers.
  - `web_search`, `web_fetch`: Claude's own web search and page reading, for papers, repos, blogs and news.
- **Depth and budget:**

  | Depth | What happens | Default budget |
  |---|---|---|
  | quick | The lead searches alone; a few minutes | $1.50 |
  | deep | Up to 6 parallel workers | $10 |
  | max | Up to 10 workers per round, deeper reasoning | $30 |

  You can set your own budget per question. The agents see the running cost after every search and stop searching when the budget is used up. Runs usually land close to the budget and can go a little over.
- Every report, its full research log, and every X post the official API returned are saved in `data/research.db` on your computer.

## Setup

You need Python 3.10 or newer (`python3 --version`).

```bash
git clone https://github.com/emilioDeSantis/x-research-agent.git
cd x-research-agent
./setup.sh
```

Then open `.env` and add your keys:

| Key | Needed? | Where to get it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Required | https://console.anthropic.com/settings/keys (add credit under Billing) |
| `XAI_API_KEY` | Strongly recommended: the main way it searches X | https://console.x.ai → API Keys (add credit under Billing) |
| `X_BEARER_TOKEN` | Optional | https://developer.x.com → your app → Keys and tokens → Bearer Token (needs pay-per-use credit) |

Never commit `.env`. It's already in `.gitignore`.

## Run

```bash
./run.sh
```

Open http://localhost:8787. The three dots at the top left turn green for each key that's set. Type a question, pick a depth, optionally set a budget, and click **Research**. The research log streams live while it works, and the briefing appears when it's done.

- **Stop this run** cancels a run in progress.
- **Open as shareable page** on a finished report opens a clean, formatted version for reading or sharing.
- Past questions are listed on the left.

Add `--reload` (`./run.sh --reload`) if you're editing the code and want the server to restart on changes. After changing `.env`, restart the server.

## Cost

Roughly what a run costs:
- **quick:** $1–3
- **deep, with a $4–5 budget:** about $4–7
- **deep, with the default $10 budget:** about $8–10

Grok searches cost the most, about $0.50–2 each depending on how busy the topic is. Web searches cost about a cent. Check your Anthropic and xAI billing pages for exact spend.

## Exporting a report from the command line

```bash
.venv/bin/python -m app.export <run_id> out.html "Optional Title"
```

## Layout

- `app/agent.py`: lead and worker loop, prompts, tools, budget enforcement
- `app/sources/grok.py`, `app/sources/xapi.py`: the X data sources
- `app/cost.py`: cost tracking and budget
- `app/server.py`: web server and live updates
- `app/export.py`, `static/share_template.html`: shareable report pages
- `app/publish.py`: automatic sharing to the shared GitHub repo
- `static/index.html`: the web app
