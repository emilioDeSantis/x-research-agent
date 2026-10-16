import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from . import agent, db, export
from .config import ANTHROPIC_API_KEY, ROOT, has_x_api, has_xai

app = FastAPI(title="X Research Agent")
db.mark_interrupted()


class Ask(BaseModel):
    question: str
    depth: str = "deep"
    budget: float | None = None


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/status")
def status():
    return {"anthropic": bool(ANTHROPIC_API_KEY), "xai": has_xai(), "x_api": has_x_api()}


@app.post("/api/ask")
async def ask(body: Ask):
    if not body.question.strip():
        raise HTTPException(400, "empty question")
    run = agent.start(body.question.strip(), body.depth, body.budget)
    return {"id": run.id}


@app.post("/api/runs/{run_id}/cancel")
def cancel(run_id: str):
    if not agent.cancel(run_id):
        raise HTTPException(404, "no running run with that id")
    return {"ok": True}


@app.get("/api/runs")
def runs():
    live = {r.id: r.status for r in agent.RUNS.values()}
    return [r | {"status": live.get(r["id"], r["status"])} for r in db.list_runs()]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = agent.RUNS.get(run_id)
    if run:
        return {"id": run.id, "question": run.question, "depth": run.depth, "status": run.status,
                "report": run.report, "cost": run.cost.summary(), "events": run.events}
    stored = db.get_run(run_id)
    if not stored:
        raise HTTPException(404)
    return stored


@app.get("/runs/{run_id}/share", response_class=HTMLResponse)
def share(run_id: str):
    run = db.get_run(run_id)
    if not run or not run.get("report"):
        raise HTTPException(404, "no finished report for that run")
    page = export.render(run)
    # The template is written as an artifact body; wrap it so it also opens as a normal page.
    return "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"></head><body style=\"margin:0\">" + page + "</body></html>"


@app.get("/api/runs/{run_id}/stream")
async def stream(run_id: str, after: int = 0):
    run = agent.RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "run not live")

    async def gen():
        i = after
        while True:
            while i < len(run.events):
                yield f"data: {json.dumps(run.events[i])}\n\n"
                i += 1
            if run.status != "running" and i >= len(run.events):
                return
            try:
                await asyncio.wait_for(run.wait(i), timeout=15)
            except asyncio.TimeoutError:
                yield ": ping\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
