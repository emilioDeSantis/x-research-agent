"""The research agent: a lead Claude that plans, delegates angles to parallel workers, and writes the briefing."""

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone

import anthropic

from . import db
from .config import CLAUDE_MODEL, has_x_api, has_xai
from .cost import Cost
from .sources import grok, xapi

_client: anthropic.AsyncAnthropic | None = None


def _claude() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()
    return _client

DEPTHS = {
    # lead effort, worker effort, lead turn cap, worker turn cap, max workers
    "quick": dict(lead_effort="medium", worker_effort="medium", lead_turns=14, worker_turns=0, max_workers=0, budget=1.5),
    "deep": dict(lead_effort="high", worker_effort="medium", lead_turns=30, worker_turns=16, max_workers=6, budget=10.0),
    "max": dict(lead_effort="xhigh", worker_effort="high", lead_turns=45, worker_turns=24, max_workers=10, budget=30.0),
}

# max_uses caps each request so a single model turn can't run up an unbounded bill between budget checks.
SERVER_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 6},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5},
]


def _source_tools() -> list[dict]:
    tools = []
    if has_xai():
        tools.append({
            "name": "x_search_grok",
            "description": (
                "Search X (Twitter) through Grok's x_search. Grok runs several keyword AND semantic searches, looks up "
                "accounts, and reads threads for you, then returns the relevant posts with handles, quotes, dates and "
                "x.com URLs. Best for discovery: 'what are people saying about X', finding who matters on a topic, "
                "catching things you don't know the keywords for. Phrase the query as a precise natural-language "
                "request. Covers all of X's history. The most expensive tool (~$0.50–2.00 per call; busy topics cost more), so make each query count and don't repeat near-identical ones."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to find, as a specific request."},
                    "from_date": {"type": "string", "description": "YYYY-MM-DD, inclusive."},
                    "to_date": {"type": "string", "description": "YYYY-MM-DD, exclusive."},
                    "handles": {"type": "array", "items": {"type": "string"}, "description": "Only search these accounts (max 20)."},
                    "exclude_handles": {"type": "array", "items": {"type": "string"}, "description": "Skip these accounts (max 20). Ignored if handles is set."},
                    "include_media": {"type": "boolean", "description": "Let Grok look at images/videos in posts (slower)."},
                },
                "required": ["query"],
            },
        })
    if has_x_api():
        tools += [
            {
                "name": "x_search",
                "description": (
                    "Exact search over the LAST 7 DAYS of X via the official API, returning raw posts with real "
                    "engagement numbers, sorted client-side. Supports X operators: implicit AND, OR, -negation, "
                    "(grouping), \"exact phrase\", from:user, to:user, url:domain.com, has:links, has:media, is:reply, "
                    "is:quote, lang:en, conversation_id:ID. Retweets are excluded automatically. min_faves is NOT "
                    "supported — use min_likes instead. Costs ~$0.015 per post returned (post + author), so keep max_results modest (default 30)."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "X search query, max 512 chars."},
                        "sort_order": {"type": "string", "enum": ["relevancy", "recency"], "description": "What X returns first. Default relevancy."},
                        "sort": {"type": "string", "enum": ["likes", "recent"], "description": "How results are ordered for you. Default likes."},
                        "min_likes": {"type": "integer", "description": "Drop posts below this many likes."},
                        "max_results": {"type": "integer", "description": "10-100, default 30."},
                        "start_time": {"type": "string", "description": "ISO 8601, e.g. 2026-10-14T00:00:00Z."},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "x_thread",
                "description": "Read a post plus its thread and replies (replies only from the last 7 days), ranked by likes. Use on posts that are clearly important or sparked debate.",
                "input_schema": {
                    "type": "object",
                    "properties": {"tweet_id": {"type": "string"}},
                    "required": ["tweet_id"],
                },
            },
            {
                "name": "x_user_posts",
                "description": "A user's bio and most recent posts (newest first). Use to check what a key person has been saying lately.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "username": {"type": "string"},
                        "max_results": {"type": "integer", "description": "5-100, default 25."},
                        "include_replies": {"type": "boolean"},
                    },
                    "required": ["username"],
                },
            },
        ]
    return tools


