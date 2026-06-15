#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path


TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = TOOLKIT_ROOT.parent
PUBLIC_ROOT = WORKSPACE_ROOT if (WORKSPACE_ROOT / "index.html").exists() else WORKSPACE_ROOT / "public"
SCRIPT_ROOT = TOOLKIT_ROOT / "vendor" / "intraday_decision" / "scripts"
CONFIG_PATH = TOOLKIT_ROOT / "toolkit_config.json"
PUBLISH_SCRIPT = TOOLKIT_ROOT / "scripts" / "publish_static_site.py"

CHECKPOINT_SCRIPTS = {
    "09:25": "scan_0925.py",
    "0925": "scan_0925.py",
    "09:45": "scan_0945.py",
    "0945": "scan_0945.py",
    "10:30": "scan_1030.py",
    "1030": "scan_1030.py",
    "11:20": "scan_1120.py",
    "1120": "scan_1120.py",
    "13:30": "scan_1330.py",
    "1330": "scan_1330.py",
    "14:30": "scan_1440.py",
    "1430": "scan_1440.py",
    "14:40": "scan_1440.py",
    "1440": "scan_1440.py",
    "15:10": "scan_1510.py",
    "1510": "scan_1510.py",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run intraday checkpoint, publish static dashboard, and push GitHub Pages.")
    parser.add_argument("--checkpoint", default="", help="Checkpoint such as 09:45, 10:30, 14:30, 1510.")
    parser.add_argument("--asof-time", default="", help="Optional HH:MM cutoff for intraday minute metrics; defaults to checkpoint.")
    parser.add_argument("--strategy", action="store_true", help="Run strategy package only.")
    parser.add_argument("--date", default=date.today().isoformat(), help="Report date, default today.")
    parser.add_argument("--pool", default="all-a", choices=["all-a", "watchlist"])
    parser.add_argument("--limit", type=int, default=0, help="Optional scan limit for testing.")
    parser.add_argument("--max-workers", type=int, default=0)
    parser.add_argument("--max-float-shares", type=float, default=500_000_000)
    parser.add_argument("--no-push", action="store_true", help="Commit locally but do not push to GitHub.")
    parser.add_argument("--no-commit", action="store_true", help="Update public files but do not git commit.")
    parser.add_argument("--skip-scan", action="store_true", help="Only publish/commit/push existing outputs.")
    return parser.parse_args()


def load_config() -> dict:
    default = {
        "intraday_python": sys.executable,
        "intraday_export_root": str(WORKSPACE_ROOT / "tool" / "intraday_exports"),
        "investment_dir": str(WORKSPACE_ROOT / "tool" / "cloud_inputs"),
    }
    if CONFIG_PATH.exists():
        try:
            default.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    if not Path(str(default.get("intraday_python", ""))).exists():
        default["intraday_python"] = sys.executable
    investment_dir = Path(str(default.get("investment_dir") or ""))
    if investment_dir and not investment_dir.is_absolute():
        investment_dir = WORKSPACE_ROOT / investment_dir
        default["investment_dir"] = str(investment_dir)
    if not investment_dir.exists():
        default["investment_dir"] = str(WORKSPACE_ROOT / "tool" / "cloud_inputs")
    export_root = Path(str(default.get("intraday_export_root") or ""))
    if export_root and not export_root.is_absolute():
        export_root = WORKSPACE_ROOT / export_root
        default["intraday_export_root"] = str(export_root)
    if str(export_root).startswith("/Users/") and not export_root.exists():
        default["intraday_export_root"] = str(WORKSPACE_ROOT / "tool" / "intraday_exports")
    return default


def run(command: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command))
    result = subprocess.run(command, cwd=str(cwd), text=True, check=False)
    if check and result.returncode != 0:
        raise SystemExit(result.returncode)
    return result


