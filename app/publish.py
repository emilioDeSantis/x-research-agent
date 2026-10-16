"""Copy finished deep research into the shared GitHub repo and note it in the chat log.

Enabled when SHARED_REPO_DIR points at a local clone of the shared repo.
"""

import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from .config import SHARED_REPO_DEPTHS, SHARED_REPO_DIR, SHARED_REPO_ME, SHARED_REPO_THEM

_lock = threading.Lock()


def enabled_for(depth: str) -> bool:
    return bool(SHARED_REPO_DIR) and depth in SHARED_REPO_DEPTHS


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def _title(report: str, question: str) -> str:
    m = re.match(r"\s*#\s+(.+)", report)
    return (m.group(1) if m else question).strip()


def publish(question: str, report: str, depth: str, cost_usd: float) -> str:
    """Write the report into deep-research/, append a chat entry, commit and push. Returns the repo-relative path."""
    repo = Path(SHARED_REPO_DIR).expanduser()
    now = datetime.now()
    title = _title(report, question)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:70].rstrip("-")
    rel = f"deep-research/{now:%Y-%m-%d}-{slug}.md"

    with _lock:
        _git(repo, "pull", "--rebase", "--quiet")
        path = repo / rel
        n = 2
        while path.exists():
            rel = f"deep-research/{now:%Y-%m-%d}-{slug}-{n}.md"
            path, n = repo / rel, n + 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"<!-- Research agent report ({depth}, ~${cost_usd:.2f}). Question asked:\n{question}\n-->\n\n{report}")

        chat = repo / "chat.md"
        with chat.open("a") as f:
            f.write(
                f"\n---\n### {now:%Y-%m-%d %H:%M} · {SHARED_REPO_ME}'s Claude → {SHARED_REPO_THEM}\n\n"
                f"New deep research from the research agent: **{title}**\n\n"
                f"Question: {question.strip().splitlines()[0][:300]}\n\n"
                f"Files: `{rel}`\n"
            )
        _git(repo, "add", rel, "chat.md")
        _git(repo, "commit", "--quiet", "-m", f"Add deep research: {title[:60]}")
        try:
            _git(repo, "push", "--quiet")
        except RuntimeError:
            # Someone pushed in between; replay on top of theirs and try once more.
            try:
                _git(repo, "pull", "--rebase", "--quiet")
            except RuntimeError:
                subprocess.run(["git", "rebase", "--abort"], cwd=repo, capture_output=True)
                raise RuntimeError("couldn't merge with the latest shared repo; the report is committed locally, push it by hand")
            _git(repo, "push", "--quiet")
    return rel
