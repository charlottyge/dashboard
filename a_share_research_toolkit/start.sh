#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PORT="${A_SHARE_TOOLKIT_PORT:-8765}"
echo "Starting A-share research toolkit at http://127.0.0.1:${PORT}"
python3 app.py
