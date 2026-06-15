#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


TOOLKIT_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = TOOLKIT_ROOT.parent
WEB_ROOT = TOOLKIT_ROOT / "web"
TOOL_DIR = WORKSPACE_ROOT / "tool"
PUBLIC_ROOT = WORKSPACE_ROOT / "public"
ROTATION_DIR = WORKSPACE_ROOT / "a_share_rotation_research"
INTRADAY_SCRIPT_DIR = TOOLKIT_ROOT / "vendor" / "intraday_decision" / "scripts"
RUN_AND_PUBLISH_SCRIPT = TOOLKIT_ROOT / "scripts" / "run_intraday_and_publish.py"
SYNC_AI_SCRIPT = TOOLKIT_ROOT / "scripts" / "sync_ai_analysis.py"
CONFIG_PATH = TOOLKIT_ROOT / "toolkit_config.json"
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


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


def load_config() -> dict:
    default = {
        "python": sys.executable,
        "intraday_python": sys.executable,
        "rotation_python": str(ROTATION_DIR / ".venv" / "bin" / "python") if (ROTATION_DIR / ".venv" / "bin" / "python").exists() else sys.executable,
        "investment_dir": str(Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Obsidian Vault/investment"),
        "intraday_export_root": str(TOOL_DIR / "intraday_exports"),
        "rotation_project_dir": str(ROTATION_DIR),
    }
    if CONFIG_PATH.exists():
        try:
            user_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            default.update(user_config)
        except Exception:
            pass
    return default


def write_json(handler: SimpleHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_request_json(handler: SimpleHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8") or "{}")


def safe_child(path: Path, roots: list[Path]) -> Path:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except ValueError:
            continue
    raise ValueError(f"path outside allowed roots: {path}")


def job_update(job_id: str, **patch: object) -> None:
    with JOBS_LOCK:
        JOBS[job_id].update(patch)
        JOBS[job_id]["updated_at"] = datetime.now().isoformat(timespec="seconds")


def run_command(job_id: str, command: list[str], cwd: Path, env: dict | None = None) -> None:
    output: list[str] = []
    job_update(job_id, status="running", command=command, cwd=str(cwd))
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            output.append(line.rstrip("\n"))
            if len(output) > 500:
                output = output[-500:]
            job_update(job_id, output="\n".join(output))
        code = process.wait()
        job_update(job_id, status="completed" if code == 0 else "failed", exit_code=code, output="\n".join(output))
    except Exception as exc:
        output.append(f"ERROR: {exc}")
        job_update(job_id, status="failed", exit_code=-1, output="\n".join(output))


def create_job(kind: str, payload: dict, command: list[str], cwd: Path, env: dict | None = None) -> dict:
    job_id = uuid.uuid4().hex[:12]
    now = datetime.now().isoformat(timespec="seconds")
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "payload": payload,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "command": command,
            "cwd": str(cwd),
            "output": "",
            "exit_code": None,
        }
    thread = threading.Thread(target=run_command, args=(job_id, command, cwd, env), daemon=True)
    thread.start()
    return JOBS[job_id]


def intraday_output_dir(report_date: str, checkpoint: str) -> Path:
    normalized = checkpoint.replace(":", "")
    if normalized in {"1430", "1440"}:
        name = "scan_1430"
    else:
        name = f"scan_{normalized}"
    return Path(load_config()["intraday_export_root"]) / report_date / name


def build_intraday_job(payload: dict) -> dict:
    config = load_config()
    checkpoint = str(payload.get("checkpoint") or "10:30")
    report_date = str(payload.get("date") or date.today().isoformat())
    pool = str(payload.get("pool") or "all-a")
    if checkpoint not in CHECKPOINT_SCRIPTS:
        raise ValueError(f"unsupported checkpoint: {checkpoint}")
    command = [
        sys.executable,
        str(RUN_AND_PUBLISH_SCRIPT),
        "--checkpoint",
        checkpoint,
        "--date",
        report_date,
        "--pool",
        pool,
        "--no-push",
        "--no-commit",
    ]
    if payload.get("limit"):
        command.extend(["--limit", str(payload["limit"])])
    if payload.get("max_workers"):
        command.extend(["--max-workers", str(payload["max_workers"])])
    return create_job("intraday_publish", payload, command, WORKSPACE_ROOT)


def build_strategy_job(payload: dict) -> dict:
    report_date = str(payload.get("date") or date.today().isoformat())
    command = [
        sys.executable,
        str(RUN_AND_PUBLISH_SCRIPT),
        "--strategy",
        "--date",
        report_date,
        "--no-push",
        "--no-commit",
    ]
    if payload.get("limit"):
        command.extend(["--limit", str(payload["limit"])])
    if payload.get("max_workers"):
        command.extend(["--max-workers", str(payload["max_workers"])])
    if payload.get("max_float_shares"):
        command.extend(["--max-float-shares", str(payload["max_float_shares"])])
    return create_job("strategy_publish", payload, command, WORKSPACE_ROOT)


def build_weekly_job(payload: dict) -> dict:
    config = load_config()
    rotation_dir = Path(config["rotation_project_dir"])
    as_of = str(payload.get("as_of") or payload.get("date") or date.today().isoformat())
    command = [config["rotation_python"], "src/weekly_runner.py", "--as-of", as_of]
    if payload.get("force_refresh"):
        command.append("--force-refresh")
    if payload.get("skip_daily_fetch"):
        command.append("--skip-daily-fetch")
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    env["PYTHONPYCACHEPREFIX"] = ".pycache_compile"
    return create_job("weekly", payload, command, rotation_dir, env=env)


def list_reports() -> dict:
    intraday_root = Path(load_config()["intraday_export_root"])
    weekly_root = ROTATION_DIR / "data" / "reports"
    return {
        "weekly_reports": list_files(weekly_root, ["*.md", "*.csv", "*.json"], limit=80),
        "intraday_exports": list_files(intraday_root, ["*.csv", "*.json"], limit=120),
        "dashboard_data": list_files(PUBLIC_ROOT / "data", ["*.json", "*.md"], limit=80),
    }


def dashboard_status() -> dict:
    site_path = PUBLIC_ROOT / "data" / "site.json"
    if not site_path.exists():
        return {"site_json": str(site_path), "exists": False}
    payload = json.loads(site_path.read_text(encoding="utf-8"))
    days = payload.get("timeline_days") or []
    latest_day = days[0] if days else {}
    checkpoints = latest_day.get("checkpoints") or []
    latest_checkpoint = checkpoints[-1] if checkpoints else {}
    return {
        "site_json": str(site_path),
        "exists": True,
        "generated_at": payload.get("generated_at", ""),
        "latest_date": latest_day.get("date", ""),
        "latest_checkpoint": latest_checkpoint.get("id", ""),
        "latest_label": latest_checkpoint.get("label", ""),
        "has_ai_analysis": bool(latest_checkpoint.get("ai_analysis")),
        "dashboard_url": str(PUBLIC_ROOT / "index.html"),
    }


def latest_ai_target() -> dict:
    status = dashboard_status()
    if not status.get("exists"):
        return status
    return {
        **status,
        "sync_command": "python3 a_share_research_toolkit/scripts/sync_ai_analysis.py --input /path/to/ai_analysis.json",
    }


def build_ai_sync_job(payload: dict) -> dict:
    analysis = payload.get("analysis")
    if not isinstance(analysis, dict):
        raise ValueError("payload.analysis must be an object matching ai_analysis schema")
    temp_dir = WORKSPACE_ROOT / "tool" / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    input_path = temp_dir / f"ai_analysis_{uuid.uuid4().hex[:8]}.json"
    input_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    command = [sys.executable, str(SYNC_AI_SCRIPT), "--input", str(input_path)]
    if payload.get("date"):
        command.extend(["--date", str(payload["date"])])
    if payload.get("checkpoint"):
        command.extend(["--checkpoint", str(payload["checkpoint"])])
    return create_job("ai_sync", payload, command, WORKSPACE_ROOT)


def list_files(root: Path, patterns: list[str], limit: int = 100) -> list[dict]:
    if not root.exists():
        return []
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(root.rglob(pattern))
    items = sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True)[:limit]
    return [
        {
            "name": item.name,
            "path": str(item),
            "relative_path": str(item.relative_to(WORKSPACE_ROOT)) if item.is_relative_to(WORKSPACE_ROOT) else str(item),
            "modified": datetime.fromtimestamp(item.stat().st_mtime).isoformat(timespec="seconds"),
            "size": item.stat().st_size,
        }
        for item in items
    ]


def preview_file(path_value: str) -> dict:
    path = safe_child(Path(path_value), [WORKSPACE_ROOT, TOOLKIT_ROOT])
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        return {"type": "csv", "columns": list(rows[0].keys()) if rows else [], "rows": rows[:80], "path": str(path)}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {"type": "text", "text": text[:50000], "path": str(path)}


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            config = load_config()
            write_json(
                self,
                {
                    "toolkit_root": str(TOOLKIT_ROOT),
                    "tool_dir": str(TOOL_DIR),
                    "public_root": str(PUBLIC_ROOT),
                    "rotation_dir": str(ROTATION_DIR),
                    "intraday_scripts": str(INTRADAY_SCRIPT_DIR),
                    "config": config,
                    "scripts_ready": INTRADAY_SCRIPT_DIR.exists(),
                    "rotation_ready": (ROTATION_DIR / "src" / "weekly_runner.py").exists(),
                },
            )
            return
        if parsed.path == "/api/dashboard":
            write_json(self, dashboard_status())
            return
        if parsed.path == "/api/ai/target":
            write_json(self, latest_ai_target())
            return
        if parsed.path == "/api/jobs":
            with JOBS_LOCK:
                jobs = sorted(JOBS.values(), key=lambda item: item["created_at"], reverse=True)
            write_json(self, {"jobs": jobs[:30]})
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
            write_json(self, {"job": job} if job else {"error": "not found"}, status=200 if job else 404)
            return
        if parsed.path == "/api/reports":
            write_json(self, list_reports())
            return
        if parsed.path == "/api/preview":
            try:
                path_value = parse_qs(parsed.query).get("path", [""])[0]
                write_json(self, preview_file(path_value))
            except Exception as exc:
                write_json(self, {"error": str(exc)}, status=400)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = read_request_json(self)
            if parsed.path == "/api/run/intraday":
                write_json(self, {"job": build_intraday_job(payload)}, status=202)
                return
            if parsed.path == "/api/run/strategy":
                write_json(self, {"job": build_strategy_job(payload)}, status=202)
                return
            if parsed.path == "/api/run/weekly":
                write_json(self, {"job": build_weekly_job(payload)}, status=202)
                return
            if parsed.path == "/api/ai/sync":
                write_json(self, {"job": build_ai_sync_job(payload)}, status=202)
                return
            write_json(self, {"error": "not found"}, status=404)
        except Exception as exc:
            write_json(self, {"error": str(exc)}, status=400)


def main() -> None:
    port = int(os.environ.get("A_SHARE_TOOLKIT_PORT", "8765"))
    os.chdir(WEB_ROOT)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"A-share toolkit running: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
