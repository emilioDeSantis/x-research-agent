import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import agent, db
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
