#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Checking Python..."
python3 --version

if [ -d "../a_share_rotation_research" ]; then
  echo "Installing weekly research dependencies..."
  if [ ! -d "../a_share_rotation_research/.venv" ]; then
    python3 -m venv "../a_share_rotation_research/.venv"
  fi
  "../a_share_rotation_research/.venv/bin/python" -m pip install -r "../a_share_rotation_research/requirements.txt"
fi

if [ -d "../tool" ] && [ -f "../tool/requirements.txt" ]; then
  echo "Installing intraday helper dependencies..."
  if [ ! -d "../tool/.venv" ]; then
    python3 -m venv "../tool/.venv"
  fi
  "../tool/.venv/bin/python" -m pip install -r "../tool/requirements.txt"
fi

chmod +x start.sh scripts/backup.sh scripts/restore.sh
echo "Done. Run ./start.sh and open http://127.0.0.1:8765"
