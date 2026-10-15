from dataclasses import dataclass, field

from .config import PRICE


@dataclass
class Cost:
    claude_in: int = 0
    claude_out: int = 0
    claude_cache_read: int = 0
    claude_web_searches: int = 0
    grok_in: int = 0
    grok_out: int = 0
    grok_posts: int = 0
    grok_users: int = 0
    x_posts: int = 0
    x_users: int = 0
    calls: dict = field(default_factory=dict)

    def add_claude(self, usage) -> None:
        self.claude_in += (usage.input_tokens or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        self.claude_out += usage.output_tokens or 0
        self.claude_cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        stu = getattr(usage, "server_tool_use", None)
        if stu is not None:
            self.claude_web_searches += getattr(stu, "web_search_requests", 0) or 0

    def tick(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    @property
    def usd(self) -> float:
        p = PRICE
        return (
            self.claude_in * p["claude_in"]
            + self.claude_out * p["claude_out"]
            + self.claude_cache_read * p["claude_cache_read"]
            + self.claude_web_searches * p["claude_web_search"]
            + self.grok_in * p["grok_in"]
            + self.grok_out * p["grok_out"]
            + self.grok_posts * p["grok_post"]
            + self.grok_users * p["grok_user"]
            + self.x_posts * p["x_post"]
            + self.x_users * p["x_user"]
        )

    def summary(self) -> dict:
        return {
            "usd": round(self.usd, 3),
            "claude_tokens": {"in": self.claude_in, "out": self.claude_out, "cache_read": self.claude_cache_read},
            "web_searches": self.claude_web_searches,
            "grok": {"posts": self.grok_posts, "users": self.grok_users, "in": self.grok_in, "out": self.grok_out},
            "x_api": {"posts": self.x_posts, "users": self.x_users},
            "calls": self.calls,
        }
