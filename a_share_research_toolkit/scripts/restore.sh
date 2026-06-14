#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: ./scripts/restore.sh /path/to/backup.tar.gz" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="$(cd "${ROOT}/.." && pwd)"
ARCHIVE="$1"

if [ ! -f "${ARCHIVE}" ]; then
  echo "Backup not found: ${ARCHIVE}" >&2
  exit 1
fi

cd "${WORKSPACE}"
tar -xzf "${ARCHIVE}"
echo "Restored ${ARCHIVE}"