DELEGATE_TOOL = {
    "name": "delegate",
    "description": (
        "Send research workers out in parallel. Each worker is a capable researcher with the same X and web tools you "
        "have; it works its assignment independently and returns dense notes with sources. Give each a distinct angle "
        "and enough context to work alone (the question, what you already know, what you need back). Returns all "
        "workers' notes once they finish."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short label, e.g. 'Benchmarks & evals'."},
                        "brief": {"type": "string", "description": "The full assignment."},
                    },
                    "required": ["title", "brief"],
                },
            }
        },
        "required": ["tasks"],
    },
}


# Rough worst-case cost of one call, used to refuse calls that would blow the budget.
EST_COST = {"x_search_grok": 2.0, "x_search": 0.5, "x_thread": 0.6, "x_user_posts": 0.3}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%A, %B %d, %Y")


def _sources_note() -> str:
    parts = []
    if has_xai():
        parts.append("x_search_grok (semantic + keyword discovery across all of X)")
    if has_x_api():
        parts.append("x_search / x_thread / x_user_posts (official API: exact operators, real engagement numbers, last 7 days)")
    parts.append("web_search / web_fetch (the open web: papers, repos, blogs, docs, news)")
    note = "Your sources: " + "; ".join(parts) + "."
    if not has_xai() and not has_x_api():
        note += " No X access is configured right now, so lean on the web and say in the report that X wasn't searched."
    return note


LEAD_SYSTEM = """You are a research agent that keeps one person fully up to date on the state of the world — whatever they ask about, but especially fast-moving fields like AI. They don't scroll X; you do it for them, and far more thoroughly than they ever could. Today is {today}.

X is where things surface first: researchers, founders, engineers and insiders post launches, results, leaks, demos and arguments there before anywhere else. The open web is where you confirm, get the primary source, and go deeper. {sources}

Your job is to find everything that matters on the question — including things the person wouldn't have known to ask about — and separate signal from noise. Good research here tends to snowball: the people who keep showing up are worth reading directly, threads with real engagement often hold the best detail, and links that many posts point to are usually the primary source. Engagement is a signal but not the truth; a small account that built the thing beats a big account summarizing it. Watch dates closely — "latest" means latest as of today.

{depth_note} You have a research budget of about ${budget:.0f} for this question (workers' spending counts toward it); every tool result shows the running total. Spend it where it buys new information.

When you're done researching, write the final briefing as your answer, in Markdown. It is the whole deliverable — the person reads only this. Make it something they can read in a few minutes and come away genuinely current:
- Open with a short TL;DR of what matters most right now.
- Then organize by theme or storyline, not by search. Lead with what's new and important.
- Cite everything inline with links to the actual post or page, e.g. ([@handle](https://x.com/...)) or ([paper](https://...)). Quote people when their exact words matter.
- Give dates. Say who people are when it matters why they said something.
- Be clear about what's confirmed vs. claimed vs. rumor, and where informed people disagree.
- Close with what to watch next and the handful of accounts most worth following on this, with one line on why.
- If something important couldn't be found or verified, say so.
Write the briefing only — no preamble about your process."""

DEPTH_NOTES = {
    "quick": "This is a quick question: do a focused handful of searches yourself and answer within a few minutes.",
    "deep": "This is a deep research request. Use `delegate` to send parallel workers after the distinct angles of the question (usually 3–6), then read their notes, chase gaps and contradictions yourself or with a second round, and only then write.",
    "max": "This is an exhaustive research request. Use `delegate` generously — up to 10 parallel workers per round, and a second round on whatever the first turned up (new names, new threads, open questions). Leave no important corner unchecked.",
}

WORKER_SYSTEM = """You are a research worker on a team keeping someone fully up to date on the state of the world. Today is {today}. The lead researcher gave you one angle of a larger question; dig into it thoroughly and report back. {sources}

X is where things surface first; the web is where you confirm and find primary sources. Follow what you find: people who keep coming up, threads with real discussion, links many posts point to. Searches cost real money and the team shares one budget (each tool result shows the running total), so make each search count, don't repeat near-identical queries, and stop once you've covered your angle.

Your final answer is notes for the lead, not a polished essay. Make them dense and complete:
- Findings, each with its source URL (x.com post or web page), date, who said it (and who they are), and engagement when known. Quote key lines verbatim.
- The accounts that matter most on this angle.
- Primary-source links (papers, repos, announcements) and what they show.
- Disagreements, unverified claims, and open questions.
- Anything surprising you found outside your assignment that the lead should know about."""


