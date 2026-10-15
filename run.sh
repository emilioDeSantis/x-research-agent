#!/bin/zsh
cd "$(dirname "$0")"
exec .venv/bin/uvicorn app.server:app --port 8787 "$@"
