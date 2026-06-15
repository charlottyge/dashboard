#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = TOOLKIT_ROOT.parent
PUBLIC_ROOT = WORKSPACE_ROOT / "public"
DATA_ROOT = PUBLIC_ROOT / "data"
INTRADAY_ROOT = WORKSPACE_ROOT / "tool" / "intraday_exports"
PUBLISH_SCRIPT = TOOLKIT_ROOT / "scripts" / "publish_static_site.py"

CHECKPOINT_DIRS = {
    "09:25": "scan_0925",
    "0925": "scan_0925",
    "scan_0925": "scan_0925",
    "09:45": "scan_0945",
    "0945": "scan_0945",
    "scan_0945": "scan_0945",
    "10:30": "scan_1030",
    "1030": "scan_1030",
    "scan_1030": "scan_1030",
    "11:20": "scan_1120",
    "1120": "scan_1120",
    "scan_1120": "scan_1120",
    "13:30": "scan_1330",
    "1330": "scan_1330",
    "scan_1330": "scan_1330",
    "14:30": "scan_1430",
    "1430": "scan_1430",
    "14:40": "scan_1430",
    "1440": "scan_1430",
    "scan_1430": "scan_1430",
    "scan_1440": "scan_1430",
    "15:10": "scan_1510",
    "1510": "scan_1510",
    "scan_1510": "scan_1510",
    "strategy": "scan_strategy_1430",
    "14:20": "scan_strategy_1430",
    "scan_strategy_1430": "scan_strategy_1430",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Codex-generated AI analysis into the dashboard.")
    parser.add_argument("--input", required=True, type=Path, help="JSON file containing ai_analysis fields.")
    parser.add_argument("--date", default="", help="Trading date. Default: latest date in public/data/site.json.")
    parser.add_argument("--checkpoint", default="", help="Checkpoint such as 10:30 or scan_1030. Default: latest checkpoint.")
    parser.add_argument("--no-publish", action="store_true", help="Write analysis files but do not regenerate site.json.")
    parser.add_argument("--print-target", action="store_true", help="Print latest target and exit without writing.")
    return parser.parse_args()


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def normalize_checkpoint(value: str) -> str:
    normalized = CHECKPOINT_DIRS.get(str(value or "").strip())
    if not normalized:
        raise SystemExit(f"Unsupported checkpoint: {value}")
    return normalized


def latest_target(site: dict) -> tuple[str, str]:
    days = site.get("timeline_days") or []
    for day in days:
        checkpoints = [item for item in day.get("checkpoints", []) if item.get("id")]
        if checkpoints:
            return str(day.get("date") or ""), str(checkpoints[-1].get("id") or "")
    raise SystemExit("No checkpoint found in public/data/site.json. Run a scan first.")


def resolve_target(args: argparse.Namespace) -> tuple[str, str]:
    site = read_json(DATA_ROOT / "site.json")
    if not site:
        raise SystemExit(f"Missing or invalid {DATA_ROOT / 'site.json'}")
    latest_date, latest_checkpoint = latest_target(site)
    report_date = args.date or latest_date
    checkpoint = normalize_checkpoint(args.checkpoint) if args.checkpoint else normalize_checkpoint(latest_checkpoint)
    return report_date, checkpoint


def write_override(report_date: str, checkpoint: str, payload: dict) -> Path:
    override_dir = DATA_ROOT / "ai_analysis_overrides"
    override_dir.mkdir(parents=True, exist_ok=True)
    target = override_dir / f"{report_date}_{checkpoint}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def write_raw_if_available(report_date: str, checkpoint: str, payload: dict) -> Path | None:
    target_dir = INTRADAY_ROOT / report_date / checkpoint
    if not (target_dir / "summary.json").exists():
        return None
    target = target_dir / "ai_analysis.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def update_site_json_direct(report_date: str, checkpoint: str, payload: dict) -> bool:
    site_path = DATA_ROOT / "site.json"
    site = read_json(site_path)
    changed = False
    for day in site.get("timeline_days") or []:
        if str(day.get("date") or "") != report_date:
            continue
        for item in day.get("checkpoints") or []:
            if item.get("id") == checkpoint:
                item["ai_analysis"] = payload
                changed = True
    if changed:
        site_path.write_text(json.dumps(site, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def publish() -> None:
    result = subprocess.run([sys.executable, str(PUBLISH_SCRIPT)], cwd=str(WORKSPACE_ROOT), text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> int:
    args = parse_args()
    report_date, checkpoint = resolve_target(args)
    if args.print_target:
        print(json.dumps({"date": report_date, "checkpoint": checkpoint}, ensure_ascii=False, indent=2))
        return 0

    payload = read_json(args.input)
    if not payload:
        raise SystemExit(f"Missing or invalid AI analysis JSON: {args.input}")
    payload.setdefault("generated_at", datetime.now().isoformat(timespec="seconds"))
    payload.setdefault("source", "a-share-intraday-decision")

    override_path = write_override(report_date, checkpoint, payload)
    raw_path = write_raw_if_available(report_date, checkpoint, payload)
    if not args.no_publish:
        publish()
    direct_updated = update_site_json_direct(report_date, checkpoint, payload)

    print(
        json.dumps(
            {
                "date": report_date,
                "checkpoint": checkpoint,
                "override": str(override_path),
                "raw_ai_analysis": str(raw_path) if raw_path else "",
                "site_json_updated": direct_updated,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
