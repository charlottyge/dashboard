#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="$(cd "${ROOT}/.." && pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="${ROOT}/backup_${STAMP}.tar.gz"

cd "${WORKSPACE}"
tar -czf "${OUT}" \
  a_share_research_toolkit/toolkit_config.json \
  a_share_research_toolkit/vendor \
  a_share_rotation_research/config \
  a_share_rotation_research/data/reports \
  a_share_rotation_research/data/processed \
  tool/data \
  tool/intraday_exports

echo "${OUT}"
