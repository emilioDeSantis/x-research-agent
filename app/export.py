"""Render a finished run as a standalone, shareable HTML page.

    .venv/bin/python -m app.export <run_id> [out.html]
"""

import html
import re
import sys
from datetime import datetime
from pathlib import Path

from markdown_it import MarkdownIt

from . import db
from .config import ROOT

TEMPLATE = (ROOT / "static" / "share_template.html").read_text()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


_md = MarkdownIt("commonmark", {"typographer": True}).enable(["table", "smartquotes", "replacements"])


def render(run: dict, title: str | None = None) -> str:
    md = run["report"] or ""
    # The report's own H1 becomes the page heading.
    m = re.match(r"\s*#\s+(.+)\n", md)
    heading = m.group(1).strip() if m else run["question"]
    body_md = md[m.end():] if m else md

    body = _md.render(body_md)
    # Anchor ids for the contents list, and a class on the TL;DR block.
    toc = []

    def add_id(match):
        inner = match.group(1)
        text = re.sub(r"<[^>]+>", "", inner)
        sid = _slug(text)
        toc.append((sid, text))
        return f'<h2 id="{sid}">{inner}</h2>'

    body = re.sub(r"<h2>(.*?)</h2>", add_id, body)
    body = re.sub(r"<table>", '<div class="table-wrap"><table>', body)
    body = body.replace("</table>", "</table></div>")
    body = body.replace("<hr />", "").replace("<hr>", "")
    body = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', body)
    # Mark X links so handles read as handles.
    body = re.sub(r'<a href="(https://x\.com/[^"]+)"', r'<a class="x" href="\1"', body)
    # Wrap each h2 section so the TL;DR can be styled on its own.
    parts = re.split(r'(?=<h2 id=")', body)
    sections = []
    for p in parts:
        if not p.strip():
            continue
        cls = "tldr" if p.startswith('<h2 id="tl-dr"') else "sec"
        sections.append(f'<section class="{cls}">{p}</section>')
    body = "\n".join(sections)

    links = set(re.findall(r'href="(https?://[^"]+)"', body))
    x_links = {l for l in links if "x.com/" in l}
    when = datetime.fromtimestamp(run["finished_at"] or run["created_at"]).strftime("%B %-d, %Y")
    toc_html = "\n".join(f'<li><a href="#{sid}">{html.escape(text)}</a></li>' for sid, text in toc)

    return (TEMPLATE
            .replace("{{TITLE}}", html.escape(title or heading))
            .replace("{{HEADING}}", html.escape(heading))
            .replace("{{QUESTION}}", html.escape(run["question"]))
            .replace("{{DATE}}", when)
            .replace("{{N_SOURCES}}", str(len(links)))
            .replace("{{N_X}}", str(len(x_links)))
            .replace("{{TOC}}", toc_html)
            .replace("{{BODY}}", body))


if __name__ == "__main__":
    run = db.get_run(sys.argv[1])
    if not run or not run.get("report"):
        sys.exit("run not found or has no report")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "exports" / f"{sys.argv[1]}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    title = sys.argv[3] if len(sys.argv) > 3 else None
    out.write_text(render(run, title))
    print(out)
