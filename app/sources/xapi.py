"""Official X API v2 (pay-per-use). Exact operator search, threads, user timelines."""

import httpx

from ..config import X_BEARER_TOKEN
from ..cost import Cost
from .. import db

BASE = "https://api.x.com/2"
TWEET_FIELDS = "created_at,public_metrics,author_id,conversation_id,entities,note_tweet,referenced_tweets,lang"
USER_FIELDS = "username,name,description,public_metrics,verified"


async def _get(path: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(BASE + path, params=params, headers={"Authorization": f"Bearer {X_BEARER_TOKEN}"})
    if r.status_code == 429:
        raise RuntimeError(f"X API rate limited; resets at {r.headers.get('x-rate-limit-reset')}")
    if r.status_code >= 400:
        raise RuntimeError(f"X API {r.status_code}: {r.text[:500]}")
    return r.json()


def _format(data: dict, cost: Cost, sort: str = "likes", min_likes: int = 0, limit: int = 40) -> str:
    tweets = data.get("data") or []
    users = {u["id"]: u for u in (data.get("includes") or {}).get("users", [])}
    cost.x_posts += len(tweets)
    cost.x_users += len(users)
    db.save_posts(tweets, users)

    def likes(t):
        return (t.get("public_metrics") or {}).get("like_count", 0)

    tweets = [t for t in tweets if likes(t) >= min_likes]
    if sort == "likes":
        tweets.sort(key=likes, reverse=True)
    elif sort == "recent":
        tweets.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    if not tweets:
        return "(no posts matched)"

    lines = []
    for t in tweets[:limit]:
        u = users.get(t.get("author_id"), {})
        handle = u.get("username", "?")
        m = t.get("public_metrics") or {}
        text = (t.get("note_tweet") or {}).get("text") or t.get("text", "")
        links = [x.get("expanded_url") for x in (t.get("entities") or {}).get("urls", []) if x.get("expanded_url")]
        links = [l for l in links if "x.com/" not in l and "twitter.com/" not in l]
        followers = (u.get("public_metrics") or {}).get("followers_count")
        lines.append(
            f"@{handle} ({u.get('name', '')}, {followers or '?'} followers) · {t.get('created_at', '')[:16]} · "
            f"{m.get('like_count', 0)}♥ {m.get('retweet_count', 0)}↻ {m.get('reply_count', 0)}💬 {m.get('impression_count', 0)} views\n"
            f"{text}\n"
            + (f"links: {' '.join(links)}\n" if links else "")
            + f"https://x.com/{handle}/status/{t['id']} (conversation {t.get('conversation_id')})"
        )
    more = len(tweets) - limit
    return "\n\n".join(lines) + (f"\n\n(+{more} more not shown)" if more > 0 else "")


async def search(cost: Cost, query: str, sort_order: str = "relevancy", max_results: int = 100,
                 sort: str = "likes", min_likes: int = 0, start_time: str | None = None) -> str:
    q = query if "is:retweet" in query else f"{query} -is:retweet"
    params = {
        "query": q,
        "max_results": max(10, min(100, max_results)),
        "sort_order": sort_order,
        "tweet.fields": TWEET_FIELDS,
        "expansions": "author_id",
        "user.fields": USER_FIELDS,
    }
    if start_time:
        params["start_time"] = start_time
    return _format(await _get("/tweets/search/recent", params), cost, sort=sort, min_likes=min_likes)


async def thread(cost: Cost, tweet_id: str) -> str:
    root = await _get(f"/tweets/{tweet_id}", {
        "tweet.fields": TWEET_FIELDS, "expansions": "author_id", "user.fields": USER_FIELDS,
    })
    root_t = root.get("data") or {}
    conv = root_t.get("conversation_id", tweet_id)
    head = _format({"data": [root_t], "includes": root.get("includes")}, cost, sort="none")
    replies = await _get("/tweets/search/recent", {
        "query": f"conversation_id:{conv}",
        "max_results": 100,
        "tweet.fields": TWEET_FIELDS,
        "expansions": "author_id",
        "user.fields": USER_FIELDS,
    })
    return f"ROOT POST:\n{head}\n\nREPLIES / THREAD (top by likes, last 7 days only):\n" + _format(replies, cost, limit=30)


async def user_posts(cost: Cost, username: str, max_results: int = 50, include_replies: bool = False) -> str:
    u = await _get(f"/users/by/username/{username.lstrip('@')}", {"user.fields": USER_FIELDS})
    user = u.get("data")
    if not user:
        return f"(user @{username} not found)"
    cost.x_users += 1
    exclude = "retweets" if include_replies else "retweets,replies"
    data = await _get(f"/users/{user['id']}/tweets", {
        "max_results": max(5, min(100, max_results)),
        "exclude": exclude,
        "tweet.fields": TWEET_FIELDS,
        "expansions": "author_id",
        "user.fields": USER_FIELDS,
    })
    bio = f"@{user['username']} — {user.get('name', '')}: {user.get('description', '')}\n\n"
    return bio + _format(data, cost, sort="recent", limit=max_results)