class Run:
    def __init__(self, question: str, depth: str, budget: float | None = None):
        self.id = uuid.uuid4().hex[:12]
        self.question = question
        self.depth = depth if depth in DEPTHS else "deep"
        self.events: list[dict] = []
        self.cost = Cost(budget=budget or DEPTHS[self.depth]["budget"])
        self.status = "running"
        self.report: str | None = None
        self._cond = asyncio.Condition()
        db.create_run(self.id, question, self.depth)

    async def emit(self, type_: str, **data) -> None:
        self.events.append({"type": type_, "t": time.time(), **data})
        async with self._cond:
            self._cond.notify_all()

    async def wait(self, after: int) -> None:
        async with self._cond:
            await self._cond.wait_for(lambda: len(self.events) > after or self.status != "running")


RUNS: dict[str, Run] = {}


def _short(value, n: int = 400) -> str:
    s = value if isinstance(value, str) else json.dumps(value)
    return s if len(s) <= n else s[:n] + "…"


async def _exec_tool(run: Run, agent: str, block, worker_turns: int, worker_effort: str, max_workers: int) -> dict:
    name, args = block.name, block.input if isinstance(block.input, dict) else {}
    left = run.cost.search_room()
    est = EST_COST.get(name, 0.0)
    if run.cost.budget and name != "delegate" and left < max(est, 0.02):
        cheaper = [n for n, c in EST_COST.items() if c <= left]
        hint = f" Cheaper options that still fit: {', '.join(cheaper)}, web_search." if cheaper and left > 0.05 else " No more searching — write up what you have."
        return {"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                "content": f"Not enough search budget left for {name} (${max(left, 0):.2f} available; ${run.cost.usd:.2f} of ${run.cost.budget:.2f} spent).{hint}"}
    run.cost.tick(name)
    run.cost.reserved += est
    started = time.time()
    await run.emit("tool", agent=agent, name=name, input=args)
    try:
        if name == "x_search_grok":
            out = await grok.grok_x_search(run.cost, **args)
        elif name == "x_search":
            out = await xapi.search(run.cost, **args)
        elif name == "x_thread":
            out = await xapi.thread(run.cost, **args)
        elif name == "x_user_posts":
            out = await xapi.user_posts(run.cost, **args)
        elif name == "delegate":
            out = await _delegate(run, args.get("tasks") or [], worker_turns, worker_effort, max_workers)
        else:
            raise ValueError(f"unknown tool {name}")
        is_error = False
    except Exception as e:  # report tool failures back to the model instead of crashing the run
        out, is_error = f"Error: {e}", True
    finally:
        run.cost.reserved -= est
    await run.emit("tool_done", agent=agent, name=name, ms=int((time.time() - started) * 1000),
                   preview=_short(out, 600), error=is_error, cost=run.cost.summary())
    return {"type": "tool_result", "tool_use_id": block.id, "content": f"{out}\n\n{run.cost.budget_note()}", "is_error": is_error}


async def _delegate(run: Run, tasks: list[dict], worker_turns: int, worker_effort: str, max_workers: int) -> str:
    if not tasks:
        return "No tasks given."
    if run.cost.budget and run.cost.search_room() <= 0:
        return "Research budget used up — no workers sent. Write up what you have."
    tasks = tasks[: max(1, max_workers)]
    sem = asyncio.Semaphore(6)

    async def one(i: int, task: dict) -> str:
        label = task.get("title") or f"worker {i + 1}"
        async with sem:
            await run.emit("worker_start", agent=label, brief=task.get("brief", ""))
            try:
                notes = await _agent_loop(
                    run, label,
                    system=WORKER_SYSTEM.format(today=_today(), sources=_sources_note()),
                    messages=[{"role": "user", "content": f"Original question: {run.question}\n\nYour assignment: {task.get('brief', '')}"}],
                    tools=_source_tools() + SERVER_TOOLS,
                    effort=worker_effort, max_turns=worker_turns,
                )
            except Exception as e:
                notes = f"(worker failed: {e})"
            await run.emit("worker_done", agent=label, notes=notes)
            return f"## Worker: {label}\n\n{notes}"

    results = await asyncio.gather(*(one(i, t) for i, t in enumerate(tasks)))
    return "\n\n---\n\n".join(results)


async def _agent_loop(run: Run, agent: str, system: str, messages: list, tools: list, effort: str,
                      max_turns: int, worker_turns: int = 0, worker_effort: str = "medium", max_workers: int = 0) -> str:
    turn = 0
    final_turn = False
    while True:
        turn += 1
        kwargs = dict(
            model=CLAUDE_MODEL,
            max_tokens=64000,
            system=system,
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": effort},
            cache_control={"type": "ephemeral"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if final_turn:
            kwargs["tool_choice"] = {"type": "none"}
        try:
            async with _claude().beta.messages.stream(**kwargs) as stream:
                msg = await stream.get_final_message()
        except anthropic.BadRequestError:
            if not final_turn:
                raise
            # Wrap-up request rejected (e.g. mid-pause history shape); return what the agent has written so far.
            return "\n\n".join(b.text for m in messages if m["role"] == "assistant"
                                 for b in m["content"] if getattr(b, "type", None) == "text").strip()
        run.cost.add_claude(msg.usage)
        messages.append({"role": "assistant", "content": msg.content})

        for b in msg.content:
            if b.type == "thinking" and getattr(b, "thinking", ""):
                await run.emit("thinking", agent=agent, text=b.thinking)
            elif b.type == "server_tool_use":
                run.cost.tick(b.name)
                await run.emit("tool", agent=agent, name=b.name, input=b.input)
        await run.emit("cost", cost=run.cost.summary())

        if msg.stop_reason == "refusal":
            raise RuntimeError("model declined this request")
        if msg.stop_reason == "pause_turn":
            if run.cost.budget and run.cost.search_room() <= 0 and not final_turn:
                final_turn = True
                messages.append({"role": "user", "content": "You've used your research budget. Write your final answer now with what you have."})
            continue

        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        tool_uses = [b for b in msg.content if b.type == "tool_use"]
        if not tool_uses or final_turn:
            if msg.stop_reason == "max_tokens" and not text:
                raise RuntimeError("ran out of output tokens")
            return text

        results = await asyncio.gather(*(
            _exec_tool(run, agent, b, worker_turns, worker_effort, max_workers) for b in tool_uses
        ))
        content: list = list(results)
        if turn >= max_turns - 1 or (run.cost.budget and run.cost.search_room() <= 0):
            final_turn = True
            content.append({"type": "text", "text": "You've used your research budget. Write your final answer now with what you have."})
        messages.append({"role": "user", "content": content})


async def execute(run: Run) -> None:
    cfg = DEPTHS[run.depth]
    tools = _source_tools() + SERVER_TOOLS + ([DELEGATE_TOOL] if cfg["max_workers"] else [])
    system = LEAD_SYSTEM.format(today=_today(), sources=_sources_note(), depth_note=DEPTH_NOTES[run.depth], budget=run.cost.budget)
    await run.emit("start", question=run.question, depth=run.depth)
    try:
        report = await _agent_loop(
            run, "lead", system=system,
            messages=[{"role": "user", "content": run.question}],
            tools=tools, effort=cfg["lead_effort"], max_turns=cfg["lead_turns"],
            worker_turns=cfg["worker_turns"], worker_effort=cfg["worker_effort"], max_workers=cfg["max_workers"],
        )
        run.report = report
        run.status = "done"
        await run.emit("report", markdown=report, cost=run.cost.summary())
    except asyncio.CancelledError:
        run.status = "cancelled"
    except Exception as e:
        run.status = "error"
        await run.emit("error", message=f"{type(e).__name__}: {e}")
    finally:
        db.finish_run(run.id, run.status, run.report, run.cost.summary(), run.events)
        await run.emit("end", status=run.status)


def start(question: str, depth: str, budget: float | None = None) -> Run:
    run = Run(question, depth, budget)
    RUNS[run.id] = run
    run.task = asyncio.create_task(execute(run))
    return run


def cancel(run_id: str) -> bool:
    run = RUNS.get(run_id)
    if not run or run.status != "running":
        return False
    run.task.cancel()
    return True
