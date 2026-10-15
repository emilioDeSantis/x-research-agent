import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-4.7")

DB_PATH = ROOT / "data" / "research.db"

# Prices (USD) used for the per-report cost estimate.
PRICE = {
    "claude_in": 4.00 / 1e6,
    "claude_out": 20.00 / 1e6,
    "claude_cache_read": 0.20 / 1e6,
    "claude_web_search": 10.00 / 1000,
    "grok_in": 2.00 / 1e6,
    "grok_out": 6.00 / 1e6,
    "grok_post": 5.00 / 1000,
    "grok_user": 10.00 / 1000,
    "x_post": 0.005,
    "x_user": 0.010,
}


def has_xai() -> bool:
    return bool(XAI_API_KEY)


def has_x_api() -> bool:
    return bool(X_BEARER_TOKEN)
