#!/usr/bin/env bash
# One-time setup: creates the Python environment, installs dependencies, and makes .env from the template.
set -e
cd "$(dirname "$0")"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10 or newer is required")'
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "Done. Put your API keys in .env, then run ./run.sh and open http://localhost:8787"
