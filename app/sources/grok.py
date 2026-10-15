"""X search through xAI's Grok `x_search` server tool (semantic + keyword search over X)."""

import httpx

from ..config import GROK_MODEL, XAI_API_KEY
from ..cost import Cost

INSTRUCTIONS = """You are a search backend for a research agent, not a chat assistant.
Search X thoroughly for the request below — use several keyword and semantic searches, look up the relevant accounts, and open threads that matter.

Return what you found as raw material, not an essay:
- For each relevant post: @handle (and who they are, if known), date, approximate engagement if visible, what it says (quote the key line verbatim), and its x.com URL.
- Then list the accounts that seem most authoritative or most active on this topic, with one line on each.
- Note any links (papers, repos, blog posts, announcements) that several posts point to.
Prefer primary sources (the people who built / announced / measured the thing) over aggregators and engagement bait.
Do not pad. If you found little, say so."""


async def grok_x_search(
    cost: Cost,
    query: str,
    from_date: str | None = None,
    to_date: str | None = None,
    handles: list[str] | None = None,
    exclude_handles: list[str] | None = None,
    include_media: bool = False,
) -> str:
    tool: dict = {"type": "x_search"}
    if from_date:
        tool["from_date"] = from_date
    if to_date:
        tool["to_date"] = to_date
    if handles:
        tool["allowed_x_handles"] = [h.lstrip("@") for h in handles][:20]
    elif exclude_handles:
        tool["excluded_x_handles"] = [h.lstrip("@") for h in exclude_handles][:20]
    if include_media:
        tool["enable_image_understanding"] = True
        tool["enable_video_understanding"] = True

    body = {
        "model": GROK_MODEL,
        "instructions": INSTRUCTIONS,
        "input": query,
        "tools": [tool],
    }
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            "https://api.x.ai/v1/responses",
            headers={"Authorization": f"Bearer {XAI_API_KEY}"},
            json=body,
        )
    if r.status_code >= 400:
        raise RuntimeError(f"xAI {r.status_code}: {r.text[:500]}")
    data = r.json()

    usage = data.get("usage") or {}
    cost.grok_in += usage.get("input_tokens", 0) or 0
    cost.grok_out += usage.get("output_tokens", 0) or 0
    details = usage.get("server_side_tool_usage_details") or {}
    cost.grok_posts += details.get("x_posts_fetched", 0) or 0
    cost.grok_users += details.get("x_users_fetched", 0) or 0

    text_parts = []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    text_parts.append(c.get("text", ""))
    text = "\n".join(text_parts).strip() or "(no results)"

    citations = data.get("citations") or []
    if citations:
        urls = [c if isinstance(c, str) else c.get("url", "") for c in citations]
        text += "\n\nAll sources Grok saw:\n" + "\n".join(u for u in urls if u)
    return text
