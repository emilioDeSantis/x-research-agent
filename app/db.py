import json
import sqlite3
import time

from .config import DB_PATH

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript("""
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    depth TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    finished_at REAL,
    report TEXT,
    cost TEXT,
    events TEXT
);
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    handle TEXT,
    author_name TEXT,
    text TEXT,
    created_at TEXT,
    metrics TEXT,
    conversation_id TEXT,
    first_seen REAL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    handle TEXT,
    name TEXT,
    description TEXT,
    metrics TEXT,
    last_seen REAL
);
""")


def create_run(run_id: str, question: str, depth: str) -> None:
    _conn.execute("INSERT INTO runs (id, question, depth, status, created_at) VALUES (?, ?, ?, 'running', ?)",
                  (run_id, question, depth, time.time()))
    _conn.commit()


def finish_run(run_id: str, status: str, report: str | None, cost: dict, events: list) -> None:
    _conn.execute("UPDATE runs SET status=?, finished_at=?, report=?, cost=?, events=? WHERE id=?",
                  (status, time.time(), report, json.dumps(cost), json.dumps(events), run_id))
    _conn.commit()


def list_runs(limit: int = 100) -> list[dict]:
    rows = _conn.execute("SELECT id, question, depth, status, created_at, cost FROM runs ORDER BY created_at DESC LIMIT ?",
                         (limit,)).fetchall()
    return [dict(r) | {"cost": json.loads(r["cost"]) if r["cost"] else None} for r in rows]


def get_run(run_id: str) -> dict | None:
    r = _conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["cost"] = json.loads(d["cost"]) if d["cost"] else None
    d["events"] = json.loads(d["events"]) if d["events"] else []
    return d


def mark_interrupted() -> None:
    _conn.execute("UPDATE runs SET status='interrupted' WHERE status='running'")
    _conn.commit()


def save_posts(tweets: list[dict], users: dict[str, dict]) -> None:
    now = time.time()
    for u in users.values():
        _conn.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?, ?, ?)",
                      (u["id"], u.get("username"), u.get("name"), u.get("description"),
                       json.dumps(u.get("public_metrics")), now))
    for t in tweets:
        u = users.get(t.get("author_id"), {})
        text = (t.get("note_tweet") or {}).get("text") or t.get("text", "")
        _conn.execute("""INSERT INTO posts VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                         ON CONFLICT(id) DO UPDATE SET metrics=excluded.metrics""",
                      (t["id"], u.get("username"), u.get("name"), text, t.get("created_at"),
                       json.dumps(t.get("public_metrics")), t.get("conversation_id"), now))
    _conn.commit()
