#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = TOOLKIT_ROOT.parent
PUBLIC_ROOT = WORKSPACE_ROOT if (WORKSPACE_ROOT / "index.html").exists() else WORKSPACE_ROOT / "public"
DATA_ROOT = PUBLIC_ROOT / "data"
INTRADAY_ROOT = WORKSPACE_ROOT / "tool" / "intraday_exports"
WEEKLY_ROOT = WORKSPACE_ROOT / "a_share_rotation_research" / "data" / "reports"
INTRADAY_SCRIPT_ROOT = TOOLKIT_ROOT / "vendor" / "intraday_decision" / "scripts"
DEFAULT_INVESTMENT_DIR = Path(os.environ.get("INVESTMENT_DIR") or WORKSPACE_ROOT / "tool" / "cloud_inputs")
LOCAL_INVESTMENT_DIR = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Obsidian Vault/investment"
if not DEFAULT_INVESTMENT_DIR.exists() and LOCAL_INVESTMENT_DIR.exists():
    DEFAULT_INVESTMENT_DIR = LOCAL_INVESTMENT_DIR
DEFAULT_PORTFOLIO_MD = DEFAULT_INVESTMENT_DIR / "portfolio.md"
DEFAULT_WATCHLIST_MD = DEFAULT_INVESTMENT_DIR / "watchlist.md"

CSV_PREVIEW_ROWS = 40
CANDIDATE_PREVIEW_ROWS = 500
REPORT_PREVIEW_CHARS = 32000
DEFAULT_START_DAY = "2026-06-15"
CHECKPOINT_ORDER = {
    "scan_0925": 925,
    "scan_0945": 945,
    "scan_1030": 1030,
    "scan_1120": 1120,
    "scan_1330": 1330,
    "scan_1430": 1440,
    "scan_1440": 1440,
    "scan_1510": 1510,
    "scan_strategy_1430": 1420,
}
TABLE_EXCLUDE = {"errors.csv", "tech_sector_daily_k.csv", "tech_sector_stock_map.csv"}
TABLE_LABELS = {
    "market_overview.csv": "市场概览",
    "market_sector_scan.csv": "板块扫描",
    "hot_board_front_core.csv": "强板块中军 / 前排",
    "pullback_setups.csv": "热门股回踩观察",
    "candidate_scores.csv": "10:30 候选评分",
    "watchlist_portfolio_actions.csv": "10:30 自选 / 持仓处理",
    "portfolio_extra.csv": "持仓额外信息",
    "morning_mainlines.csv": "上午主线",
    "candidate_morning_check.csv": "上午候选检查",
    "portfolio_morning_plan.csv": "午后预案",
    "market_close_confirm.csv": "尾盘市场确认",
    "sector_close_confirm.csv": "尾盘板块确认",
    "candidate_close_confirm.csv": "尾盘候选确认",
    "portfolio_close_confirm.csv": "尾盘持仓确认",
    "final_market.csv": "盘后市场",
    "final_sectors.csv": "盘后板块",
    "final_stocks.csv": "盘后个股",
    "portfolio_final_review.csv": "盘后持仓复盘",
    "strategy_summary.csv": "策略汇总",
    "strategy_candidates.csv": "策略候选",
    "strategy_candidates_float_excluded.csv": "流通股过滤",
    "strategy_candidates_float_unavailable.csv": "流通股不可用",
}
CHECKPOINT_IO = {
    "scan_1030": {
        "stage": "10:30 第一轮换手确认",
        "input": ["market_overview.csv", "market_sector_scan.csv", "hot_board_front_core.csv", "candidate_scores.csv", "watchlist_portfolio_actions.csv", "portfolio_extra.csv"],
        "output": ["candidate_scores.csv", "watchlist_portfolio_actions.csv", "market_sector_scan.csv"],
        "goal": "确认第一轮冲击后资金是否真正接受强线，同时把 watchlist / 持仓风险单独列出来。",
    },
    "scan_1120": {
        "stage": "11:20 上午收尾",
        "input": ["market_overview.csv", "market_sector_scan.csv", "morning_mainlines.csv", "candidate_morning_check.csv", "portfolio_morning_plan.csv"],
        "output": ["candidate_morning_check.csv", "morning_mainlines.csv", "portfolio_morning_plan.csv"],
        "goal": "避免午前冲动追涨，检查 10:30 候选是否继续在 VWAP 上方，并准备午后验证条件。",
    },
    "scan_strategy_1430": {
        "stage": "14:20 策略包",
        "input": ["strategy_summary.csv", "strategy_candidates.csv", "strategy_candidates_float_excluded.csv", "strategy_candidates_float_unavailable.csv"],
        "output": ["strategy_candidates.csv", "strategy_summary.csv"],
        "goal": "独立运行首板次日策略包，输出命中策略、个股和过滤原因，作为尾盘观察池。",
    },
    "scan_1430": {
        "stage": "14:30-14:45 尾盘确认",
        "input": ["market_close_confirm.csv", "market_sector_scan.csv", "sector_close_confirm.csv", "candidate_close_confirm.csv", "portfolio_close_confirm.csv"],
        "output": ["candidate_close_confirm.csv", "sector_close_confirm.csv", "portfolio_close_confirm.csv"],
        "goal": "把当天强线和个股表现转成明日 watchlist，同时识别长上影、回落和持仓未修复风险。",
    },
    "scan_1510": {
        "stage": "15:10 盘后复盘",
        "input": ["final_market.csv", "final_sectors.csv", "final_stocks.csv", "portfolio_final_review.csv", "market_sector_scan.csv"],
        "output": ["final_stocks.csv", "final_sectors.csv", "portfolio_final_review.csv"],
        "goal": "保存当天学习样本和明日计划：哪些继续看，哪些只是情绪温度计，哪些进入风险复盘。",
    },
}

