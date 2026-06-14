#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = TOOLKIT_ROOT.parent
INTRADAY_ROOT = WORKSPACE_ROOT / "tool" / "intraday_exports"

CHECKPOINT_DIRS = {
    "09:25": "scan_0925",
    "0925": "scan_0925",
    "09:45": "scan_0945",
    "0945": "scan_0945",
    "10:30": "scan_1030",
    "1030": "scan_1030",
    "11:20": "scan_1120",
    "1120": "scan_1120",
    "13:30": "scan_1330",
    "1330": "scan_1330",
    "14:30": "scan_1430",
    "1430": "scan_1430",
    "14:40": "scan_1430",
    "1440": "scan_1430",
    "15:10": "scan_1510",
    "1510": "scan_1510",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Save a manually generated AI analysis JSON into a checkpoint directory.")
    parser.add_argument("--input", required=True, type=Path, help="JSON file containing the analysis.")
    parser.add_argument("--date", default="", help="Trading date, default latest available date.")
    parser.add_argument("--checkpoint", default="", help="Checkpoint such as 10:30. Default latest checkpoint.")
    return parser.parse_args()


def latest_date_dir() -> Path:
    dirs = sorted([path for path in INTRADAY_ROOT.iterdir() if path.is_dir()], key=lambda item: item.name, reverse=True)
    if not dirs:
        raise SystemExit(f"No intraday export days under {INTRADAY_ROOT}")
    return dirs[0]


def checkpoint_dir(date_dir: Path, checkpoint: str) -> Path:
    if checkpoint:
        name = CHECKPOINT_DIRS.get(checkpoint)
        if not name:
            raise SystemExit(f"Unsupported checkpoint: {checkpoint}")
        target = date_dir / name
        if not target.exists():
            raise SystemExit(f"Checkpoint directory does not exist: {target}")
        return target
    summaries = sorted(date_dir.glob("scan_*/summary.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not summaries:
        raise SystemExit(f"No checkpoint summary under {date_dir}")
    return summaries[0].parent


def main() -> int:
    args = parse_args()
    date_dir = INTRADAY_ROOT / args.date if args.date else latest_date_dir()
    if not date_dir.exists():
        raise SystemExit(f"Date directory does not exist: {date_dir}")
    target_dir = checkpoint_dir(date_dir, args.checkpoint)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    payload.setdefault("generated_at", datetime.now().isoformat(timespec="seconds"))
    payload.setdefault("source", "manual_codex_analysis")
    target = target_dir / "ai_analysis.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved AI analysis: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
