#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path


TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = TOOLKIT_ROOT.parent
DATA_ROOT = WORKSPACE_ROOT / "data"
INPUT_ROOT = WORKSPACE_ROOT / "tool" / "cloud_inputs"


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def cached_payload(name: str, site_key: str) -> dict:
    payload = read_json(DATA_ROOT / name)
    if payload:
        return payload
    site = read_json(DATA_ROOT / "site.json")
    return site.get(site_key, {}) if isinstance(site, dict) else {}


def code_text(row: dict) -> str:
    code = str(row.get("code") or "").strip()
    return f" `{code}`" if re.fullmatch(r"\d{6}", code) else ""


def write_watchlist(payload: dict) -> None:
    rows = payload.get("current_items") or []
    date = payload.get("latest_date") or "cached"
    lines = [
        f"## 云端缓存 watchlist：{date}",
        "",
        "| 股票 | 角色 | 板块/主逻辑 | 为什么留 | 确认条件 | 降级 / 风险条件 | 行动考虑栏 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        name = str(row.get("name") or row.get("stock") or "").strip()
        if not name:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{name}{code_text(row)}",
                    str(row.get("role") or row.get("priority") or "watchlist"),
                    str(row.get("sector") or ""),
                    str(row.get("note") or row.get("raw") or "缓存 watchlist"),
                    "按当前 checkpoint 的 VWAP、板块排名、成交确认",
                    "跌回 VWAP 下或弱于所属板块",
                    str(row.get("group") or "云端缓存"),
                ]
            )
            + " |"
        )
    (INPUT_ROOT / "watchlist.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_portfolio(payload: dict) -> None:
    rows = payload.get("base_holdings") or payload.get("current_items") or []
    date = payload.get("latest_date") or "cached"
    lines = [
        f"## 云端缓存 portfolio：{date}",
        "",
        "## Holdings",
        "",
        "| Ticker | Shares | Avg Cost | Current | Note |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        name = str(row.get("name") or row.get("stock") or row.get("code") or "").strip()
        if not name:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    f"{name}{code_text(row)}",
                    str(row.get("shares_total") or row.get("shares") or ""),
                    str(row.get("avg_cost") or row.get("cost") or ""),
                    str(row.get("current_snapshot") or row.get("current") or ""),
                    str(row.get("note") or row.get("thesis") or "云端缓存"),
                ]
            )
            + " |"
        )
    (INPUT_ROOT / "portfolio.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    INPUT_ROOT.mkdir(parents=True, exist_ok=True)
    write_watchlist(cached_payload("current_watchlist.json", "watchlist"))
    write_portfolio(cached_payload("current_portfolio.json", "portfolio"))
    print(f"Prepared cloud inputs under {INPUT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