PORTFOLIO_CODE_MAP = {
    "长盈通": "688143",
    "埃斯顿": "002747",
    "雷曼光电": "300162",
    "蓝思科技": "300433",
    "中科创达": "300496",
    "彩虹股份": "600707",
    "彩虹集团": "600707",
    "南大光电": "300346",
    "厦门钨业": "600549",
    "华亚智能": "003043",
    "欧莱新材": "688530",
    "烽火通信": "600498",
    "蓝箭电子": "301348",
    "甘李药业": "603087",
}


if str(INTRADAY_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(INTRADAY_SCRIPT_ROOT))

try:
    import decision_summary
    import scan_1030 as scan_core
except Exception:
    decision_summary = None
    scan_core = None


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc), "path": str(path)}


def read_csv_preview(path: Path, limit: int = CSV_PREVIEW_ROWS) -> dict:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    return {
        "name": path.name,
        "relative_path": rel(path),
        "columns": list(rows[0].keys()) if rows else [],
        "rows": rows[:limit],
        "row_count": len(rows),
        "modified": modified(path),
    }


def modified(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(path)


def latest_summary_dirs() -> list[Path]:
    if not INTRADAY_ROOT.exists():
        return []
    summaries = sorted(INTRADAY_ROOT.rglob("summary.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    return [item.parent for item in summaries]


def find_latest_dir(name_fragment: str = "", exclude_fragments: set[str] | None = None, start_date: str = "") -> Path | None:
    exclude_fragments = exclude_fragments or set()
    for directory in latest_summary_dirs():
        date_part = directory.parent.name
        if start_date and _looks_like_date(date_part) and date_part < start_date:
            continue
        if any(fragment in directory.name for fragment in exclude_fragments):
            continue
        if not name_fragment or name_fragment in directory.name:
            return directory
    return None


def csv_if_exists(directory: Path | None, names: list[str]) -> list[dict]:
    if directory is None:
        return []
    previews = []
    for name in names:
        path = directory / name
        if path.exists():
            previews.append(read_csv_preview(path))
    return previews


def csv_tables(directory: Path) -> list[dict]:
    tables = []
    for path in sorted(directory.glob("*.csv")):
        if path.name in TABLE_EXCLUDE:
            continue
        limit = CANDIDATE_PREVIEW_ROWS if _is_candidate_table(path.name) else CSV_PREVIEW_ROWS
        tables.append(read_csv_preview(path, limit=limit))
    return tables


def _is_candidate_table(name: str) -> bool:
    return name.startswith("candidate_") or name in {"candidate_scores.csv", "strategy_candidates.csv", "pullback_setups.csv"}


def list_recent_exports(limit: int = 80, start_date: str = DEFAULT_START_DAY) -> list[dict]:
    if not INTRADAY_ROOT.exists():
        return []
    files = []
    for path in INTRADAY_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".csv", ".json"}:
            continue
        try:
            date_part = path.relative_to(INTRADAY_ROOT).parts[0]
        except Exception:
            date_part = ""
        if start_date and _looks_like_date(date_part) and date_part < start_date:
            continue
        files.append(path)
    paths = sorted(
        files,
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return [
        {
            "name": path.name,
            "relative_path": rel(path),
            "modified": modified(path),
            "size": path.stat().st_size,
        }
        for path in paths[:limit]
    ]


def scan_dirs_by_day(limit_days: int = 20, start_date: str = DEFAULT_START_DAY) -> list[dict]:
    if not INTRADAY_ROOT.exists():
        return [{"date": start_date, "checkpoints": []}] if start_date else []
    date_dirs = [path for path in INTRADAY_ROOT.iterdir() if path.is_dir() and _looks_like_date(path.name)]
    if start_date:
        date_dirs = [path for path in date_dirs if path.name >= start_date]
    date_dirs.sort(key=lambda item: item.name, reverse=True)
    days = []
    for date_dir in date_dirs[:limit_days]:
        checkpoint_dirs = [
            path
            for path in date_dir.iterdir()
            if path.is_dir() and path.name.startswith("scan_") and (path / "summary.json").exists()
        ]
        checkpoint_dirs.sort(key=lambda item: CHECKPOINT_ORDER.get(item.name, 9999))
        if not checkpoint_dirs:
            continue
        days.append(
            {
                "date": date_dir.name,
                "checkpoints": [build_checkpoint_packet(path) for path in checkpoint_dirs],
            }
        )
    if start_date and not any(day["date"] == start_date for day in days):
        days.append({"date": start_date, "checkpoints": []})
    days.sort(key=lambda item: item["date"], reverse=True)
    return days


def _looks_like_date(value: str) -> bool:
    parts = value.split("-")
    return len(parts) == 3 and all(part.isdigit() for part in parts)


def build_checkpoint_packet(directory: Path) -> dict:
    summary = read_json(directory / "summary.json")
    tables = csv_tables(directory)
    table_map = {Path(table["name"]).stem: table["rows"] for table in tables}
    decision = read_json(directory / "checkpoint_decision_summary.json") if (directory / "checkpoint_decision_summary.json").exists() else {}
    if not decision:
        decision = synthesize_decision(directory, summary, table_map)
    ai_analysis = ai_analysis_for_checkpoint(directory)
    return {
        "id": directory.name,
        "label": checkpoint_label(directory.name, summary),
        "directory": rel(directory),
        "modified": modified(directory / "summary.json"),
        "summary": summary,
        "decision": decision,
        "demo_analysis": build_demo_analysis(directory, summary, tables),
        "ai_analysis": ai_analysis,
        "tables": tables,
    }


def ai_analysis_for_checkpoint(directory: Path) -> dict:
    raw_path = directory / "ai_analysis.json"
    raw = read_json(raw_path) if raw_path.exists() else {}
    override_path = DATA_ROOT / "ai_analysis_overrides" / f"{directory.parent.name}_{directory.name}.json"
    override = read_json(override_path) if override_path.exists() else {}
    return override or raw


def checkpoint_label(name: str, summary: dict) -> str:
    checkpoint = str(summary.get("checkpoint") or "")
    if "strategy" in name:
        return f"{checkpoint or '14:20'} 策略包"
    labels = {
        "scan_0925": "09:25 集合竞价",
        "scan_0945": "09:45 第一轮冲击",
        "scan_1030": "10:30 换手确认",
        "scan_1120": "11:20 上午收尾",
        "scan_1330": "13:30 午后重启",
        "scan_1430": "14:30 尾盘确认",
        "scan_1440": "14:40 尾盘确认",
        "scan_1510": "15:10 盘后复盘",
    }
    return labels.get(name, checkpoint or name)


def synthesize_decision(directory: Path, summary: dict, table_map: dict[str, list[dict]]) -> dict:
    if decision_summary is None:
        return {}
    if "strategy" in directory.name:
        rows = table_map.get("strategy_candidates", [])
        excluded = table_map.get("strategy_candidates_float_excluded", [])
        unavailable = table_map.get("strategy_candidates_float_unavailable", [])
        rows = decision_summary.enrich_strategy_candidates(rows)
        return decision_summary.build_strategy_decision_summary(
            checkpoint=str(summary.get("checkpoint") or "14:20"),
            summary=summary,
            rows=rows,
            excluded_rows=excluded,
            unavailable_rows=unavailable,
        )
    return decision_summary.build_checkpoint_decision_summary(
        checkpoint=str(summary.get("checkpoint") or directory.name),
        summary=summary,
        tables=table_map,
    )


def build_demo_analysis(directory: Path, summary: dict, tables: list[dict]) -> dict:
    config = CHECKPOINT_IO.get(directory.name, {})
    table_by_name = {table["name"]: table for table in tables}
    market = _first_row(table_by_name, "market_overview.csv") or _first_row(table_by_name, "market_close_confirm.csv") or _first_row(table_by_name, "final_market.csv")
    sectors = _rows(table_by_name, "market_sector_scan.csv") or _rows(table_by_name, "sector_close_confirm.csv") or _rows(table_by_name, "final_sectors.csv")
    candidates = (
        _rows(table_by_name, "candidate_scores.csv")
        or _rows(table_by_name, "candidate_morning_check.csv")
        or _rows(table_by_name, "candidate_close_confirm.csv")
        or _rows(table_by_name, "final_stocks.csv")
        or _rows(table_by_name, "strategy_candidates.csv")
    )
    top_sectors = [_sector_name(row) for row in sectors[:3] if _sector_name(row)]
    top_candidates = [_stock_name(row) for row in candidates[:4] if _stock_name(row)]
    candidate_count = len(candidates)
    vwap_up_count = sum(1 for row in candidates if row.get("VWAP上/下") == "上" or row.get("VWAP状态") == "上")
    fallback_used = bool(summary.get("fallback_used"))
    data_source = "Sina 行业 fallback" if fallback_used else "东方财富概念板块"

    headline, verdict, points, questions = _checkpoint_demo_text(
        directory.name,
        market=market,
        top_sectors=top_sectors,
        top_candidates=top_candidates,
        candidate_count=candidate_count,
        vwap_up_count=vwap_up_count,
        summary=summary,
        data_source=data_source,
    )

    available_inputs = _table_cards(config.get("input", []), table_by_name)
    available_outputs = _table_cards(config.get("output", []), table_by_name)
    data_notes = [
        f"板块源：{data_source}；fetch_attempts={summary.get('fetch_attempts', '-')}",
        f"候选/复盘个股：{candidate_count} 条",
    ]
    if fallback_used:
        data_notes.append("本时点东方财富概念拉取失败，skill 按规则使用 Sina 行业源，因此板块粒度会比 10:30 更粗。")
    if summary.get("error_count"):
        data_notes.append(f"原始采集错误 {summary.get('error_count')} 条，页面保留可用行用于复盘。")

    return {
        "stage": config.get("stage") or checkpoint_label(directory.name, summary),
        "goal": config.get("goal") or "按 checkpoint 合约读取数据、生成候选和风险处理表。",
        "headline": headline,
        "verdict": verdict,
        "input_files": available_inputs,
        "output_files": available_outputs,
        "analysis_points": points,
        "next_questions": questions,
        "data_notes": data_notes,
    }


def _rows(table_by_name: dict[str, dict], name: str) -> list[dict]:
    return table_by_name.get(name, {}).get("rows", [])


def _first_row(table_by_name: dict[str, dict], name: str) -> dict:
    rows = _rows(table_by_name, name)
    return rows[0] if rows else {}


def _table_cards(names: list[str], table_by_name: dict[str, dict]) -> list[dict]:
    cards = []
    for name in names:
        table = table_by_name.get(name)
        if not table:
            continue
        cards.append(
            {
                "name": name,
                "label": TABLE_LABELS.get(name, name),
                "rows": table.get("row_count", len(table.get("rows", []))),
                "columns": table.get("columns", [])[:8],
            }
        )
    return cards


def _sector_name(row: dict) -> str:
    name = row.get("板块") or row.get("sector") or ""
    pct = row.get("涨幅") or row.get("板块涨幅") or ""
    breadth = row.get("涨家率") or ""
    detail = []
    if pct:
        detail.append(f"{pct}%")
    if breadth:
        detail.append(f"涨家率{breadth}")
    return f"{name}（{'，'.join(detail)}）" if name and detail else name


def _stock_name(row: dict) -> str:
    stock = row.get("股票") or " ".join(part for part in [row.get("name"), row.get("code")] if part)
    pct = row.get("当前涨幅") or row.get("当前涨幅%") or row.get("收盘涨幅") or ""
    vwap = row.get("VWAP上/下") or row.get("VWAP状态") or ""
    tags = []
    if pct:
        tags.append(f"{pct}%")
    if vwap:
        tags.append(f"VWAP{vwap}")
    return f"{stock}（{'，'.join(tags)}）" if stock and tags else stock


def _market_sentence(market: dict) -> str:
    if not market:
        return "市场概览缺失，主要依据候选和板块表判断。"
    index = market.get("指数涨幅") or " / ".join(
        item
        for item in [
            f"上证 {market.get('上证')}%" if market.get("上证") else "",
            f"创业板 {market.get('创业板')}%" if market.get("创业板") else "",
            f"科创50 {market.get('科创50')}%" if market.get("科创50") else "",
        ]
        if item
    )
    breadth = market.get("涨跌家数") or "-"
    limit = market.get("涨停/跌停") or "-"
    return f"{index or '指数未知'}；涨跌家数 {breadth}；涨停/跌停 {limit}。"


def _checkpoint_demo_text(
    checkpoint_id: str,
    *,
    market: dict,
    top_sectors: list[str],
    top_candidates: list[str],
    candidate_count: int,
    vwap_up_count: int,
    summary: dict,
    data_source: str,
) -> tuple[str, str, list[str], list[str]]:
    sectors_text = "、".join(top_sectors) if top_sectors else "暂无清晰板块"
    stocks_text = "、".join(top_candidates) if top_candidates else "暂无高优先候选"
    market_text = _market_sentence(market)
    if checkpoint_id == "scan_1030":
        headline = "第一轮换手确认：CPO / 光通信链条成为上午主攻"
        verdict = f"{market_text} 当前强势板块是 {sectors_text}，候选表给出 {candidate_count} 条，其中 {vwap_up_count} 条在 VWAP 上方，说明这个时点不是单纯看涨幅，而是在确认强线承接。"
        points = [
            f"输入：用 {data_source} 板块、全 A 报价、分时 VWAP、watchlist 共同筛选。",
            f"输出：候选集中在 {stocks_text}，用于区分放量突破、watchlist 和风险处理。",
            "判断：强线可以继续观察，但买点必须等 VWAP 和高点回撤不恶化，不能只因涨幅靠前就追。",
        ]
        questions = ["11:20 时 CPO / 光通信是否仍保持强度？", "候选股是否继续在 VWAP 上方？", "冲高股有没有出现明显长上影或高点回撤？"]
    elif checkpoint_id == "scan_1120":
        headline = "上午收尾：确认候选承接，避免午前追涨"
        verdict = f"{market_text} 数据源切到 {data_source}，候选检查仍有 {candidate_count} 条，{vwap_up_count} 条在 VWAP 上方；这里的重点是午后计划，不是新增冲动买点。"
        points = [
            "输入：读取 10:30 候选和上午主线表，检查是否收回 VWAP、是否跌破上午低点。",
            f"输出：上午候选靠前包括 {stocks_text}。",
            "判断：午前仍强的个股进入午后验证池；未收回 VWAP 或跌破上午低点的个股降低优先级。",
        ]
        questions = ["13:30/14:30 是否继续站稳 VWAP？", "上午强线午后是延续还是回落？", "fallback 行业源下的粗粒度板块结论是否需要用个股强弱交叉验证？"]
    elif checkpoint_id == "scan_strategy_1430":
        strategies = summary.get("strategies", {})
        strategy_text = "、".join(f"{name} {count} 条" for name, count in strategies.items()) or "暂无策略命中"
        headline = "策略包：首板次日模型给出尾盘观察池"
        verdict = f"14:20 策略包独立扫描 {summary.get('evaluated_count', '-')} 只股票，命中 {candidate_count} 条事件、{summary.get('unique_stock_count', '-')} 只个股；策略分布为 {strategy_text}。"
        points = [
            "输入：全 A 报价、日 K、流通股过滤和策略定义。",
            f"输出：候选包括 {stocks_text}。",
            "判断：这是交易模型候选，不等同于主线确认；需要和尾盘板块、成交量、回撤一起看。",
        ]
        questions = ["候选是否接近高位但未涨停？", "成交量是否符合策略定义而不是单日异动？", "流通股过滤后是否仍有足够可执行标的？"]
    elif checkpoint_id == "scan_1430":
        headline = "尾盘确认：早盘科技强线回落，资源 / 电力行业靠前"
        verdict = f"{market_text} 尾盘强势板块变成 {sectors_text}；候选表仍有 {candidate_count} 条，但已经开始区分强阳接近高位、长上影和 VWAP 失守。"
        points = [
            "输入：尾盘市场确认、板块确认、候选确认和持仓确认表。",
            f"输出：尾盘观察重点包括 {stocks_text}。",
            "判断：尾盘不是新增判断越多越好，而是把明天能继续看的和今天冲高回落的分开。",
        ]
        questions = ["收盘接近高点的标的能否进入明日观察？", "长上影且 VWAP 下方的标的是否降级？", "尾盘强行业是否只是防守切换？"]
    elif checkpoint_id == "scan_1510":
        headline = "盘后复盘：保存明日计划和风险样本"
        verdict = f"{market_text} 收盘强势板块为 {sectors_text}，盘后个股表保留 {candidate_count} 条复盘样本，用于明日 watchlist 和学习。"
        points = [
            "输入：盘后市场、最终板块、最终个股和持仓复盘表。",
            f"输出：复盘样本包括 {stocks_text}。",
            "判断：盘后不追求即时操作，而是记录今天的强线、回落样本和明天需要验证的价格/板块条件。",
        ]
        questions = ["明天开盘强线是否延续，还是继续切到防守行业？", "今天长上影样本是否需要降低观察权重？", "watchlist 中哪些个股必须先过 VWAP 或关键位？"]
    else:
        headline = f"{summary.get('checkpoint', checkpoint_id)} checkpoint 复盘"
        verdict = f"{market_text} 强势板块是 {sectors_text}，候选/输出共 {candidate_count} 条。"
        points = [f"输入源：{data_source}。", f"主要候选：{stocks_text}。"]
        questions = ["下一 checkpoint 继续验证板块成交、VWAP 和高点回撤。"]
    return headline, verdict, points, questions


def _latest_dated_markdown_block(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "", ""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    date_rows: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("#"):
            continue
        match = __import__("re").search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", line)
        if not match:
            continue
        date = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        date_rows.append((date, index))
    if not date_rows:
        return "", text
    latest_date, start = max(date_rows, key=lambda item: item[0])
    following = [index for date, index in date_rows if index > start]
    end = min(following) if following else len(lines)
    return latest_date, "\n".join(lines[start:end]).strip()


def _parse_markdown_stock_items(path: Path) -> dict:
    source = str(path)
    date, block = _latest_dated_markdown_block(path)
    items: list[dict] = []
    current_group = ""
    current_priority = ""
    table_header: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            table_header = []
            continue
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            current_group = title
            priority_match = __import__("re").search(r"\b(P[0-3])\b", title, flags=__import__("re").IGNORECASE)
            if priority_match:
                current_priority = priority_match.group(1).upper()
            table_header = []
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(set(cell) <= {"-", ":", " "} for cell in cells):
                continue
            if any("股票" in cell for cell in cells):
                table_header = cells
                continue
            if table_header:
                row = {table_header[index]: cells[index] if index < len(cells) else "" for index in range(len(table_header))}
                stock_cell = row.get("股票") or row.get("股票 / 板块") or row.get("股票/板块") or cells[0]
                role = row.get("角色") or ""
                sector = row.get("板块/主逻辑") or row.get("板块") or row.get("主逻辑") or ""
                note = row.get("行动考虑栏") or row.get("保留原因") or row.get("为什么留") or ""
                priority = "P0" if "主观察" in current_group else current_priority or "P2"
                for raw_stock in __import__("re").split(r"[、，,]", stock_cell):
                    content = raw_stock.strip()
                    if not content:
                        continue
                    content = __import__("re").sub(r"`([^`]+)`", r" \1", content)
                    code_match = __import__("re").search(r"\b(\d{6})\b", content)
                    name_content = __import__("re").sub(r"\b\d{6}\b", "", content).strip()
                    stock_match = __import__("re").match(r"([\u4e00-\u9fa5A-Za-z* ]{2,16})", name_content)
                    if not stock_match:
                        continue
                    code = code_match.group(1) if code_match else ""
                    name = (stock_match.group(1) or name_content).strip()
                    items.append(
                        {
                            "name": name,
                            "code": code,
                            "priority": priority,
                            "sector": sector,
                            "role": role,
                            "note": note,
                            "group": current_group,
                            "raw": " | ".join(cells),
                        }
                    )
            continue
        if not line.startswith(("-", "*", "•")):
            continue
        content = line.lstrip("-*•").strip()
        parts = [part.strip() for part in content.replace("｜", "|").split("|")]
        first = parts[0] if parts else content
        first = __import__("re").sub(r"`([^`]+)`", r" \1", first)
        code_match = __import__("re").search(r"\b(\d{6})\b", first)
        name_first = __import__("re").sub(r"\b\d{6}\b", "", first).strip()
        stock_match = __import__("re").match(r"([\u4e00-\u9fa5A-Za-z* ]{2,16})", name_first)
        if not stock_match:
            continue
        code = code_match.group(1) if code_match else ""
        name = (stock_match.group(1) or name_first).strip()
        priority_match = __import__("re").search(r"\b(P[0-3])\b", content, flags=__import__("re").IGNORECASE)
        priority = priority_match.group(1).upper() if priority_match else current_priority or "P2"
        sector = parts[1] if len(parts) > 1 else ""
        role = parts[2] if len(parts) > 2 else ""
        note = " | ".join(parts[3:]) if len(parts) > 3 else ""
        items.append(
            {
                "name": name,
                "code": code,
                "priority": priority,
                "sector": sector,
                "role": role,
                "note": note,
                "group": current_group,
                "raw": content,
            }
        )
    return {
        "source": source,
        "modified": modified(path) if path.exists() else "",
        "latest_date": date,
        "current_items": items,
    }


def load_watchlist() -> dict:
    parsed = _parse_markdown_stock_items(DEFAULT_WATCHLIST_MD)
    if not parsed.get("current_items"):
        cached = _cached_current("current_watchlist.json", "watchlist")
        if cached:
            return cached
    return parsed


def load_portfolio() -> dict:
    rows = []
    source = str(DEFAULT_PORTFOLIO_MD)
    if scan_core is not None and DEFAULT_PORTFOLIO_MD.exists():
        try:
            date, block = _latest_dated_markdown_block(DEFAULT_PORTFOLIO_MD)
            temp_path = DEFAULT_PORTFOLIO_MD
            if date and block:
                temp_path = Path("/private/tmp/a_share_dashboard_portfolio_latest_block.md")
                temp_path.write_text(block, encoding="utf-8")
            holdings = scan_core.parse_portfolio_markdown(temp_path)
            rows = sorted(holdings.values(), key=lambda item: str(item.get("code", "")))
        except Exception as exc:
            return {"source": source, "error": str(exc), "base_holdings": []}
    latest_date, _ = _latest_dated_markdown_block(DEFAULT_PORTFOLIO_MD)
    row_latest_date = max((str(row.get("date") or "") for row in rows if row.get("date")), default="")
    if row_latest_date:
        latest_date = row_latest_date
    result = {
        "source": source,
        "modified": modified(DEFAULT_PORTFOLIO_MD) if DEFAULT_PORTFOLIO_MD.exists() else "",
        "latest_date": latest_date,
        "base_holdings": rows,
    }
    if not rows:
        cached = _cached_current("current_portfolio.json", "portfolio")
        if cached:
            return cached
    return result


def load_portfolio_history(start_date: str = DEFAULT_START_DAY) -> dict:
    if not DEFAULT_PORTFOLIO_MD.exists():
        return {}
    text = DEFAULT_PORTFOLIO_MD.read_text(encoding="utf-8", errors="replace")
    current_year = "2026"
    history: dict[str, dict] = {}
    in_holdings = False
    header: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        year_match = __import__("re").search(r"(20\d{2})", line)
        if line.startswith("#") and year_match:
            current_year = year_match.group(1)
        if line.startswith("## Holdings"):
            in_holdings = True
            continue
        if in_holdings and line.startswith("## ") and not line.startswith("## Holdings"):
            in_holdings = False
        if not in_holdings or not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if any(cell.lower() == "date" for cell in cells):
            header = cells
            continue
        if not cells or not header:
            continue
        row = {header[index]: cells[index] if index < len(cells) else "" for index in range(len(header))}
        date_text = row.get("Date") or cells[0]
        date_match = __import__("re").search(r"(\d{1,2})[./-](\d{1,2})", date_text)
        if not date_match:
            continue
        date_key = f"{current_year}-{int(date_match.group(1)):02d}-{int(date_match.group(2)):02d}"
        name = (row.get("Ticker") or "").strip()
        code_match = __import__("re").search(r"\b(\d{6})\b", name)
        code = code_match.group(1) if code_match else PORTFOLIO_CODE_MAP.get(name, "")
        name = __import__("re").sub(r"`?\d{6}`?", "", name).strip()
        if not name:
            continue
        if start_date and date_key < start_date:
            continue
        history.setdefault(date_key, {"latest_date": date_key, "base_holdings": []})
        history[date_key]["base_holdings"].append(
            {
                "code": code,
                "name": name,
                "shares_total": row.get("Shares", ""),
                "avg_cost": row.get("Avg Cost", ""),
                "current_snapshot": row.get("Current", ""),
                "return": row.get("Return", ""),
                "total": row.get("Total", ""),
                "source": "portfolio.md",
            }
        )
    return history


def _cached_current(filename: str, key: str) -> dict:
    current_path = DATA_ROOT / filename
    if current_path.exists():
        try:
            return json.loads(current_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    site_path = DATA_ROOT / "site.json"
    if site_path.exists():
        try:
            return json.loads(site_path.read_text(encoding="utf-8")).get(key, {})
        except Exception:
            return {}
    return {}


def latest_weekly_report() -> dict | None:
    if not WEEKLY_ROOT.exists():
        return None
    reports = sorted(WEEKLY_ROOT.glob("*_weekly_report.md"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not reports:
        return None
    source = reports[0]
    target = DATA_ROOT / source.name
    shutil.copy2(source, target)
    return {
        "name": source.name,
        "relative_path": rel(source),
        "published_path": f"data/{source.name}",
        "modified": modified(source),
        "text": source.read_text(encoding="utf-8", errors="replace")[:REPORT_PREVIEW_CHARS],
    }


def load_preopen_plan() -> dict:
    path = DATA_ROOT / "preopen_plan.json"
    if not path.exists():
        return {}
    payload = read_json(path)
    return payload if isinstance(payload, dict) else {}


def build_payload() -> dict:
    preopen_plan = load_preopen_plan()
    start_date = str(preopen_plan.get("date") or DEFAULT_START_DAY)
    latest_intraday_dir = find_latest_dir("scan_", exclude_fragments={"strategy"}, start_date=start_date)
    latest_strategy_dir = find_latest_dir("strategy", start_date=start_date)
    intraday_summary = read_json(latest_intraday_dir / "summary.json") if latest_intraday_dir else {}
    strategy_summary = read_json(latest_strategy_dir / "summary.json") if latest_strategy_dir else {}
    watchlist = load_watchlist()
    portfolio = load_portfolio()
    portfolio_history = load_portfolio_history(start_date=start_date)
    (DATA_ROOT / "current_watchlist.json").write_text(json.dumps(watchlist, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA_ROOT / "current_portfolio.json").write_text(json.dumps(portfolio, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "demo_day": start_date,
        "source": {
            "intraday_root": rel(INTRADAY_ROOT),
            "weekly_root": rel(WEEKLY_ROOT),
        },
        "latest_intraday": {
            "directory": rel(latest_intraday_dir) if latest_intraday_dir else "",
            "summary": intraday_summary,
            "tables": csv_if_exists(
                latest_intraday_dir,
                [
                    "market_overview.csv",
                    "market_sector_scan.csv",
                    "hot_board_front_core.csv",
                    "candidate_first_impact.csv",
                    "candidate_afternoon_restart.csv",
                    "final_stocks.csv",
                    "final_sectors.csv",
                    "portfolio_first_impact.csv",
                    "portfolio_afternoon_status.csv",
                    "portfolio_final_review.csv",
                ],
            ),
        },
        "latest_strategy": {
            "directory": rel(latest_strategy_dir) if latest_strategy_dir else "",
            "summary": strategy_summary,
            "tables": csv_if_exists(latest_strategy_dir, ["strategy_summary.csv", "strategy_candidates.csv"]),
        },
        "latest_weekly": latest_weekly_report(),
        "preopen_plan": preopen_plan,
        "timeline_days": scan_dirs_by_day(start_date=start_date),
        "watchlist": watchlist,
        "portfolio": portfolio,
        "portfolio_history": portfolio_history,
        "recent_exports": list_recent_exports(start_date=start_date),
    }


def main() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    payload = build_payload()
    (DATA_ROOT / "site.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Published static data: {DATA_ROOT / 'site.json'}")


if __name__ == "__main__":
    main()