def output_dir(export_root: Path, report_date: str, checkpoint: str) -> Path:
    normalized = checkpoint.replace(":", "")
    name = "scan_1430" if normalized in {"1430", "1440"} else f"scan_{normalized}"
    return export_root / report_date / name


def scan_command(config: dict, report_date: str, checkpoint: str, args: argparse.Namespace) -> list[str]:
    script = CHECKPOINT_SCRIPTS.get(checkpoint)
    if not script:
        raise SystemExit(f"unsupported checkpoint: {checkpoint}")
    export_root = Path(config["intraday_export_root"])
    command = [
        config["intraday_python"],
        "-u",
        str(SCRIPT_ROOT / script),
        "--pool",
        args.pool,
        "--out",
        str(output_dir(export_root, report_date, checkpoint)),
    ]
    if config.get("investment_dir"):
        command.extend(["--investment-dir", str(config["investment_dir"])])
    if checkpoint not in {"09:25", "0925", "09:45", "0945", "10:30", "1030"}:
        command.extend(["--previous-root", str(export_root / report_date)])
    if args.asof_time:
        command.extend(["--asof-time", str(args.asof_time)])
    if args.limit:
        command.extend(["--limit", str(args.limit)])
    if args.max_workers:
        command.extend(["--max-workers", str(args.max_workers)])
    return command


def strategy_command(config: dict, report_date: str, args: argparse.Namespace) -> list[str]:
    out_dir = Path(config["intraday_export_root"]) / report_date / "scan_strategy_1430"
    command = [
        config["intraday_python"],
        "-u",
        str(SCRIPT_ROOT / "scan_strategy.py"),
        "--out",
        str(out_dir),
        "--checkpoint",
        "14:20",
        "--max-float-shares",
        str(args.max_float_shares),
    ]
    if args.limit:
        command.extend(["--limit", str(args.limit)])
    if args.max_workers:
        command.extend(["--max-workers", str(args.max_workers)])
    return command


def run_scans(args: argparse.Namespace, config: dict) -> None:
    checkpoint = args.checkpoint.strip()
    if args.strategy:
        run(strategy_command(config, args.date, args), SCRIPT_ROOT)
        return
    if not checkpoint:
        raise SystemExit("provide --checkpoint or --strategy")
    run(scan_command(config, args.date, checkpoint, args), SCRIPT_ROOT)
    if checkpoint in {"14:30", "1430", "14:40", "1440"}:
        run(strategy_command(config, args.date, args), SCRIPT_ROOT)


def publish() -> None:
    run([sys.executable, str(PUBLISH_SCRIPT)], WORKSPACE_ROOT)


def git_status_porcelain() -> str:
    return subprocess.check_output(["git", "status", "--short"], cwd=str(PUBLIC_ROOT), text=True)


def commit_public(args: argparse.Namespace) -> None:
    status = git_status_porcelain()
    if not status.strip():
        print("public/ has no changes to commit")
        return
    if args.no_commit:
        print("public/ changed, --no-commit set; leaving files unstaged")
        return
    run(["git", "add", "app.js", "data", "index.html", "styles.css"], PUBLIC_ROOT)
    status_after_add = git_status_porcelain()
    if not status_after_add.strip():
        print("nothing staged")
        return
    message = f"Update dashboard {args.date}"
    if args.checkpoint:
        message += f" {args.checkpoint}"
    if args.strategy:
        message += " strategy"
    run(["git", "commit", "-m", message], PUBLIC_ROOT)


def push_public(args: argparse.Namespace) -> None:
    if args.no_push or args.no_commit:
        return
    result = run(["git", "push", "origin", "main"], PUBLIC_ROOT, check=False)
    if result.returncode != 0:
        raise SystemExit("GitHub push failed. Local commit is kept; retry later with: cd public && git push origin main")


def main() -> int:
    args = parse_args()
    config = load_config()
    if not args.skip_scan:
        run_scans(args, config)
    publish()
    commit_public(args)
    push_public(args)
    print("Dashboard publish flow finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
