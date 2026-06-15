#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import decision_summary


SINA_QUOTES = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
SINA_KLINE = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
SINA_MINLINE = "https://quotes.sina.cn/cn/api/openapi.php/CN_MinlineService.getMinlineData"
SINA_SECTORS = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
INDEX_SYMBOLS = {
    "sh000001": "上证",
    "sz399001": "深证成指",
    "sz399006": "创业板",
    "sh000688": "科创50",
    "sh000016": "上证50",
    "sh932000": "中证2000",
    "sz399005": "中小100",
}
SINA_HQ = "https://hq.sinajs.cn/list=" + ",".join(INDEX_SYMBOLS)
SINA_HQ_LIST = "https://hq.sinajs.cn/list="
TENCENT_DAILY = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
EASTMONEY_BOARD_RANK = "https://17.push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_CONCEPT_RANK = "https://79.push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_BOARD_RANK_ENDPOINTS = [
    "https://17.push2.eastmoney.com/api/qt/clist/get",
    "https://79.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
]
EASTMONEY_CONCEPT_RANK_ENDPOINTS = [
    "https://79.push2.eastmoney.com/api/qt/clist/get",
    "https://17.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
]
AKSHARE_PYTHON = Path("/Users/char/Desktop/04 investment/a_share_rotation_research/.venv/bin/python")
AKSHARE_WORKDIR = Path("/Users/char/Desktop/04 investment/a_share_rotation_research")
TENCENT_QUOTES = "https://qt.gtimg.cn/q="

CHECKPOINT = "10:30"
TODAY = date.today().isoformat()
MARKET_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_INVESTMENT_DIR = Path("/Users/char/Library/Mobile Documents/com~apple~CloudDocs/Obsidian Vault/investment")
INVESTMENT_ROOT = Path(__file__).resolve().parents[4]
LOCAL_STOCK_CACHE_DIR = Path("/Users/char/Desktop/04 investment/a_share_rotation_research/data/cache")
SOURCE_FAILURE_LIMIT = 25
SOURCE_FAILURE_LOCK = threading.Lock()
SOURCE_FAILURES = {"daily": 0, "intraday": 0}
MANUAL_STOCK_CODE_MAP = {
    "博创科技": ("300548", "博创科技"),
    "得润电子": ("002055", "得润电子"),
    "道森股份": ("603800", "道森股份"),
    "龙辰科技": ("920161", "龙辰科技"),
    "东旭光电": ("000413", "东旭光电"),
    "闻泰科技": ("600745", "闻泰科技"),
}
UNAVAILABLE_TEXT_VALUES = {
    "",
    "-",
    "none",
    "null",
    "nan",
    "unavailable",
    "unavailable: no evaluated members for this board",
}
INTRADAY_FIELD_AVAILABILITY_FIELDS = [
    "time",
    "code",
    "symbol",
    "name",
    "sector",
    "sector_rank",
    "sector_pct",
    "price",
    "pct",
    "amount_1030",
    "volume_ratio_vs_5d_same_time",
    "vwap",
    "vwap_distance_pct",
    "open",
    "high",
    "low",
    "prev_close",
    "prev_low",
    "ma5",
    "ma10",
    "prev5_high",
    "prev5_high_is_stage_high",
    "recent5_gain_pct",
    "distance_to_ma5_pct",
    "drawdown_from_high_pct",
    "drawdown_from_high_abs_pct",
    "position_in_range",
    "is_above_vwap",
    "is_above_open",
    "is_new_5d_high",
    "reclaimed_ma5",
    "reclaimed_vwap",
    "relative_strength_vs_sector",
    "role_type",
    "sector_continuity_type",
    "is_pullback_setup",
    "is_breakout_setup",
    "setup_name",
    "setup_pass_reasons",
    "setup_fail_reasons",
    "risk_flags",
    "hard_cap_reason",
    "score",
    "score_breakdown",
    "auction_open_pct",
    "auction_amount",
    "yesterday_hot_sector",
    "exact_core_front_row_classification",
]


@dataclass(frozen=True)
class Sector:
    code: str
    name: str
    rank: int
    pct: float
    amount: float
    stock_count: int
    leader_symbol: str
    leader_pct: float
    leader_name: str
    source: str = "sina_industry_fallback"
    kind: str = "行业"
    fallback_used: bool = False
    fetch_attempts: int = 1
    fallback_reason: str = ""
    advancers_ratio: float | str = ""
    limit_up_count: int | str = ""


def is_available_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in UNAVAILABLE_TEXT_VALUES
    return True


def summarize_field_availability(rows: list[dict[str, Any]], expected_fields: list[str] | None = None) -> dict[str, Any]:
    field_order: list[str] = []
    for field in expected_fields or []:
        if field not in field_order:
            field_order.append(field)
    for row in rows:
        for field in row:
            if field not in field_order:
                field_order.append(field)

    usable_fields: list[str] = []
    unusable_fields: list[str] = []
    for field in field_order:
        if any(is_available_value(row.get(field)) for row in rows):
            usable_fields.append(field)
        else:
            unusable_fields.append(field)

    return {
        "usable_fields": usable_fields,
        "unusable_fields": unusable_fields,
        "usable_field_count": len(usable_fields),
        "unusable_field_count": len(unusable_fields),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="10:30 A-share intraday decision scanner")
    parser.add_argument("--pool", choices=["all-a", "watchlist"], default="all-a")
    parser.add_argument("--watchlist", type=Path, help="Optional CSV with code/name/symbol columns")
    parser.add_argument("--portfolio", type=Path, help="Optional portfolio CSV")
    parser.add_argument("--investment-dir", type=Path, default=DEFAULT_INVESTMENT_DIR)
    parser.add_argument("--out", type=Path, default=Path(f"scan_1030_{TODAY}"))
    parser.add_argument("--checkpoint", default=CHECKPOINT, help="HH:MM checkpoint used for intraday metrics")
    parser.add_argument("--asof-time", default="", help="Optional HH:MM cutoff for intraday minute metrics; defaults to checkpoint.")
    parser.add_argument("--top-sector-rank", type=int, default=10)
    parser.add_argument("--pullback-sector-rank", type=int, default=15)
    parser.add_argument("--min-amount", type=float, default=500_000_000)
    parser.add_argument("--min-free-market-cap", type=float, default=0)
    parser.add_argument("--max-workers", type=int, default=18)
    parser.add_argument("--limit", type=int, default=0, help="Optional symbol limit for testing")
    return parser.parse_args()


def normalize_intraday_time(value: str, fallback: str = CHECKPOINT) -> str:
    raw = str(value or "").strip().replace("：", ":")
    if not raw:
        raw = fallback
    if raw.isdigit() and len(raw) == 4:
        raw = f"{raw[:2]}:{raw[2:]}"
    if raw.isdigit() and len(raw) in {3, 4}:
        raw = f"{int(raw[:-2]):02d}:{raw[-2:]}"
    if len(raw) != 5 or raw[2] != ":":
        raise SystemExit(f"invalid intraday time: {value}")
    hour, minute = raw.split(":", 1)
    if not (hour.isdigit() and minute.isdigit()):
        raise SystemExit(f"invalid intraday time: {value}")
    hour_int = int(hour)
    minute_int = int(minute)
    if hour_int < 0 or hour_int > 23 or minute_int < 0 or minute_int > 59:
        raise SystemExit(f"invalid intraday time: {value}")
    return f"{hour_int:02d}:{minute_int:02d}"


def metric_checkpoint(args: argparse.Namespace) -> str:
    return normalize_intraday_time(getattr(args, "asof_time", "") or args.checkpoint, args.checkpoint)


def summary_snapshot_fields(args: argparse.Namespace, results: list[dict[str, Any]]) -> dict[str, Any]:
    target_time = metric_checkpoint(args)
    checkpoint_times = sorted(str(row.get("checkpoint_time") or "") for row in results if row.get("checkpoint_time"))
    actual_time = checkpoint_times[-1] if checkpoint_times else ""
    now = datetime.now(MARKET_TZ)
    run_at = now.isoformat(timespec="seconds")
    run_hm = now.strftime("%H:%M")
    snapshot_mode = "live_preview" if target_time > run_hm else "historical_intraday"
    return {
        "run_at": run_at,
        "target_checkpoint": args.checkpoint,
        "asof_time": target_time,
        "actual_data_time": f"{TODAY} {actual_time}" if actual_time else "",
        "snapshot_mode": snapshot_mode,
        "snapshot_warning": "指数、市场宽度、个股分时指标按 asof_time 之前最新分钟或截面聚合计算；板块排名为成员股 asof 聚合口径，非 EastMoney 历史排行榜原始快照。",
    }


def fetch_bytes(url: str, params: dict[str, Any] | None = None, retries: int = 4, timeout: int = 20) -> bytes:
    full_url = url if not params else f"{url}?{urllib.parse.urlencode(params)}"
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return subprocess.run(
                [
                    "curl",
                    "-fsSL",
                    "--compressed",
                    "--connect-timeout",
                    str(min(timeout, 10)),
                    "-A",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
                    "-H",
                    "Accept: */*",
                    "-H",
                    "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
                    "-H",
                    "Connection: keep-alive",
                    "-H",
                    "Referer: https://finance.sina.com.cn/",
                    full_url,
                ],
                check=True,
                capture_output=True,
                timeout=timeout,
            ).stdout
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.5 * attempt)
    raise RuntimeError(f"request failed: {last_error}")


def fetch_json(url: str, params: dict[str, Any] | None = None, retries: int = 4, timeout: int = 20) -> Any:
    return json.loads(fetch_bytes(url, params=params, retries=retries, timeout=timeout).decode("utf-8"))


def run_akshare_json(code: str, timeout: int = 90) -> Any:
    if not AKSHARE_PYTHON.exists():
        raise RuntimeError(f"akshare python not found: {AKSHARE_PYTHON}")
    proc = subprocess.run(
        [str(AKSHARE_PYTHON), "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(AKSHARE_WORKDIR) if AKSHARE_WORKDIR.exists() else None,
    )
    for line in reversed(proc.stdout.splitlines()):
        text = line.strip()
        if text.startswith(("[", "{")):
            return json.loads(text)
    return json.loads(proc.stdout)


def num(value: Any, default: float | None = None) -> float | None:
    try:
        if value in ("", None):
            return default
        parsed = float(value)
        if math.isnan(parsed):
            return default
        return parsed
    except (TypeError, ValueError):
        return default


def symbol_for_code(code: str) -> str:
    code = str(code).strip().zfill(6)
    if code.startswith(("6", "5", "9")):
        return f"sh{code}"
    if code.startswith(("8", "4")):
        return f"bj{code}"
    return f"sz{code}"


def code_for_symbol(symbol: str) -> str:
    return str(symbol)[-6:]


def normalize_stock_name(value: str) -> str:
    return (
        str(value or "")
        .replace(" ", "")
        .replace("\u3000", "")
        .replace("Ａ", "A")
        .replace("Ｂ", "B")
        .upper()
    )


def current_workspace(text: str) -> str:
    return text.split("## 历史工作区", 1)[0]


def split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def extract_codes(text: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for name, code in re.findall(r"([\u4e00-\u9fffA-Za-z0-9Ａ＊* ]+?)\s*`(\d{6})`", text):
        clean_name = name.strip().strip("|").strip()
        result[code] = {"code": code, "name": clean_name}
    return result


def _code_from_cache_value(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def load_local_stock_name_map() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}

    def add_row(code_value: Any, name_value: Any) -> None:
        code = _code_from_cache_value(code_value)
        name = str(name_value or "").strip()
        if not code or not name:
            return
        result.setdefault(normalize_stock_name(name), {"code": code, "name": name})

    spot_path = LOCAL_STOCK_CACHE_DIR / "stock_zh_a_spot.csv"
    if spot_path.exists():
        try:
            with spot_path.open(encoding="utf-8-sig", newline="") as file:
                for row in csv.DictReader(file):
                    add_row(row.get("代码"), row.get("名称"))
        except Exception:
            pass

    if LOCAL_STOCK_CACHE_DIR.exists():
        for path in sorted(LOCAL_STOCK_CACHE_DIR.glob("stock_board*_cons*.csv")):
            try:
                with path.open(encoding="utf-8-sig", newline="") as file:
                    for row in csv.DictReader(file):
                        add_row(row.get("代码"), row.get("名称"))
            except Exception:
                continue
    return result


def resolve_stock_name(name: str, name_map: dict[str, dict[str, str]] | None = None) -> dict[str, str] | None:
    manual = MANUAL_STOCK_CODE_MAP.get(name)
    if manual:
        return {"code": manual[0], "name": manual[1]}
    name_map = name_map if name_map is not None else load_local_stock_name_map()
    return name_map.get(normalize_stock_name(name))


def _split_stock_names(value: str) -> list[str]:
    names = re.split(r"[、,，/]+", str(value or ""))
    return [name.strip() for name in names if name.strip()]


def parse_tech_sector_branches(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    text = current_workspace(path.read_text(encoding="utf-8"))
    lines = text.splitlines()
    in_section = False
    header: list[str] = []
    rows: list[dict[str, str]] = []
    name_map = load_local_stock_name_map()
    for line in lines:
        if line.startswith("### "):
            in_section = "Tech Sector 分支字典" in line
            continue
        if not in_section:
            continue
        if not line.startswith("|"):
            if header and rows:
                break
            continue
        if "---" in line:
            continue
        cells = split_markdown_row(line)
        if cells and cells[0] == "分支":
            header = cells
            continue
        if len(cells) < 5:
            continue
        branch = cells[0]
        category = cells[1]
        for role, cell in (("前排弹性", cells[2]), ("中军容量", cells[3]), ("补涨观察", cells[4])):
            for input_name in _split_stock_names(cell):
                resolved = resolve_stock_name(input_name, name_map)
                rows.append(
                    {
                        "branch": branch,
                        "category": category,
                        "role": role,
                        "input_name": input_name,
                        "code": resolved["code"] if resolved else "",
                        "name": resolved["name"] if resolved else "",
                        "symbol": symbol_for_code(resolved["code"]) if resolved else "",
                        "status": "resolved" if resolved else "unresolved",
                    }
                )
    return rows


def tech_sector_symbols(rows: list[dict[str, str]]) -> set[str]:
    return {row["symbol"] for row in rows if row.get("symbol")}


def build_tech_sector_daily_rows(rows: list[dict[str, str]], daily_by_symbol: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in rows:
        symbol = item.get("symbol", "")
        if not symbol:
            continue
        for daily in daily_by_symbol.get(symbol, []):
            output.append(
                {
                    "板块": item["branch"],
                    "分类": item["category"],
                    "角色": item["role"],
                    "输入股票": item["input_name"],
                    "代码": item["code"],
                    "名称": item["name"],
                    "日期": daily.get("date", ""),
                    "开盘": daily.get("open", ""),
                    "最高": daily.get("high", ""),
                    "最低": daily.get("low", ""),
                    "收盘": daily.get("close", ""),
                    "成交量": daily.get("volume", ""),
                    "数据来源": daily.get("data_source", "Sina daily KLine"),
                }
            )
    return output


def build_tech_sector_stock_map(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "板块": row["branch"],
            "分类": row["category"],
            "角色": row["role"],
            "输入股票": row["input_name"],
            "代码": row["code"],
            "名称": row["name"],
            "状态": row["status"],
        }
        for row in rows
    ]


def parse_watchlist_markdown(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    text = current_workspace(path.read_text(encoding="utf-8"))
    result = extract_codes(text)
    for line in text.splitlines():
        if not line.startswith("|") or "`" not in line or "---" in line:
            continue
        cells = split_markdown_row(line)
        if len(cells) < 2:
            continue
        match = re.search(r"`(\d{6})`", cells[0])
        if not match:
            continue
        code = match.group(1)
        name = re.sub(r"`\d{6}`", "", cells[0]).strip()
        result.setdefault(code, {"code": code, "name": name})
    return result


def parse_plan_rows_from_watchlist(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    text = current_workspace(path.read_text(encoding="utf-8"))
    rows: dict[str, dict[str, str]] = {}
    header: list[str] = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = split_markdown_row(line)
        if cells and "股票" in cells[0]:
            header = cells
            continue
        if "---" in line or "`" not in line:
            continue
        match = re.search(r"`(\d{6})`", cells[0] if cells else "")
        if not match:
            continue
        code = match.group(1)
        name = re.sub(r"`\d{6}`", "", cells[0]).strip()
        cell_by_header = {header[index]: cells[index] for index in range(min(len(header), len(cells)))} if header else {}
        thesis = cell_by_header.get("主逻辑") or cell_by_header.get("板块/主逻辑") or ""
        buy_condition = cell_by_header.get("买入观察条件") or cell_by_header.get("升级条件") or ""
        sell_condition = cell_by_header.get("卖出 / 降级观察条件") or cell_by_header.get("降级条件") or ""
        if ("见持仓处理观察" in buy_condition or "见持仓处理观察" in sell_condition) and code in rows:
            continue
        numbers = re.findall(r"\d+(?:\.\d+)?", f"{buy_condition} {sell_condition}")
        rows[code] = {
            "code": code,
            "name": name,
            "thesis": thesis,
            "planned_buy_condition": buy_condition,
            "planned_sell_or_downgrade_condition": sell_condition,
            "key_support_1": numbers[0] if len(numbers) >= 1 else "",
            "key_support_2": numbers[1] if len(numbers) >= 2 else "",
        }
    return rows


def parse_portfolio_markdown(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    known_codes = {
        "长盈通": "688143",
        "埃斯顿": "002747",
        "雷曼光电": "300162",
        "中科创达": "300496",
        "南大光电": "300346",
        "彩虹股份": "600707",
        "彩虹集团": "600707",
        "厦门钨业": "600549",
        "华亚智能": "003043",
        "欧莱新材": "688530",
        "烽火通信": "600498",
        "蓝箭电子": "301348",
        "甘李药业": "603087",
        "天赐材料": "002709",
        "云南锗业": "002428",
        "中天科技": "600522",
        "节能风电": "601016",
        "蓝思科技": "300433",
        "浙江新能": "600032",
    }
    holdings: dict[str, dict[str, Any]] = {}
    parsed_rows: list[dict[str, Any]] = []
    in_holdings = False
    header: list[str] = []
    current_year = ""
    for line in text.splitlines():
        year_match = re.search(r"(20\d{2})", line)
        if line.lstrip().startswith("#") and year_match:
            current_year = year_match.group(1)
        if line.startswith("## Holdings"):
            in_holdings = True
            continue
        if in_holdings and line.startswith("## "):
            break
        if not in_holdings or not line.startswith("|") or "---" in line:
            continue
        cells = split_markdown_row(line)
        if any(cell.lower() == "ticker" for cell in cells):
            header = cells
            continue
        if not cells:
            continue
        cell_by_header = {header[index]: cells[index] for index in range(min(len(header), len(cells)))} if header else {}
        name = (cell_by_header.get("Ticker") or cells[0]).strip()
        code_match = re.search(r"`?(\d{6})`?", name)
        code = code_match.group(1) if code_match else known_codes.get(name)
        name = re.sub(r"`?\d{6}`?", "", name).strip()
        if not code:
            continue
        shares_total = cell_by_header["Shares"] if "Shares" in cell_by_header else (cells[1] if len(cells) > 1 else "")
        avg_cost = cell_by_header["Avg Cost"] if "Avg Cost" in cell_by_header else (cells[2] if len(cells) > 2 else "")
        current_snapshot = cell_by_header["Current"] if "Current" in cell_by_header else (cells[3] if len(cells) > 3 else "")
        parsed_rows.append({
            "date": normalize_portfolio_date(cell_by_header.get("Date", ""), current_year),
            "code": code,
            "name": name,
            "shares_total": shares_total,
            "avg_cost": avg_cost,
            "current_snapshot": current_snapshot,
        })
    latest_row_date = max((row["date"] for row in parsed_rows if row.get("date")), default="")
    for row in parsed_rows:
        if latest_row_date and row.get("date") != latest_row_date:
            continue
        holdings[row["code"]] = {
            "code": row["code"],
            "date": row.get("date", ""),
            "name": row["name"],
            "shares_total": row["shares_total"],
            "avg_cost": row["avg_cost"],
            "current_snapshot": row["current_snapshot"],
        }
    recent_adds: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("|") or "买入" not in line or "5.6" not in line:
            continue
        cells = split_markdown_row(line)
        if len(cells) >= 6:
            name = cells[2]
            code = known_codes.get(name)
            if code:
                recent_adds[code] = cells[4]
                if code in holdings:
                    holdings[code]["last_add_price"] = cells[5]
                    holdings[code]["shares_added_recently"] = cells[4]
    for code, row in holdings.items():
        row.setdefault("shares_added_recently", recent_adds.get(code, ""))
        row.setdefault("last_add_price", "")
    return holdings


def normalize_portfolio_date(value: str, year: str = "") -> str:
    text = str(value or "").strip()
    match = re.search(r"(\d{1,2})[./-](\d{1,2})", text)
    if not match:
        return ""
    month_day = f"{int(match.group(1)):02d}-{int(match.group(2)):02d}"
    return f"{year}-{month_day}" if year else month_day


def read_symbol_pool(path: Path) -> set[str]:
    symbols: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            symbol = str(row.get("symbol") or "").strip()
            code = str(row.get("code") or "").strip()
            if symbol:
                symbols.add(symbol)
            elif code:
                symbols.add(symbol_for_code(code))
    return symbols


def quote_row_from_akshare(row: dict[str, Any]) -> dict[str, Any]:
    code = str(row.get("代码") or row.get("code") or "").strip()
    symbol = str(row.get("symbol") or "").strip() or symbol_for_code(code)
    latest = num(row.get("最新价"), 0) or 0
    prev_close = num(row.get("昨收"), 0) or 0
    pct = num(row.get("涨跌幅"))
    if pct is None and latest and prev_close:
        pct = (latest / prev_close - 1) * 100
    return {
        "symbol": symbol,
        "code": code_for_symbol(symbol),
        "name": str(row.get("名称") or row.get("name") or ""),
        "trade": latest,
        "pricechange": num(row.get("涨跌额"), 0) or 0,
        "changepercent": pct or 0,
        "buy": num(row.get("买入"), 0) or 0,
        "sell": num(row.get("卖出"), 0) or 0,
        "settlement": prev_close,
        "open": num(row.get("今开"), 0) or 0,
        "high": num(row.get("最高"), 0) or 0,
        "low": num(row.get("最低"), 0) or 0,
        "volume": num(row.get("成交量"), 0) or 0,
        "amount": num(row.get("成交额"), 0) or 0,
        "source": "akshare_sina_spot",
    }


def fetch_quotes_akshare_sina(pool_symbols: set[str] | None = None, limit: int = 0) -> list[dict[str, Any]]:
    records = run_akshare_json(
        "import akshare as ak, json; "
        "df=ak.stock_zh_a_spot(); "
        "print(json.dumps(df.to_dict('records'), ensure_ascii=False))",
        timeout=120,
    )
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        row = quote_row_from_akshare(record)
        symbol = str(row.get("symbol") or "")
        if not symbol or symbol in seen:
            continue
        if pool_symbols is not None and symbol not in pool_symbols:
            continue
        if num(row.get("trade"), 0):
            seen.add(symbol)
            rows.append(row)
        if limit and len(rows) >= limit:
            break
    return rows


def parse_tencent_quote_line(line: str) -> dict[str, Any] | None:
    match = re.search(r'v_([a-z]{2}\d{6})="(.*)"', line)
    if not match:
        return None
    symbol = match.group(1)
    parts = match.group(2).split("~")
    if len(parts) < 38:
        return None
    trade = num(parts[3], 0) or 0
    prev_close = num(parts[4], 0) or 0
    pct = num(parts[32])
    if pct is None and trade and prev_close:
        pct = (trade / prev_close - 1) * 100
    return {
        "symbol": symbol,
        "code": code_for_symbol(symbol),
        "name": parts[1],
        "trade": trade,
        "pricechange": num(parts[31], 0) or 0,
        "changepercent": pct or 0,
        "settlement": prev_close,
        "open": num(parts[5], 0) or 0,
        "high": num(parts[33], 0) or 0,
        "low": num(parts[34], 0) or 0,
        "volume": num(parts[36], 0) or 0,
        "amount": (num(parts[37], 0) or 0) * 10000,
        "source": "tencent_quote",
    }


def parse_sina_hq_quote_line(line: str) -> dict[str, Any] | None:
    match = re.search(r'var hq_str_([a-z]{2}\d{6})="(.*)"', line)
    if not match:
        return None
    symbol = match.group(1)
    parts = match.group(2).split(",")
    if len(parts) < 32 or not parts[0]:
        return None
    open_price = num(parts[1], 0) or 0
    prev_close = num(parts[2], 0) or 0
    trade = num(parts[3], 0) or 0
    pct = (trade / prev_close - 1) * 100 if trade and prev_close else 0
    return {
        "symbol": symbol,
        "code": code_for_symbol(symbol),
        "name": parts[0],
        "trade": trade,
        "pricechange": trade - prev_close if trade and prev_close else 0,
        "changepercent": pct,
        "buy": num(parts[6], 0) or 0,
        "sell": num(parts[7], 0) or 0,
        "settlement": prev_close,
        "open": open_price,
        "high": num(parts[4], 0) or 0,
        "low": num(parts[5], 0) or 0,
        "volume": num(parts[8], 0) or 0,
        "amount": num(parts[9], 0) or 0,
        "source": "sina_hq_batch",
    }


def fetch_sina_hq_quotes(symbols: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    symbols_sorted = sorted(symbols)
    for start in range(0, len(symbols_sorted), 120):
        raw = fetch_bytes(SINA_HQ_LIST + ",".join(symbols_sorted[start : start + 120]), retries=2, timeout=10).decode("gbk", "replace")
        for line in raw.splitlines():
            row = parse_sina_hq_quote_line(line)
            if row and num(row.get("trade"), 0):
                rows.append(row)
        time.sleep(0.03)
    return rows


def fetch_tencent_quotes(symbols: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    symbols_sorted = sorted(symbols)
    for start in range(0, len(symbols_sorted), 120):
        raw = fetch_bytes(TENCENT_QUOTES + ",".join(symbols_sorted[start : start + 120]), retries=3, timeout=20).decode("gbk", "replace")
        for line in raw.splitlines():
            row = parse_tencent_quote_line(line)
            if row and num(row.get("trade"), 0):
                rows.append(row)
        time.sleep(0.05)
    return rows


def fetch_quotes(pool_symbols: set[str] | None = None, limit: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    consecutive_failures = 0
    for page in range(1, 100):
        try:
            page_rows = fetch_json(
                SINA_QUOTES,
                {
                    "page": page,
                    "num": 80,
                    "sort": "changepercent",
                    "asc": 0,
                    "node": "hs_a",
                    "symbol": "",
                    "_s_r_a": "page",
                },
                retries=8,
                timeout=30,
            )
            consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            print(f"warning: fetch quotes page {page} failed after retries: {exc}")
            if consecutive_failures >= 3:
                print("warning: stop fetching quotes after 3 consecutive failed pages")
                break
            time.sleep(1.0 * consecutive_failures)
            continue
        if not page_rows:
            break
        for row in page_rows:
            symbol = str(row.get("symbol") or "")
            if not symbol or symbol in seen:
                continue
            if pool_symbols is not None and symbol not in pool_symbols:
                continue
            trade = num(row.get("trade"))
            amount = num(row.get("amount"), 0)
            if trade and amount is not None:
                seen.add(symbol)
                rows.append(row)
            if limit and len(rows) >= limit:
                return rows
        time.sleep(0.05)
    if rows:
        return rows
    try:
        print("warning: Sina quote center unavailable; trying AkShare Sina spot")
        rows = fetch_quotes_akshare_sina(pool_symbols=pool_symbols, limit=limit)
    except Exception as exc:
        print(f"warning: AkShare Sina spot unavailable: {exc}")
    if rows:
        return rows
    if pool_symbols:
        try:
            print("warning: trying Tencent quote fallback for required pool")
            return fetch_tencent_quotes(pool_symbols)
        except Exception as exc:
            print(f"warning: Tencent quote fallback unavailable: {exc}")
    return []


def fetch_eastmoney_board_rank(kind: str, url: str, fs: str, fetch_attempts: int) -> list[Sector]:
    payload = fetch_json(
        url,
        {
            "pn": "1",
            "pz": "180",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": fs,
            "fields": "f2,f3,f4,f7,f8,f12,f14,f20,f62,f104,f105,f128,f136",
        },
        retries=1,
    )
    rows: list[Sector] = []
    source = "eastmoney_industry" if kind == "行业" else "eastmoney_concept"
    for index, row in enumerate((payload.get("data") or {}).get("diff") or [], start=1):
        rows.append(
            Sector(
                code=str(row.get("f12") or ""),
                name=str(row.get("f14") or ""),
                rank=index,
                stock_count=int(num(row.get("f104"), 0) or 0) + int(num(row.get("f105"), 0) or 0),
                pct=float(num(row.get("f3"), 0) or 0),
                amount=float(num(row.get("f20"), 0) or 0),
                leader_symbol="",
                leader_pct=float(num(row.get("f136"), 0) or 0),
                leader_name=str(row.get("f128") or ""),
                source=source,
                kind=kind,
                fallback_used=False,
                fetch_attempts=fetch_attempts,
            )
        )
    return [row for row in rows if row.code and row.name]


def fetch_eastmoney_sectors() -> list[Sector]:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        rows = []
        errors = []
        for endpoint in EASTMONEY_CONCEPT_RANK_ENDPOINTS:
            try:
                rows.extend(fetch_eastmoney_board_rank("概念", endpoint, "m:90 t:3 f:!50", attempt))
                if rows:
                    break
            except Exception as exc:
                errors.append(f"concept {endpoint}: {exc}")
        if rows:
            rows = sorted(rows, key=lambda item: item.pct, reverse=True)
            sectors = [
                Sector(
                    code=item.code,
                    name=item.name,
                    rank=index,
                    stock_count=item.stock_count,
                    pct=item.pct,
                    amount=item.amount,
                    leader_symbol=item.leader_symbol,
                    leader_pct=item.leader_pct,
                    leader_name=item.leader_name,
                    source=item.source,
                    kind=item.kind,
                    fallback_used=False,
                    fetch_attempts=attempt,
                )
                for index, item in enumerate(rows, start=1)
            ]
            return sectors
        last_error = RuntimeError("; ".join(errors) if errors else "empty EastMoney board rank")
        time.sleep(0.5 * attempt)
    raise RuntimeError(f"eastmoney concept sector fetch failed after 3 attempts: {last_error}")


def fetch_sina_sectors(fallback_reason: str = "") -> list[Sector]:
    raw = fetch_bytes(SINA_SECTORS).decode("gbk", "replace")
    json_text = raw.split("=", 1)[1].strip()
    if json_text.endswith(";"):
        json_text = json_text[:-1]
    data = json.loads(json_text)
    sectors: list[Sector] = []
    for raw_value in data.values():
        parts = str(raw_value).split(",")
        if len(parts) < 13:
            continue
        sectors.append(
            Sector(
                code=parts[0],
                name=parts[1],
                rank=0,
                stock_count=int(num(parts[2], 0) or 0),
                pct=float(parts[5]),
                amount=float(parts[7]),
                leader_symbol=parts[8],
                leader_pct=float(parts[9]),
                leader_name=parts[12],
                source="sina_industry_fallback",
                kind="行业",
                fallback_used=True,
                fetch_attempts=3,
                fallback_reason=fallback_reason,
            )
        )
    sectors.sort(key=lambda item: item.pct, reverse=True)
    return [
        Sector(
            code=item.code,
            name=item.name,
            rank=index,
            stock_count=item.stock_count,
            pct=item.pct,
            amount=item.amount,
            leader_symbol=item.leader_symbol,
            leader_pct=item.leader_pct,
            leader_name=item.leader_name,
            source=item.source,
            kind=item.kind,
            fallback_used=item.fallback_used,
            fetch_attempts=item.fetch_attempts,
            fallback_reason=item.fallback_reason,
        )
        for index, item in enumerate(sectors, start=1)
    ]


def fetch_ths_industry_sectors(fallback_reason: str = "") -> list[Sector]:
    records = run_akshare_json(
        "import akshare as ak, json; "
        "df=ak.stock_board_industry_summary_ths(); "
        "print(json.dumps(df.to_dict('records'), ensure_ascii=False))",
        timeout=90,
    )
    sectors: list[Sector] = []
    for index, row in enumerate(records, start=1):
        up = int(num(row.get("上涨家数"), 0) or 0)
        down = int(num(row.get("下跌家数"), 0) or 0)
        total = up + down
        sectors.append(
            Sector(
                code=str(row.get("板块") or f"ths_industry_{index}"),
                name=str(row.get("板块") or ""),
                rank=index,
                stock_count=total,
                pct=float(num(row.get("涨跌幅"), 0) or 0),
                amount=(float(num(row.get("总成交额"), 0) or 0) * 100_000_000),
                leader_symbol="",
                leader_pct=float(num(row.get("领涨股-涨跌幅"), 0) or 0),
                leader_name=str(row.get("领涨股") or ""),
                source="ths_industry_realtime_fallback",
                kind="行业",
                fallback_used=True,
                fetch_attempts=3,
                fallback_reason=fallback_reason,
                advancers_ratio=(up / total if total else ""),
                limit_up_count="",
            )
        )
    return [sector for sector in sectors if sector.name]


def fetch_sectors() -> list[Sector]:
    try:
        return fetch_eastmoney_sectors()
    except Exception as exc:
        fallback_reason = str(exc)
        try:
            return fetch_sina_sectors(fallback_reason)
        except Exception as fallback_exc:
            ths_reason = f"EastMoney failed: {fallback_reason}; Sina fallback failed: {fallback_exc}"
            try:
                return fetch_ths_industry_sectors(ths_reason)
            except Exception as ths_exc:
                print(f"warning: sector fetch unavailable; {ths_reason}; THS realtime fallback failed: {ths_exc}")
                return []


def fetch_sector_members(sectors: list[Sector]) -> tuple[dict[str, Sector], dict[str, dict[str, Any]]]:
    result: dict[str, Sector] = {}
    stats: dict[str, dict[str, Any]] = {}
    amount_ranked = {sector.code: rank for rank, sector in enumerate(sorted(sectors, key=lambda item: item.amount, reverse=True), start=1)}
    for index, sector in enumerate(sectors, start=1):
        sector_rows: list[dict[str, Any]] = []
        member_error = ""
        pages = max(1, math.ceil((sector.stock_count or 300) / 300))
        for page in range(1, pages + 1):
            try:
                if sector.source.startswith("eastmoney"):
                    payload = fetch_json(
                        EASTMONEY_BOARD_RANK,
                        {
                            "pn": page,
                            "pz": "300",
                            "po": "1",
                            "np": "1",
                            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                            "fltt": "2",
                            "invt": "2",
                            "fid": "f3",
                            "fs": f"b:{sector.code}",
                            "fields": "f12,f14,f2,f3,f5,f6,f8,f20",
                        },
                    )
                    rows = [
                        {
                            "symbol": symbol_for_code(str(row.get("f12") or "")),
                            "changepercent": row.get("f3"),
                        }
                        for row in (payload.get("data") or {}).get("diff") or []
                        if row.get("f12")
                    ]
                elif sector.source.startswith("sina"):
                    rows = fetch_json(
                        SINA_QUOTES,
                        {
                            "page": page,
                            "num": 300,
                            "sort": "changepercent",
                            "asc": 0,
                            "node": sector.code,
                            "symbol": "",
                            "_s_r_a": "page",
                        },
                    )
                else:
                    member_error = "sector members unavailable for realtime fallback source"
                    rows = []
            except Exception as exc:
                member_error = str(exc)
                break
            for row in rows:
                symbol = str(row.get("symbol") or "")
                if symbol:
                    sector_rows.append(row)
                if symbol and symbol not in result:
                    result[symbol] = sector
            time.sleep(0.02)
        up_count = sum(1 for row in sector_rows if (num(row.get("changepercent"), 0) or 0) > 0)
        limit_up_count = sum(1 for row in sector_rows if is_limit_up(str(row.get("symbol") or ""), num(row.get("changepercent"), 0) or 0))
        stats[sector.code] = {
            "advancers_ratio": up_count / len(sector_rows) if sector_rows else sector.advancers_ratio,
            "limit_up_count": limit_up_count if sector_rows else sector.limit_up_count,
            "member_count": len(sector_rows),
            "amount_rank": amount_ranked.get(sector.code, 999),
            "member_error": member_error,
        }
        if index % 10 == 0:
            print(f"sector members {index}/{len(sectors)}")
    return result, stats


def is_limit_up(symbol: str, pct: float) -> bool:
    if symbol.startswith("bj"):
        return pct >= 29.5
    if symbol.startswith(("sz300", "sh688")):
        return pct >= 19.5
    return pct >= 9.5


def is_limit_down(symbol: str, pct: float) -> bool:
    if symbol.startswith("bj"):
        return pct <= -29.5
    if symbol.startswith(("sz300", "sh688")):
        return pct <= -19.5
    return pct <= -9.5


def fetch_daily(symbol: str, datalen: int = 30) -> list[dict[str, Any]]:
    with SOURCE_FAILURE_LOCK:
        if SOURCE_FAILURES["daily"] >= SOURCE_FAILURE_LIMIT:
            raise RuntimeError("Sina daily KLine source temporarily unavailable; circuit open")
    sina_error: Exception | None = None
    try:
        rows = fetch_json(
            SINA_KLINE,
            {"symbol": symbol, "scale": 240, "ma": "no", "datalen": datalen},
            retries=1,
            timeout=6,
        )
    except Exception as exc:
        sina_error = exc
        try:
            return fetch_daily_tencent(symbol, datalen=datalen)
        except Exception as tencent_exc:
            with SOURCE_FAILURE_LOCK:
                SOURCE_FAILURES["daily"] += 1
            raise RuntimeError(f"Sina daily KLine failed: {sina_error}; Tencent daily fallback failed: {tencent_exc}") from tencent_exc
    if not isinstance(rows, list):
        try:
            return fetch_daily_tencent(symbol, datalen=datalen)
        except Exception as tencent_exc:
            with SOURCE_FAILURE_LOCK:
                SOURCE_FAILURES["daily"] += 1
            raise RuntimeError(f"Sina daily KLine returned non-list; Tencent daily fallback failed: {tencent_exc}") from tencent_exc
    return [
        {
            "date": str(row["day"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
        for row in rows
    ]


def fetch_daily_tencent(symbol: str, datalen: int = 30) -> list[dict[str, Any]]:
    payload = fetch_json(TENCENT_DAILY, {"param": f"{symbol},day,,,{datalen}"}, retries=2, timeout=10)
    stock_data = (payload.get("data") or {}).get(symbol) or {}
    raw_rows = stock_data.get("day") or stock_data.get("qfqday") or []
    if not isinstance(raw_rows, list):
        return []
    return [
        {
            "date": str(row[0]),
            "open": float(row[1]),
            "close": float(row[2]),
            "high": float(row[3]),
            "low": float(row[4]),
            "volume": float(row[5]) if len(row) > 5 else 0.0,
        }
        for row in raw_rows
        if len(row) >= 5
    ]


def fetch_intraday(symbol: str) -> list[dict[str, Any]]:
    with SOURCE_FAILURE_LOCK:
        if SOURCE_FAILURES["intraday"] >= SOURCE_FAILURE_LIMIT:
            raise RuntimeError("Sina intraday minline source temporarily unavailable; circuit open")
    try:
        payload = fetch_json(SINA_MINLINE, {"symbol": symbol}, retries=1, timeout=6)
    except Exception:
        with SOURCE_FAILURE_LOCK:
            SOURCE_FAILURES["intraday"] += 1
        raise
    if not isinstance(payload, dict):
        return []
    return payload.get("result", {}).get("data") or []


def latest_at_or_before(rows: list[dict[str, Any]], checkpoint: str) -> dict[str, Any] | None:
    checkpoint_time = f"{checkpoint}:00" if len(checkpoint) == 5 else checkpoint
    chosen: dict[str, Any] | None = None
    for row in rows:
        if str(row.get("m") or "") <= checkpoint_time:
            chosen = row
        else:
            break
    return chosen


def sustained_vwap_break(rows: list[dict[str, Any]], start_time: str, checkpoint: str) -> bool:
    checkpoint_time = f"{checkpoint}:00" if len(checkpoint) == 5 else checkpoint
    below_count = 0
    for row in rows:
        row_time = str(row.get("m") or "")
        if row_time < start_time or row_time > checkpoint_time:
            continue
        price = num(row.get("p"))
        vwap = num(row.get("avg_p"))
        if price is not None and vwap is not None and price < vwap:
            below_count += 1
            if below_count >= 5:
                return True
        else:
            below_count = 0
    return False


def intraday_range_until(rows: list[dict[str, Any]], checkpoint: str) -> tuple[float | None, float | None]:
    checkpoint_time = f"{checkpoint}:00" if len(checkpoint) == 5 else checkpoint
    prices = [
        num(row.get("p"))
        for row in rows
        if str(row.get("m") or "") <= checkpoint_time and num(row.get("p")) is not None
    ]
    if not prices:
        return None, None
    return max(prices), min(prices)


def metrics_from_daily(daily: list[dict[str, Any]], base: dict[str, Any]) -> dict[str, Any] | None:
    if len(daily) < 8:
        return None
    today_bar = daily[-1] if daily[-1]["date"] == TODAY else None
    previous = daily[:-1] if today_bar else daily
    if len(previous) < 10:
        return None
    prev5 = previous[-5:]
    prev10 = previous[-10:]
    prev20 = previous[-20:] if len(previous) >= 20 else previous
    prev60 = previous[-60:] if len(previous) >= 60 else previous
    stage_window = previous[-19:] + [{"high": base["high"]}]
    ma5 = (sum(float(bar["close"]) for bar in previous[-4:]) + base["price"]) / 5
    ma10 = (sum(float(bar["close"]) for bar in previous[-9:]) + base["price"]) / 10
    ma20 = (sum(float(bar["close"]) for bar in previous[-19:]) + base["price"]) / 20 if len(previous) >= 19 else None
    prev_ma10 = sum(float(bar["close"]) for bar in previous[-10:]) / 10
    prev_ma20 = sum(float(bar["close"]) for bar in previous[-20:]) / 20 if len(previous) >= 20 else None
    prev5_high = max(float(bar["high"]) for bar in prev5)
    prev20_high = max(float(bar["high"]) for bar in prev20)
    stage_high = max(float(bar["high"]) for bar in stage_window)
    return {
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma10_slope_pct": (ma10 / prev_ma10 - 1) * 100 if prev_ma10 else "",
        "ma20_slope_pct": (ma20 / prev_ma20 - 1) * 100 if ma20 and prev_ma20 else "",
        "prev5_high": prev5_high,
        "prev20_high": prev20_high,
        "prev5_high_is_stage_high": abs(prev5_high - stage_high) < 1e-6,
        "recent5_gain_pct": (base["price"] / float(prev5[0]["close"]) - 1) * 100,
        "recent10_gain_pct": (base["price"] / float(prev10[0]["close"]) - 1) * 100,
        "recent20_gain_pct": (base["price"] / float(prev20[0]["close"]) - 1) * 100 if prev20 else "",
        "recent60_gain_pct": (base["price"] / float(prev60[0]["close"]) - 1) * 100 if prev60 else "",
        "drawdown_from_20d_high_pct": (base["price"] / prev20_high - 1) * 100 if prev20_high else "",
        "prev_close": float(previous[-1]["close"]),
        "prev_low": float(previous[-1]["low"]),
        "prev5_avg_volume_daily": sum(float(bar["volume"]) for bar in prev5) / 5,
        "prev10_avg_volume_daily": sum(float(bar["volume"]) for bar in prev10) / 10,
    }


def same_time_volume_ratio(daily: dict[str, Any], intraday_rows: list[dict[str, Any]], checkpoint_row: dict[str, Any]) -> float:
    checkpoint_total_volume = num(checkpoint_row.get("tot_v"))
    daily_avg = daily.get("prev5_avg_volume_daily")
    if not checkpoint_total_volume or not daily_avg:
        return 0
    # Approximate 10:30 same-time comparison when historical intraday files are unavailable.
    # 10:30 is about one hour into a four-hour A-share session, so use 25% of daily volume.
    return checkpoint_total_volume / (daily_avg * 0.25)


def build_base_quote(row: dict[str, Any], checkpoint_row: dict[str, Any]) -> dict[str, Any] | None:
    price = num(checkpoint_row.get("p")) or num(row.get("trade"))
    vwap = num(checkpoint_row.get("avg_p"))
    open_price = num(row.get("open"))
    high = num(row.get("high"))
    low = num(row.get("low"))
    prev_close = num(row.get("settlement"))
    pct = num(row.get("changepercent"))
    checkpoint_volume = num(checkpoint_row.get("tot_v"))
    amount = checkpoint_volume * vwap if checkpoint_volume and vwap else num(row.get("amount"), 0)
    volume = checkpoint_volume or num(row.get("volume"), 0)
    if None in (price, vwap, open_price, high, low, prev_close, pct, amount):
        return None
    return {
        "symbol": row.get("symbol"),
        "code": str(row.get("code") or code_for_symbol(str(row.get("symbol")))).zfill(6),
        "name": row.get("name"),
        "price": price,
        "pct": pct,
        "vwap": vwap,
        "open": open_price,
        "high": high,
        "low": low,
        "prev_close": prev_close,
        "amount": amount,
        "volume": volume,
        "ticktime": row.get("ticktime"),
        "checkpoint_time": checkpoint_row.get("m"),
        "is_st": "ST" in str(row.get("name") or "").upper(),
        "free_market_cap": num(row.get("nmc"), 0),
    }


def calc_position(price: float, high: float, low: float) -> float:
    if high == low:
        return 1.0 if price >= high else 0.0
    return (price - low) / (high - low)


def pct_or_empty(value: float | None, digits: int = 3) -> float | str:
    return "" if value is None else round(value, digits)


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def infer_role_type(base: dict[str, Any], daily: dict[str, Any], sector: Sector | None, setup: str, is_watch_or_portfolio: bool) -> str:
    amount = base["amount"]
    if is_watch_or_portfolio:
        return "watchlist/portfolio"
    if amount >= 5_000_000_000:
        return "中军"
    if amount >= 1_000_000_000 and sector and sector.rank <= 10:
        return "前排" if base["pct"] >= 5 else "趋势核心"
    if daily["recent5_gain_pct"] >= 8 and daily["distance_to_ma5_pct"] <= 12:
        return "趋势核心"
    if amount < 1_000_000_000 and base["pct"] >= 7:
        return "高弹性"
    if sector and sector.rank <= 15:
        return "后排"
    return "未知"


def infer_sector_continuity_type(sector: Sector | None, role_type: str, yesterday_hot: bool = False) -> str:
    if not sector:
        return "弱板块独强"
    if yesterday_hot and sector.rank <= 10 and sector.pct > 0:
        return "昨日强线延续"
    if yesterday_hot and sector.pct > 0:
        return "昨日强线分歧"
    if sector.rank <= 10 and role_type in ("中军", "前排", "watchlist/portfolio", "趋势核心"):
        return "今日新切换"
    if sector.rank <= 15:
        return "非昨日强线/非明确新切换"
    if sector.pct <= 0:
        return "弱板块独强"
    return "非昨日强线/非明确新切换"


def aggregate_sector_snapshot(sectors: list[Sector], results: list[dict[str, Any]]) -> tuple[list[Sector], dict[str, dict[str, Any]]]:
    meta_by_key: dict[str, Sector] = {}
    for sector in sectors:
        meta_by_key[sector.code or sector.name] = sector
        meta_by_key[sector.name] = sector
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        key = str(row.get("sector_code") or row.get("sector") or "")
        if not key:
            continue
        grouped.setdefault(key, []).append(row)

    aggregated: list[Sector] = []
    for key, rows in grouped.items():
        meta = meta_by_key.get(key) or meta_by_key.get(str(rows[0].get("sector") or "")) or Sector(
            code=key,
            name=str(rows[0].get("sector") or key),
            rank=999,
            stock_count=len(rows),
            pct=0,
            amount=0,
            leader_symbol="",
            leader_pct=0,
            leader_name="",
            source="member_aggregate",
            kind="概念",
        )
        amount = sum(num(row.get("amount_1030"), 0) or 0 for row in rows)
        weighted_total = sum((num(row.get("pct"), 0) or 0) * (num(row.get("amount_1030"), 0) or 0) for row in rows)
        pct = weighted_total / amount if amount else sum(num(row.get("pct"), 0) or 0 for row in rows) / len(rows)
        leader = max(rows, key=lambda row: (num(row.get("pct"), -999) or -999, num(row.get("amount_1030"), 0) or 0))
        up_count = sum(1 for row in rows if (num(row.get("pct"), 0) or 0) > 0)
        limit_up_count = sum(1 for row in rows if is_limit_up(str(row.get("symbol") or ""), num(row.get("pct"), 0) or 0))
        aggregated.append(
            Sector(
                code=meta.code or key,
                name=meta.name,
                rank=999,
                stock_count=len(rows),
                pct=float(pct),
                amount=float(amount),
                leader_symbol=str(leader.get("symbol") or ""),
                leader_pct=float(num(leader.get("pct"), 0) or 0),
                leader_name=str(leader.get("name") or ""),
                source=f"{meta.source}_member_aggregate",
                kind=meta.kind,
                fallback_used=meta.fallback_used,
                fetch_attempts=meta.fetch_attempts,
                fallback_reason=meta.fallback_reason,
                advancers_ratio=up_count / len(rows) if rows else "",
                limit_up_count=limit_up_count,
            )
        )
    aggregated.sort(key=lambda item: (item.pct, item.amount), reverse=True)
    ranked = [
        Sector(
            code=item.code,
            name=item.name,
            rank=index,
            stock_count=item.stock_count,
            pct=item.pct,
            amount=item.amount,
            leader_symbol=item.leader_symbol,
            leader_pct=item.leader_pct,
            leader_name=item.leader_name,
            source=item.source,
            kind=item.kind,
            fallback_used=item.fallback_used,
            fetch_attempts=item.fetch_attempts,
            fallback_reason=item.fallback_reason,
            advancers_ratio=item.advancers_ratio,
            limit_up_count=item.limit_up_count,
        )
        for index, item in enumerate(aggregated, start=1)
    ]
    amount_ranked = {sector.code: rank for rank, sector in enumerate(sorted(ranked, key=lambda item: item.amount, reverse=True), start=1)}
    stats = {
        sector.code: {
            "advancers_ratio": sector.advancers_ratio,
            "limit_up_count": sector.limit_up_count,
            "member_count": sector.stock_count,
            "amount_rank": amount_ranked.get(sector.code, 999),
            "member_error": "",
            "snapshot_basis": "asof_member_aggregate",
        }
        for sector in ranked
    }
    return ranked, stats


def apply_sector_snapshot_to_results(results: list[dict[str, Any]], sectors: list[Sector]) -> None:
    by_code = {sector.code: sector for sector in sectors}
    by_name = {sector.name: sector for sector in sectors}
    for row in results:
        sector = by_code.get(str(row.get("sector_code") or "")) or by_name.get(str(row.get("sector") or ""))
        if not sector:
            continue
        row["sector"] = sector.name
        row["sector_rank"] = sector.rank
        row["sector_pct"] = round(sector.pct, 3)
        relative = (num(row.get("pct"), 0) or 0) - sector.pct
        row["relative_strength_vs_sector"] = round(relative, 3)
        flags = [item for item in str(row.get("risk_flags") or "").split(";") if item and item != "弱于板块"]
        if relative < 0:
            flags.append("弱于板块")
        row["risk_flags"] = ";".join(flags)


def score_candidate(
    base: dict[str, Any],
    daily: dict[str, Any],
    sector: Sector | None,
    sector_stat: dict[str, Any],
    setup: str,
    role_type: str,
    sector_continuity_type: str,
    is_watch_or_portfolio: bool,
) -> tuple[int, dict[str, int], str]:
    sector_rank = sector.rank if sector else 999
    advancers_ratio = sector_stat.get("advancers_ratio", "") if sector_stat else ""
    limit_up_count = sector_stat.get("limit_up_count", 0) if sector_stat else 0
    amount_rank = sector_stat.get("amount_rank", 999) if sector_stat else 999

    if sector_rank <= 3:
        sector_quality = 25
    elif sector_rank <= 7:
        sector_quality = 21
    elif sector_rank <= 10:
        sector_quality = 17
    elif sector_rank <= 15:
        sector_quality = 13
    else:
        sector_quality = 8
    if amount_rank <= 5:
        sector_quality += 2
    if advancers_ratio != "" and advancers_ratio >= 0.7:
        sector_quality += 2
    if limit_up_count >= 5:
        sector_quality += 2
    if sector and sector.pct > 0 and advancers_ratio != "" and advancers_ratio < 0.5:
        sector_quality -= 4
    sector_quality = clamp(sector_quality, 0, 25)

    role_map = {
        "watchlist/portfolio": 19,
        "中军": 18,
        "前排": 16,
        "趋势核心": 15,
        "高弹性": 12,
        "后排": 8,
        "未知": 5,
    }
    role = role_map.get(role_type, 5)
    if not is_watch_or_portfolio and role_type not in ("中军", "前排", "趋势核心"):
        role -= 3
    role = clamp(role, 0, 20)

    vwap_distance = base["vwap_distance_pct"]
    if vwap_distance >= 2:
        acceptance = 19
    elif vwap_distance >= 0.5:
        acceptance = 15
    elif vwap_distance >= 0:
        acceptance = 11
    else:
        acceptance = 6
    position_pct = base["position_in_range"] * 100
    if position_pct >= 85:
        acceptance += 2
    elif position_pct < 50:
        acceptance -= 5
    if base["drawdown_from_high_abs_pct"] > 5:
        acceptance -= 8
    elif base["drawdown_from_high_abs_pct"] > 3:
        acceptance -= 5
    if not base["is_above_open"]:
        acceptance -= 6
    acceptance = clamp(acceptance, 0, 20)

    volume_ratio = base["volume_ratio_vs_5d_same_time"]
    if 1.5 <= volume_ratio <= 3.5:
        volume_quality = 14
    elif 1.0 <= volume_ratio < 1.5:
        volume_quality = 10
    elif 3.5 < volume_ratio <= 5:
        volume_quality = 9
    elif volume_ratio > 5:
        volume_quality = 6
    else:
        volume_quality = 5
    if base["amount"] >= 2_000_000_000:
        volume_quality += 2
    elif base["amount"] < 500_000_000:
        volume_quality -= 3
    volume_quality = clamp(volume_quality, 0, 15)

    dist = daily["distance_to_ma5_pct"]
    if 0 <= dist <= 5:
        risk_position = 10
    elif 5 < dist <= 8:
        risk_position = 8
    elif 8 < dist <= 12:
        risk_position = 5
    elif 12 < dist <= 18:
        risk_position = 2
    else:
        risk_position = 0
    if base["pct"] > 8 and dist > 10:
        risk_position -= 3
    if base["pct"] >= 9.5 and base["drawdown_from_high_abs_pct"] > 1:
        risk_position -= 3
    if daily["recent5_gain_pct"] > 15 and base["pct"] > 5:
        risk_position -= 2
    risk_position = clamp(risk_position, 0, 10)

    continuity_map = {
        "昨日强线延续": 10,
        "昨日强线分歧": 7,
        "今日新切换": 8,
        "今日新切换仅前排": 5,
        "非昨日强线/非明确新切换": 3,
        "弱板块独强": 1,
    }
    continuity = continuity_map.get(sector_continuity_type, 3)

    parts = {
        "sector_quality": sector_quality,
        "stock_role": role,
        "intraday_acceptance": acceptance,
        "volume_price_quality": volume_quality,
        "position_risk": risk_position,
        "mainline_continuity": continuity,
    }
    raw_score = sum(parts.values())

    hard_caps: list[str] = []
    capped_score = raw_score
    def cap(max_score: int, reason: str) -> None:
        nonlocal capped_score
        if capped_score > max_score:
            capped_score = max_score
        hard_caps.append(reason)

    if sector_rank > 15:
        cap(70, "板块排名低")
    if not base["is_above_vwap"]:
        cap(65, "低于VWAP")
    if base["drawdown_from_high_abs_pct"] > 5:
        cap(70, "高点回撤大")
    if daily["distance_to_ma5_pct"] > 15:
        cap(70, "偏离5日线过大")
    if role_type == "未知":
        cap(75, "角色未知")
    if not is_watch_or_portfolio and base["amount"] < 500_000_000:
        cap(75, "非watchlist且成交额低")
    if advancers_ratio != "" and advancers_ratio < 0.5:
        cap(75, "板块涨家率低")

    return capped_score, parts, ";".join(hard_caps)


def evaluate_stock(
    quote: dict[str, Any],
    sector: Sector | None,
    sector_stat: dict[str, Any],
    daily_rows: list[dict[str, Any]],
    intraday_rows: list[dict[str, Any]],
    args: argparse.Namespace,
    watch_symbols: set[str],
    portfolio_codes: set[str],
) -> dict[str, Any] | None:
    target_time = metric_checkpoint(args)
    checkpoint_row = latest_at_or_before(intraday_rows, target_time)
    if not checkpoint_row:
        return None
    base = build_base_quote(quote, checkpoint_row)
    if not base:
        return None
    intraday_high, intraday_low = intraday_range_until(intraday_rows, target_time)
    if intraday_high is not None:
        base["high"] = intraday_high
    if intraday_low is not None:
        base["low"] = intraday_low
    daily = metrics_from_daily(daily_rows, base)
    if not daily:
        return None

    high = base["high"]
    low = base["low"]
    price = base["price"]
    base["vwap_distance_pct"] = (price - base["vwap"]) / base["vwap"] * 100
    base["drawdown_from_high_pct"] = (price - high) / high * 100
    base["drawdown_from_high_abs_pct"] = abs(base["drawdown_from_high_pct"])
    base["position_in_range"] = calc_position(price, high, low)
    base["is_above_vwap"] = price >= base["vwap"]
    base["is_above_open"] = price >= base["open"]
    base["reclaimed_vwap"] = base["is_above_vwap"] and any(num(row.get("p"), 0) < num(row.get("avg_p"), 0) for row in intraday_rows if str(row.get("m") or "") <= f"{target_time}:00")
    base["sustained_vwap_break_0945_1030"] = sustained_vwap_break(intraday_rows, "09:45:00", target_time)
    base["volume_ratio_vs_5d_same_time"] = same_time_volume_ratio(daily, intraday_rows, checkpoint_row)

    daily["distance_to_ma5_pct"] = (price - daily["ma5"]) / daily["ma5"] * 100
    daily["distance_to_ma10_pct"] = (price - daily["ma10"]) / daily["ma10"] * 100
    daily["distance_to_ma20_pct"] = (price - daily["ma20"]) / daily["ma20"] * 100 if daily.get("ma20") else ""
    daily["is_new_5d_high"] = price > daily["prev5_high"] and high > daily["prev5_high"]
    daily["reclaimed_ma5"] = price >= daily["ma5"] and low < daily["ma5"]
    daily["reclaimed_ma10"] = price >= daily["ma10"] and low < daily["ma10"]
    daily["reclaimed_ma20"] = bool(daily.get("ma20")) and price >= daily["ma20"] and low < daily["ma20"]

    sector_rank = sector.rank if sector else 999
    sector_pct = sector.pct if sector else 0
    relative_strength = base["pct"] - sector_pct

    risk_flags: list[str] = []
    if base["is_st"]:
        risk_flags.append("ST")
    if base["free_market_cap"] and args.min_free_market_cap and base["free_market_cap"] < args.min_free_market_cap:
        risk_flags.append("流通市值过小")
    if base["pct"] > 6 and not base["is_above_open"]:
        risk_flags.append("高开后跌破开盘价")
    if base["drawdown_from_high_abs_pct"] > 6 and base["volume_ratio_vs_5d_same_time"] >= 1.5:
        risk_flags.append("放量长上影")
    if sector and relative_strength < 0:
        risk_flags.append("弱于板块")

    pullback = (
        daily["recent5_gain_pct"] >= 8
        and daily["prev5_high_is_stage_high"]
        and -4 <= base["pct"] <= 2
        and base["volume_ratio_vs_5d_same_time"] <= 0.8
        and (price >= daily["ma5"] or daily["reclaimed_ma5"])
        and (price >= base["vwap"] or base["reclaimed_vwap"])
        and sector_rank <= args.pullback_sector_rank
        and base["drawdown_from_high_abs_pct"] <= 5
        and not base["is_st"]
    )
    breakout = (
        price > daily["prev5_high"]
        and high > daily["prev5_high"]
        and base["volume_ratio_vs_5d_same_time"] >= 1.5
        and price > base["vwap"]
        and price > base["open"]
        and daily["distance_to_ma5_pct"] <= 12
        and sector_rank <= args.top_sector_rank
        and base["drawdown_from_high_abs_pct"] <= 3
        and base["position_in_range"] >= 0.6
        and not base["is_st"]
    )
    setup = "缩量回踩" if pullback else "放量突破" if breakout else "none"

    is_watch_or_portfolio = str(base["symbol"]) in watch_symbols or str(base["code"]) in portfolio_codes
    role_type = infer_role_type(base, daily, sector, setup, is_watch_or_portfolio)
    sector_continuity_type = infer_sector_continuity_type(sector, role_type)
    score, parts, hard_cap_reason = score_candidate(base, daily, sector, sector_stat, setup, role_type, sector_continuity_type, is_watch_or_portfolio)
    pass_reasons: list[str] = []
    fail_reasons: list[str] = []
    if setup != "none":
        pass_reasons.append(setup)
    if risk_flags:
        fail_reasons.extend(risk_flags)
    if setup == "none":
        fail_reasons.append("未满足10:30 setup")

    return {
        "time": args.checkpoint,
        "code": base["code"],
        "symbol": base["symbol"],
        "name": base["name"],
        "sector": sector.name if sector else "",
        "sector_code": sector.code if sector else "",
        "sector_rank": sector_rank if sector else "",
        "sector_pct": round(sector_pct, 3) if sector else "",
        "price": round(price, 3),
        "pct": round(base["pct"], 3),
        "amount_1030": round(base["amount"], 0),
        "volume_ratio_vs_5d_same_time": round(base["volume_ratio_vs_5d_same_time"], 3),
        "vwap": round(base["vwap"], 3),
        "vwap_distance_pct": round(base["vwap_distance_pct"], 3),
        "open": round(base["open"], 3),
        "high": round(high, 3),
        "low": round(low, 3),
        "prev_close": round(daily["prev_close"], 3),
        "prev_low": round(daily["prev_low"], 3),
        "ma5": round(daily["ma5"], 3),
        "ma10": round(daily["ma10"], 3),
        "ma20": round(daily["ma20"], 3) if daily.get("ma20") else "",
        "ma10_slope_pct": round(daily["ma10_slope_pct"], 3) if daily.get("ma10_slope_pct") != "" else "",
        "ma20_slope_pct": round(daily["ma20_slope_pct"], 3) if daily.get("ma20_slope_pct") != "" else "",
        "prev5_high": round(daily["prev5_high"], 3),
        "prev20_high": round(daily["prev20_high"], 3),
        "prev5_high_is_stage_high": daily["prev5_high_is_stage_high"],
        "recent5_gain_pct": round(daily["recent5_gain_pct"], 3),
        "recent10_gain_pct": round(daily["recent10_gain_pct"], 3),
        "recent20_gain_pct": round(daily["recent20_gain_pct"], 3) if daily.get("recent20_gain_pct") != "" else "",
        "recent60_gain_pct": round(daily["recent60_gain_pct"], 3) if daily.get("recent60_gain_pct") != "" else "",
        "distance_to_ma5_pct": round(daily["distance_to_ma5_pct"], 3),
        "distance_to_ma10_pct": round(daily["distance_to_ma10_pct"], 3),
        "distance_to_ma20_pct": round(daily["distance_to_ma20_pct"], 3) if daily.get("distance_to_ma20_pct") != "" else "",
        "drawdown_from_20d_high_pct": round(daily["drawdown_from_20d_high_pct"], 3) if daily.get("drawdown_from_20d_high_pct") != "" else "",
        "drawdown_from_high_pct": round(base["drawdown_from_high_pct"], 3),
        "drawdown_from_high_abs_pct": round(base["drawdown_from_high_abs_pct"], 3),
        "position_in_range": round(base["position_in_range"], 3),
        "is_above_vwap": base["is_above_vwap"],
        "is_above_open": base["is_above_open"],
        "is_new_5d_high": daily["is_new_5d_high"],
        "reclaimed_ma5": daily["reclaimed_ma5"],
        "reclaimed_ma10": daily["reclaimed_ma10"],
        "reclaimed_ma20": daily["reclaimed_ma20"],
        "reclaimed_vwap": base["reclaimed_vwap"],
        "relative_strength_vs_sector": round(relative_strength, 3),
        "role_type": role_type,
        "sector_continuity_type": sector_continuity_type,
        "is_pullback_setup": pullback,
        "is_breakout_setup": breakout,
        "setup_name": setup,
        "setup_pass_reasons": ";".join(pass_reasons),
        "setup_fail_reasons": ";".join(fail_reasons),
        "risk_flags": ";".join(risk_flags),
        "hard_cap_reason": hard_cap_reason,
        "score": score,
        "score_breakdown": json.dumps(parts, ensure_ascii=False),
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None and rows:
        fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        if not fieldnames:
            file.write("")
            return
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_sina_hq_rows(raw: str) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    for line in raw.splitlines():
        match = re.match(r"var hq_str_(\w+)=\"(.*)\";", line)
        if not match:
            continue
        symbol, payload = match.groups()
        parsed[symbol] = payload.split(",")
    return parsed


def fetch_index_pcts(args: argparse.Namespace | None = None) -> tuple[dict[str, Any], str]:
    raw = subprocess.run(
        ["curl", "-fsSL", "-A", "Mozilla/5.0", "-e", "https://finance.sina.com.cn", SINA_HQ],
        check=True,
        capture_output=True,
        timeout=15,
    ).stdout.decode("gbk", "replace")
    hq_rows = parse_sina_hq_rows(raw)
    target_time = metric_checkpoint(args) if args is not None else ""
    output: dict[str, Any] = {}
    use_asof = bool(args is not None and target_time)
    source = "sina_index_minline_asof" if use_asof else "sina_hq_realtime"
    for symbol, label in INDEX_SYMBOLS.items():
        parts = hq_rows.get(symbol) or []
        prev_close = num(parts[2]) if len(parts) > 2 else None
        price = None
        if use_asof:
            try:
                row = latest_at_or_before(fetch_intraday(symbol), target_time)
                price = num(row.get("p")) if row else None
            except Exception:
                price = None
        else:
            price = num(parts[3]) if len(parts) > 3 else None
        pct = (price / prev_close - 1) * 100 if price and prev_close else None
        output[label] = round(pct, 3) if pct is not None else ""
    return output, source


def fetch_market_overview(quotes: list[dict[str, Any]], args: argparse.Namespace | None = None, results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    basis_rows = results or []
    overview: dict[str, Any] = {
        "时间": args.checkpoint if args is not None else CHECKPOINT,
        **{label: "" for label in INDEX_SYMBOLS.values()},
        "成交额预估": round(sum(num(row.get("amount_1030"), 0) or 0 for row in basis_rows), 0)
        if basis_rows
        else round(sum(num(row.get("amount"), 0) or 0 for row in quotes), 0),
        "涨跌家数": "",
        "涨停/跌停": "",
        "指数来源": "",
        "市场宽度来源": "asof_stock_aggregate" if basis_rows else "quote_snapshot",
    }
    try:
        index_pcts, index_source = fetch_index_pcts(args)
        overview.update(index_pcts)
        overview["指数来源"] = index_source
    except Exception as exc:
        overview["指数错误"] = str(exc)
    rows_for_breadth = basis_rows or quotes
    pct_key = "pct" if basis_rows else "changepercent"
    amount_symbol_key = "symbol"
    up = sum(1 for row in rows_for_breadth if (num(row.get(pct_key), 0) or 0) > 0)
    down = sum(1 for row in rows_for_breadth if (num(row.get(pct_key), 0) or 0) < 0)
    limit_up = sum(1 for row in rows_for_breadth if is_limit_up(str(row.get(amount_symbol_key) or ""), num(row.get(pct_key), 0) or 0))
    limit_down = sum(1 for row in rows_for_breadth if is_limit_down(str(row.get(amount_symbol_key) or ""), num(row.get(pct_key), 0) or 0))
    overview["涨跌家数"] = f"{up}/{down}"
    overview["涨停/跌停"] = f"{limit_up}/{limit_down}"
    return overview


def build_market_rows(sectors: list[Sector], sector_stats: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    amount_ranked = {sector.code: rank for rank, sector in enumerate(sorted(sectors, key=lambda item: item.amount, reverse=True), start=1)}
    for sector in sectors:
        status = "延续" if sector.rank <= 10 and sector.pct > 0 else "分歧" if sector.pct > 0 else "退潮"
        stats = sector_stats.get(sector.code, {})
        rows.append(
            {
                "时间": CHECKPOINT,
                "板块": sector.name,
                "板块来源": sector.source,
                "板块类型": sector.kind,
                "fallback_used": sector.fallback_used,
                "fetch_attempts": sector.fetch_attempts,
                "fallback_reason": sector.fallback_reason,
                "涨幅排名": sector.rank,
                "涨幅": round(sector.pct, 3),
                "成交额排名": amount_ranked[sector.code],
                "涨家率": round(stats.get("advancers_ratio", ""), 3) if stats.get("advancers_ratio", "") != "" else "",
                "涨停数": stats.get("limit_up_count", ""),
                "状态(延续/分歧/切换)": status,
                "领涨股": sector.leader_name,
            }
        )
    return rows


def build_hot_board_front_core_rows(
    checkpoint: str,
    sectors: list[Sector],
    results: list[dict[str, Any]],
    limit: int = 5,
    front_count: int = 3,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sector in sectors[:limit]:
        members = [row for row in results if row.get("sector") == sector.name]
        members.sort(key=lambda row: (num(row.get("pct"), -999) or -999, num(row.get("amount_1030"), 0) or 0), reverse=True)
        amount_sorted = sorted(members, key=lambda row: num(row.get("amount_1030"), 0) or 0, reverse=True)
        core_pool = [row for row in amount_sorted if row.get("role_type") == "中军"] or amount_sorted
        core_row = core_pool[0] if core_pool else {}
        front_pool = [row for row in members if row.get("code") != core_row.get("code")]
        front_rows = front_pool[:front_count]
        row = {
            "时间": checkpoint,
            "板块": sector.name,
            "板块来源": sector.source,
            "板块类型": sector.kind,
            "板块排名": sector.rank,
            "板块涨幅": round(sector.pct, 3),
            "fallback_used": sector.fallback_used,
            "fetch_attempts": sector.fetch_attempts,
            "fallback_reason": sector.fallback_reason,
            "中军股票": f"{core_row.get('name', '')} {core_row.get('code', '')}".strip() if core_row else "",
            "中军角色": core_row.get("role_type", "") if core_row else "",
            "中军涨幅": core_row.get("pct", "") if core_row else "",
            "中军成交额": core_row.get("amount_1030", "") if core_row else "",
            "中军VWAP": "上" if core_row.get("is_above_vwap") is True else "下" if core_row.get("is_above_vwap") is False else "unavailable",
            "数据状态": "ok" if members else "unavailable: no evaluated members for this board",
        }
        for index in range(front_count):
            front = front_rows[index] if index < len(front_rows) else {}
            prefix = f"前排{index + 1}"
            row[f"{prefix}股票"] = f"{front.get('name', '')} {front.get('code', '')}".strip() if front else ""
            row[f"{prefix}角色"] = front.get("role_type", "") if front else ""
            row[f"{prefix}涨幅"] = front.get("pct", "") if front else ""
            row[f"{prefix}成交额"] = front.get("amount_1030", "") if front else ""
            row[f"{prefix}VWAP"] = "上" if front.get("is_above_vwap") is True else "下" if front.get("is_above_vwap") is False else "unavailable"
        if not members and sector.leader_name:
            row["前排1股票"] = sector.leader_name
            row["前排1涨幅"] = round(sector.leader_pct, 3)
            row["数据状态"] = "partial: board leader only"
        rows.append(row)
    return rows


def load_portfolio_rows(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def build_watchlist_portfolio_rows(
    results: list[dict[str, Any]],
    watch_symbols: set[str] | None,
    portfolio_rows: list[dict[str, Any]],
    watch_meta: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    by_code = {row["code"]: row for row in results}
    portfolio_codes = {str(row.get("code") or "").zfill(6): row for row in portfolio_rows if row.get("code")}
    rows: list[dict[str, Any]] = []
    for result in results:
        symbol = result["symbol"]
        code = result["code"]
        is_watch = bool(watch_symbols and symbol in watch_symbols)
        is_portfolio = code in portfolio_codes
        if not is_watch and not is_portfolio:
            continue
        source = "portfolio" if is_portfolio else "watchlist"
        portfolio = portfolio_codes.get(code, {})
        risk_condition = bool(result["risk_flags"] or not result["is_above_vwap"])
        rows.append(
            {
                "time": result["time"],
                "code": code,
                "name": result["name"],
                "source": source,
                "走势自然语言": trajectory_text(result),
                "thesis": portfolio.get("thesis", ""),
                "current_price": result["price"],
                "pct": result["pct"],
                "sector_pct": result["sector_pct"],
                "is_above_vwap": result["is_above_vwap"],
                "relative_strength_vs_sector": result["relative_strength_vs_sector"],
                "planned_condition_met": result["is_pullback_setup"] or result["is_breakout_setup"],
                "risk_condition_met": risk_condition,
                "risk_reason": result["risk_flags"] or result["hard_cap_reason"],
            }
        )
    missing = set(portfolio_codes) - set(by_code)
    for code in sorted(missing):
        portfolio = portfolio_codes[code]
        rows.append(
            {
                "time": CHECKPOINT,
                "code": code,
                "name": portfolio.get("name", ""),
                "source": "portfolio",
                "走势自然语言": "行情未评估。",
                "thesis": portfolio.get("thesis", ""),
                "current_price": "",
                "pct": "",
                "sector_pct": "",
                "is_above_vwap": "",
                "relative_strength_vs_sector": "",
                "planned_condition_met": "",
                "risk_condition_met": "",
                "risk_reason": "行情未评估",
            }
        )
    watch_meta = watch_meta or {}
    watch_codes = {code_for_symbol(symbol) for symbol in (watch_symbols or set())}
    missing_watch = watch_codes - set(by_code) - set(portfolio_codes)
    for code in sorted(missing_watch):
        meta = watch_meta.get(code, {})
        rows.append(
            {
                "time": CHECKPOINT,
                "code": code,
                "name": meta.get("name", ""),
                "source": "watchlist",
                "走势自然语言": "行情未评估。",
                "thesis": meta.get("thesis", ""),
                "current_price": "",
                "pct": "",
                "sector_pct": "",
                "is_above_vwap": "",
                "relative_strength_vs_sector": "",
                "planned_condition_met": "",
                "risk_condition_met": "",
                "risk_reason": "行情未评估",
            }
        )
    return rows


def source_for_result(row: dict[str, Any], watch_symbols: set[str], portfolio_codes: set[str]) -> str:
    sources: list[str] = []
    if row["is_breakout_setup"]:
        sources.append("放量突破")
    if row["is_pullback_setup"]:
        sources.append("缩量回踩")
    if row["symbol"] in watch_symbols:
        sources.append("watchlist")
    if row["code"] in portfolio_codes:
        sources.append("portfolio")
    return "/".join(sources)


def build_data_packet_candidates(
    results: list[dict[str, Any]],
    watch_symbols: set[str],
    portfolio_codes: set[str],
    watch_meta: dict[str, dict[str, str]] | None = None,
    portfolio_meta: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for row in results:
        include = row["is_breakout_setup"] or row["is_pullback_setup"] or row["symbol"] in watch_symbols or row["code"] in portfolio_codes
        if not include:
            continue
        seen_codes.add(row["code"])
        rows.append(
            {
                "时间": row["time"],
                "股票": f"{row['name']} {row['code']}",
                "来源(缩量回踩/放量突破/watchlist/portfolio)": source_for_result(row, watch_symbols, portfolio_codes),
                "走势自然语言": trajectory_text(row),
                "板块": row["sector"],
                "当前价": row["price"],
                "当前涨幅": row["pct"],
                "板块排名": row["sector_rank"],
                "板块涨幅": row["sector_pct"],
                "VWAP距离%": row["vwap_distance_pct"],
                "今日高点回撤%": row["drawdown_from_high_pct"],
                "日内位置%": round(row["position_in_range"] * 100, 2),
                "量比": row["volume_ratio_vs_5d_same_time"],
                "成交额": row["amount_1030"],
                "距5日线%": row["distance_to_ma5_pct"],
                "是否突破5日高点": row["is_new_5d_high"],
                "是否强于板块": row["relative_strength_vs_sector"] > 0 if row["relative_strength_vs_sector"] != "" else "",
                "hard_cap_reason": row["hard_cap_reason"],
                "分数": row["score"],
                "风险标记": row["risk_flags"],
            }
        )
    watch_meta = watch_meta or {}
    portfolio_meta = portfolio_meta or {}
    missing_codes = ({code_for_symbol(symbol) for symbol in watch_symbols} | portfolio_codes) - seen_codes
    for code in sorted(missing_codes):
        meta = portfolio_meta.get(code) or watch_meta.get(code, {})
        source = "portfolio" if code in portfolio_codes else "watchlist"
        rows.append(
            {
                "时间": CHECKPOINT,
                "股票": f"{meta.get('name', '')} {code}".strip(),
                "来源(缩量回踩/放量突破/watchlist/portfolio)": source,
                "走势自然语言": "行情未评估。",
                "板块": "",
                "当前价": "",
                "当前涨幅": "",
                "板块排名": "",
                "板块涨幅": "",
                "VWAP距离%": "",
                "今日高点回撤%": "",
                "日内位置%": "",
                "量比": "",
                "成交额": "",
                "距5日线%": "",
                "是否突破5日高点": "",
                "是否强于板块": "",
                "hard_cap_reason": "行情未评估",
                "分数": "",
                "风险标记": "行情未评估",
            }
        )
    rows.sort(key=lambda item: (0 if "portfolio" in item["来源(缩量回踩/放量突破/watchlist/portfolio)"] else 1, -float(item["分数"] or 0)))
    return rows


def signed_pct_text(value: Any, digits: int = 1) -> str:
    parsed = num(value, 0) or 0
    return f"{parsed:+.{digits}f}%"


def trajectory_text(row: dict[str, Any]) -> str:
    prev_close = num(row.get("prev_close"), 0) or 0
    if prev_close <= 0:
        pct = row.get("pct", "")
        if pct == "":
            return "行情未评估。"
        vwap_side = "上方" if row.get("is_above_vwap") is True else "下方" if row.get("is_above_vwap") is False else "附近"
        return f"当前 {signed_pct_text(pct)}，VWAP {vwap_side}。"
    open_price = num(row.get("open"), 0) or 0
    high = num(row.get("high"), 0) or 0
    low = num(row.get("low"), 0) or 0
    price = num(row.get("price"), 0) or 0
    if min(open_price, high, low, price) <= 0:
        return "行情未评估。"
    open_pct = (open_price / prev_close - 1) * 100
    high_pct = (high / prev_close - 1) * 100
    low_pct = (low / prev_close - 1) * 100
    current_pct = num(row.get("pct"), (price / prev_close - 1) * 100) or 0
    vwap_side = "上方" if row.get("is_above_vwap") is True else "下方" if row.get("is_above_vwap") is False else "附近"
    parts = [f"{'高开' if open_pct > 0.5 else '低开' if open_pct < -0.5 else '平开'} {signed_pct_text(open_pct)}"]
    if high_pct > open_pct + 0.3:
        parts.append(f"最高冲到 {signed_pct_text(high_pct)}")
    if low_pct < current_pct - 0.3:
        parts.append(f"最低探到 {signed_pct_text(low_pct)}")
    if current_pct < open_pct - 0.3:
        parts.append(f"回落到 {signed_pct_text(current_pct)}")
    else:
        parts.append(f"当前 {signed_pct_text(current_pct)}")
    parts.append(f"VWAP {vwap_side}")
    drawdown = num(row.get("drawdown_from_high_pct"), 0) or 0
    if drawdown < -3:
        parts.append(f"较高点回撤 {signed_pct_text(drawdown)}")
    return "，".join(parts) + "。"


def row_float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    parsed = num(row.get(key))
    return parsed if parsed is not None else default


def pullback_setup_type(row: dict[str, Any]) -> str:
    dist5 = row_float(row, "distance_to_ma5_pct", 999)
    dist10 = row_float(row, "distance_to_ma10_pct", 999)
    dist20 = row_float(row, "distance_to_ma20_pct", 999)
    recent10 = row_float(row, "recent10_gain_pct")
    recent20 = row_float(row, "recent20_gain_pct")
    recent60 = row_float(row, "recent60_gain_pct")
    ma10_slope = row_float(row, "ma10_slope_pct")
    ma20_slope = row_float(row, "ma20_slope_pct")
    drawdown20 = abs(row_float(row, "drawdown_from_20d_high_pct"))
    price = row_float(row, "price")
    ma10 = row_float(row, "ma10")
    ma20 = row_float(row, "ma20")
    sector_rank = int(row_float(row, "sector_rank", 999))
    volume_ratio = row_float(row, "volume_ratio_vs_5d_same_time")

    if recent10 >= 15 and abs(dist5) <= 2 and price >= ma10 and sector_rank <= 15 and volume_ratio <= 1.5:
        return "pullback_ma5_strong"
    if recent20 >= 25 and abs(dist10) <= 2.5 and ma10_slope >= -0.2 and (not ma20 or price >= ma20) and 6 <= drawdown20 <= 20 and sector_rank <= 25:
        return "pullback_ma10_trend"
    if recent60 >= 15 and abs(dist20) <= 3 and ma20 and ma20_slope >= -0.3 and drawdown20 <= 25 and sector_rank <= 30:
        return "pullback_ma20_swing"
    if recent10 >= 12 and abs(dist5) <= 3 and not row.get("is_new_5d_high") and sector_rank <= 25:
        return "failed_breakout_reclaim"
    return ""


def pullback_type_label(setup_type: str) -> str:
    return {
        "pullback_ma5_strong": "强趋势 5日线回踩",
        "pullback_ma10_trend": "趋势 10日线回踩",
        "pullback_ma20_swing": "中线 20日线回踩",
        "failed_breakout_reclaim": "高位反抽观察",
        "do_not_chase_to_pullback_watch": "不可追转回踩观察",
    }.get(setup_type, "热门股回踩观察")


def pullback_checkpoint_text(checkpoint: str, category: str, row: dict[str, Any]) -> tuple[str, str]:
    above_vwap = row.get("is_above_vwap") is True
    above_open = row.get("is_above_open") is True
    position = row_float(row, "position_in_range")
    if checkpoint in {"09:25", "9:25"}:
        return "盘前观察池", "只生成观察池，不追昨日高潮股；开盘后看低开承接和 VWAP。"
    if checkpoint in {"09:45", "9:45"}:
        if above_vwap and above_open:
            return "初步承接", "等 10:30 换手确认，不在 09:45 直接下结论。"
        if not above_vwap and position < 0.4:
            return "未承接", "不低吸，等是否重新站回 VWAP。"
        return "假修复待辨认", "看 10:30 是否继续站回 VWAP，冲高回落则降级。"
    if checkpoint in {"10:30", "1030"}:
        if category == "回踩确认":
            return "强趋势回踩成立", "11:20 看是否维持 VWAP 上方且板块不掉队。"
        if above_vwap:
            return "回踩待确认", "11:20 看是否不破上午低点、成交不恐慌放大。"
        return "只观察，不低吸", "先等收回 VWAP，再看板块是否仍在前排。"
    if checkpoint in {"11:20", "1120"}:
        if above_vwap and position >= 0.5:
            return "上午承接保留", "午后继续观察是否维持 VWAP 上方。"
        return "午前反抽不足", "午后只看尾盘修复，弱票不要给太多幻想。"
    if checkpoint in {"13:30", "1330"}:
        if above_vwap and position >= 0.55:
            return "午后回流确认", "14:30 看是否突破上午高点且板块回流。"
        return "午后假修复风险", "跌破上午低点或板块流出则剔除。"
    if checkpoint in {"14:30", "14:40", "1430", "1440"}:
        if above_vwap:
            return "尾盘承接 K 待确认", "收盘站上 VWAP/均线且不跳水，才可带入明日观察。"
        return "不带到明天", "尾盘跌回 VWAP 或关键均线下方，不进入明日重点。"
    if checkpoint in {"15:10", "1510"}:
        if above_vwap:
            return "今日回踩成功样本", "明日只看二次确认，不追高开急冲。"
        return "今日回踩失败样本", "归档失败原因，明日不作为低吸优先级。"
    return "回踩观察", "下一 checkpoint 继续验证 VWAP、均线和板块强度。"


def build_pullback_setup_rows(
    results: list[dict[str, Any]],
    watch_symbols: set[str],
    portfolio_codes: set[str],
    checkpoint: str,
    limit: int = 80,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in results:
        if row.get("risk_flags") and "ST" in str(row.get("risk_flags")):
            continue
        sector_rank = int(row_float(row, "sector_rank", 999))
        amount = row_float(row, "amount_1030")
        recent10 = row_float(row, "recent10_gain_pct")
        recent20 = row_float(row, "recent20_gain_pct")
        recent60 = row_float(row, "recent60_gain_pct")
        drawdown20 = abs(row_float(row, "drawdown_from_20d_high_pct"))
        dist5 = row_float(row, "distance_to_ma5_pct", 999)
        dist10 = row_float(row, "distance_to_ma10_pct", 999)
        dist20 = row_float(row, "distance_to_ma20_pct", 999)
        volume_ratio = row_float(row, "volume_ratio_vs_5d_same_time")
        source_flags: list[str] = []
        if sector_rank <= 10:
            source_flags.append("强板块")
        if row.get("symbol") in watch_symbols:
            source_flags.append("watchlist")
        if row.get("code") in portfolio_codes:
            source_flags.append("portfolio")
        if recent10 >= 15 or recent20 >= 25:
            source_flags.append("近期强势股")
        if row.get("hard_cap_reason") and ("偏离5日线过大" in str(row.get("hard_cap_reason")) or "高点回撤大" in str(row.get("hard_cap_reason"))):
            source_flags.append("do_not_chase_to_pullback_watch")

        qualification = 0
        qualification += 8 if sector_rank <= 10 else 4 if sector_rank <= 20 else 0
        qualification += 6 if recent20 >= 20 else 0
        qualification += 6 if recent10 >= 15 else 0
        qualification += 5 if row.get("symbol") in watch_symbols or row.get("code") in portfolio_codes else 0
        qualification += 5 if amount >= 500_000_000 else 0
        if qualification < 15 or not source_flags:
            continue

        setup_type = pullback_setup_type(row)
        if "do_not_chase_to_pullback_watch" in source_flags and setup_type in {"pullback_ma5_strong", "pullback_ma10_trend", "failed_breakout_reclaim"}:
            setup_type = "do_not_chase_to_pullback_watch"
        if not setup_type and min(abs(dist5), abs(dist10), abs(dist20)) <= 3 and (recent10 >= 10 or recent20 >= 15 or recent60 >= 15):
            setup_type = "pullback_ma20_swing" if abs(dist20) <= 3 else "failed_breakout_reclaim"
        if not setup_type:
            continue

        position_score = 0
        position_score += 10 if abs(dist5) <= 2 else 0
        position_score += 8 if abs(dist10) <= 2.5 else 0
        position_score += 6 if abs(dist20) <= 3 else 0
        position_score += 5 if row.get("ma20") == "" or row_float(row, "price") >= row_float(row, "ma20") else -10
        position_score += 5 if 6 <= drawdown20 <= 18 else -8 if drawdown20 > 25 else 0
        position_score = clamp(position_score, -18, 25)

        acceptance = 0
        acceptance += 8 if row.get("is_above_vwap") is True else -8
        acceptance += 5 if row.get("is_above_open") is True else 0
        acceptance += 5 if row_float(row, "position_in_range") > 0.5 else 0
        acceptance += 4 if row.get("reclaimed_vwap") or row.get("reclaimed_ma5") or row.get("reclaimed_ma10") else 0
        acceptance += 3 if 0 < volume_ratio <= 1.3 else 1 if volume_ratio <= 2 else -3
        acceptance += -5 if abs(row_float(row, "drawdown_from_high_pct")) > 3 else 0
        acceptance = clamp(acceptance, -18, 25)

        sector_sync = 0
        sector_sync += 6 if sector_rank <= 10 else 3 if sector_rank <= 15 else 0
        sector_sync += 4 if row.get("role_type") == "中军" else 0
        sector_sync += 2 if row_float(row, "relative_strength_vs_sector") > 0 else 0
        sector_sync += -8 if sector_rank > 30 else 0
        sector_sync = clamp(sector_sync, -10, 15)

        risk_penalty = 0
        risk_penalty -= 5 if row_float(row, "pct") > 12 else 0
        risk_penalty -= 8 if recent10 > 30 else 0
        risk_penalty -= 6 if abs(row_float(row, "drawdown_from_high_pct")) > 4 else 0
        risk_penalty -= 5 if volume_ratio > 5 else 0
        risk_penalty -= 8 if amount < 300_000_000 else 0
        risk_penalty -= 10 if "ST" in str(row.get("risk_flags") or "") else 0
        risk_penalty = max(risk_penalty, -25)

        score = int(clamp(qualification + position_score + acceptance + sector_sync + risk_penalty, 0, 100))
        if score >= 80:
            category = "回踩确认"
        elif score >= 65:
            category = "回踩待确认"
        elif score >= 50:
            category = "只观察"
        else:
            category = "失败/剔除"
        status, next_step = pullback_checkpoint_text(checkpoint, category, row)
        risk_parts = [
            "板块退潮" if sector_rank > 20 else "",
            "未收回 VWAP" if row.get("is_above_vwap") is not True else "",
            "跌破 MA20" if row.get("ma20") != "" and row_float(row, "price") < row_float(row, "ma20") else "",
            "高位拥挤" if recent10 > 30 else "",
            row.get("risk_flags") or "",
        ]
        rows.append(
            {
                "时间": checkpoint,
                "股票": f"{row['name']} {row['code']}",
                "板块": row.get("sector", ""),
                "回踩类型": pullback_type_label(setup_type),
                "setup": setup_type,
                "分类": category,
                "状态": status,
                "分数": score,
                "资格分": qualification,
                "位置分": position_score,
                "承接分": acceptance,
                "板块同步分": sector_sync,
                "风险扣分": risk_penalty,
                "走势自然语言": trajectory_text(row),
                "当前价": row.get("price", ""),
                "当前涨幅": row.get("pct", ""),
                "板块排名": row.get("sector_rank", ""),
                "板块涨幅": row.get("sector_pct", ""),
                "MA5": row.get("ma5", ""),
                "MA10": row.get("ma10", ""),
                "MA20": row.get("ma20", ""),
                "距MA5%": row.get("distance_to_ma5_pct", ""),
                "距MA10%": row.get("distance_to_ma10_pct", ""),
                "距MA20%": row.get("distance_to_ma20_pct", ""),
                "VWAP": row.get("vwap", ""),
                "VWAP状态": "已收回/上方" if row.get("is_above_vwap") is True else "未收回/下方",
                "上午低点": row.get("low", ""),
                "日内位置%": round(row_float(row, "position_in_range") * 100, 2),
                "近10日涨幅%": row.get("recent10_gain_pct", ""),
                "近20日涨幅%": row.get("recent20_gain_pct", ""),
                "近60日涨幅%": row.get("recent60_gain_pct", ""),
                "20日高点回撤%": row.get("drawdown_from_20d_high_pct", ""),
                "量比": row.get("volume_ratio_vs_5d_same_time", ""),
                "来源": "/".join(source_flags),
                "下一步": next_step,
                "风险": "；".join(part for part in risk_parts if part),
                "提示": "回踩确认不等于立即买入；它只表示从不可追高变成有观察价值。",
            }
        )
    rows.sort(key=lambda item: ({"回踩确认": 0, "回踩待确认": 1, "只观察": 2, "失败/剔除": 3}.get(item["分类"], 9), -int(item["分数"] or 0)))
    return rows[:limit]


def build_portfolio_extra_rows(portfolio: dict[str, dict[str, Any]], plans: dict[str, dict[str, str]], result_by_code: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code, holding in portfolio.items():
        result = result_by_code.get(code, {})
        plan = plans.get(code, {})
        current_price = num(result.get("price")) or num(holding.get("current_snapshot"))
        avg_cost = num(holding.get("avg_cost"))
        shares = num(holding.get("shares_total"), 0) or 0
        pnl = (current_price - avg_cost) * shares if current_price is not None and avg_cost is not None else ""
        rows.append(
            {
                "股票": f"{holding.get('name', '')} {code}",
                "持仓数量": holding.get("shares_total", ""),
                "成本": holding.get("avg_cost", ""),
                "昨日新增仓": holding.get("shares_added_recently", ""),
                "当前浮盈亏": round(pnl, 2) if pnl != "" else "",
                "关键位1": plan.get("key_support_1", ""),
                "关键位2": plan.get("key_support_2", ""),
                "原计划确认条件": plan.get("planned_buy_condition", ""),
                "原计划失效条件": plan.get("planned_sell_or_downgrade_condition", ""),
            }
        )
    return rows


def next_checkpoint_name(checkpoint: str) -> str:
    key = str(checkpoint or "").replace(":", "")
    mapping = {
        "925": "09:45",
        "0925": "09:45",
        "945": "10:30",
        "0945": "10:30",
        "1030": "11:20",
        "1120": "13:30",
        "1330": "14:30",
        "1430": "15:10",
        "1440": "15:10",
        "1510": "明日 09:45",
    }
    return mapping.get(key, "下一 checkpoint")


def price_level(value: Any) -> str:
    parsed = num(value)
    return f"{parsed:.2f}" if parsed is not None and parsed > 0 else ""


def bool_text(value: Any) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return "unavailable"


def portfolio_position_type(row: dict[str, Any], plan: dict[str, Any]) -> str:
    if not row:
        return "数据不足，人工复核"
    pct = row_float(row, "pct")
    drawdown = abs(row_float(row, "drawdown_from_high_pct"))
    rel = row_float(row, "relative_strength_vs_sector")
    above_vwap = row.get("is_above_vwap") is True
    risk = bool(row.get("risk_flags")) or row.get("is_above_vwap") is False
    support = num(plan.get("key_support_1"))
    price = num(row.get("price"))
    if support is not None and price is not None and price < support:
        return "必须处理 / 风险触发"
    if risk and (rel < 0 or not above_vwap):
        return "必须处理 / 风险触发"
    if rel < 0 or not above_vwap:
        return "弱于板块 / 修复失败"
    if pct >= 6 and drawdown <= 3:
        return "冲高后保护利润"
    if above_vwap and (pct >= 3 or row_float(row, "recent10_gain_pct") >= 10):
        return "强势趋势持有"
    return "正常震荡持有"


def portfolio_key_levels(row: dict[str, Any]) -> dict[str, str]:
    if not row:
        return {}
    stop_candidates = [num(row.get("prev_low")), num(row.get("ma5"))]
    stop_candidates = [value for value in stop_candidates if value is not None and value > 0]
    return {
        "强势线": price_level(row.get("high")),
        "修复线": price_level(row.get("vwap")),
        "第一保护线": price_level(row.get("vwap")),
        "风险线": price_level(row.get("low")),
        "止损线": price_level(max(stop_candidates) if stop_candidates else ""),
        "趋势线": price_level(row.get("ma5")),
        "中线观察线": price_level(row.get("ma10")),
        "中线失效线": price_level(row.get("ma20")),
        "昨日低点": price_level(row.get("prev_low")),
    }


def portfolio_action_plan(position_type: str, levels: dict[str, str], next_check: str) -> list[str]:
    vwap = levels.get("第一保护线") or "VWAP"
    repair = levels.get("修复线") or "VWAP"
    risk = levels.get("风险线") or "上午低点"
    stop = levels.get("止损线") or "昨日低点 / 5日线"
    if "数据不足" in position_type:
        return ["数据不足，无法给出交易条件", "需要人工复核现价、VWAP、上午低点、昨日低点和均线"]
    if "必须处理" in position_type or "修复失败" in position_type:
        return [
            "不补仓",
            f"重新站回 {repair} 且强于板块，才降级为观察",
            f"跌破 {risk}，先降风险",
            f"跌破 {stop}，短线仓退出",
            f"{next_check} 仍弱于板块，减仓处理",
        ]
    if "冲高后保护" in position_type or "强势趋势" in position_type:
        return [
            "不追高加仓",
            f"维持 {vwap} 上方，继续持有",
            f"跌破 {vwap} 且 15 分钟不能收回，减 1/3",
            f"跌破 {risk}，减半或退出短线仓",
            f"跌破 {stop}，短线仓退出，只保留有 thesis 的底仓",
        ]
    return [
        "不追高，不补弱",
        f"维持 {vwap} 上方，正常持有",
        f"跌破 {vwap}，转观察",
        f"跌破 {risk}，降风险",
        f"跌破 {stop}，短线仓退出",
    ]


def portfolio_data_warning(row: dict[str, Any]) -> str:
    if not row:
        return "行情数据缺失，无法给出交易条件"
    price = num(row.get("price"))
    high = num(row.get("high"))
    low = num(row.get("low"))
    warnings: list[str] = []
    if price is not None and high is not None and price > high + 0.001:
        warnings.append("数据异常：当前价高于日内最高价")
    if price is not None and low is not None and price < low - 0.001:
        warnings.append("数据异常：当前价低于日内最低价")
    if high is not None and low is not None and high < low:
        warnings.append("数据异常：日内最高价低于最低价")
    return "；".join(warnings)


def build_portfolio_decision_rule_rows(
    portfolio: dict[str, dict[str, Any]],
    plans: dict[str, dict[str, str]],
    result_by_code: dict[str, dict[str, Any]],
    checkpoint: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    next_check = next_checkpoint_name(checkpoint)
    for code, holding in portfolio.items():
        result = result_by_code.get(code, {})
        plan = plans.get(code, {})
        position_type = portfolio_position_type(result, plan)
        levels = portfolio_key_levels(result)
        actions = portfolio_action_plan(position_type, levels, next_check)
        current_price = num(result.get("price")) or num(holding.get("current_snapshot"))
        avg_cost = num(holding.get("avg_cost"))
        shares = num(holding.get("shares_total"), 0) or 0
        pnl = (current_price - avg_cost) * shares if current_price is not None and avg_cost is not None else ""
        rows.append(
            {
                "时间": checkpoint,
                "股票": f"{holding.get('name', '')} {code}".strip(),
                "类型": position_type,
                "当前状态": trajectory_text(result) if result else "行情未评估。",
                "当前价": price_level(current_price),
                "当前涨幅": result.get("pct", ""),
                "VWAP": levels.get("第一保护线", ""),
                "VWAP状态": "上" if result.get("is_above_vwap") is True else "下" if result.get("is_above_vwap") is False else "unavailable",
                "高点回撤%": result.get("drawdown_from_high_pct", ""),
                "相对板块": "强于板块" if row_float(result, "relative_strength_vs_sector") > 0 else "弱于板块" if result else "unavailable",
                "板块": result.get("sector", ""),
                "板块涨幅": result.get("sector_pct", ""),
                "强势线": levels.get("强势线", ""),
                "修复线": levels.get("修复线", ""),
                "第一保护线": levels.get("第一保护线", ""),
                "风险线": levels.get("风险线", ""),
                "止损线": levels.get("止损线", ""),
                "趋势线": levels.get("趋势线", ""),
                "中线观察线": levels.get("中线观察线", ""),
                "中线失效线": levels.get("中线失效线", ""),
                "昨日低点": levels.get("昨日低点", ""),
                "成本": holding.get("avg_cost", ""),
                "持仓数量": holding.get("shares_total", ""),
                "当前浮盈亏": round(pnl, 2) if pnl != "" else "",
                "短线动作": "；".join(actions[:4]),
                "中线动作": f"跌破 {levels.get('中线观察线') or '10日线'} 降低总仓位；跌破 {levels.get('中线失效线') or '20日线'} 重新判断 thesis",
                "长线动作": "只看 thesis 是否失效，不因盘中单点波动改变底仓判断",
                "下一次检查": next_check,
                "数据提示": portfolio_data_warning(result),
                "风险原因": result.get("risk_flags") or result.get("hard_cap_reason") or "",
                "原计划确认条件": plan.get("planned_buy_condition", ""),
                "原计划失效条件": plan.get("planned_sell_or_downgrade_condition", ""),
                "是否触发风险条件": bool_text("必须处理" in position_type or "修复失败" in position_type),
            }
        )
    order = {"必须处理 / 风险触发": 0, "弱于板块 / 修复失败": 1, "冲高后保护利润": 2, "强势趋势持有": 3, "正常震荡持有": 4}
    rows.sort(key=lambda item: order.get(str(item.get("类型")), 9))
    return rows


def main() -> int:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    default_watchlist = args.investment_dir / "watchlist.md"
    default_portfolio = args.investment_dir / "portfolio.md"
    watch_meta = parse_watchlist_markdown(default_watchlist)
    plan_meta = parse_plan_rows_from_watchlist(default_watchlist)
    tech_sector_rows = parse_tech_sector_branches(default_watchlist)
    tech_symbols = tech_sector_symbols(tech_sector_rows)
    portfolio_meta = parse_portfolio_markdown(default_portfolio)
    watch_symbols_from_md = {symbol_for_code(code) for code in watch_meta}
    portfolio_symbols_from_md = {symbol_for_code(code) for code in portfolio_meta}
    portfolio_codes = set(portfolio_meta)
    csv_watch_symbols = read_symbol_pool(args.watchlist) if args.watchlist else set()
    watch_symbols = watch_symbols_from_md | csv_watch_symbols
    required_symbols = watch_symbols | portfolio_symbols_from_md | tech_symbols
    pool_symbols = watch_symbols if args.pool == "watchlist" else None

    print("fetch sectors")
    sectors = fetch_sectors()
    print("fetch sector members")
    sector_by_symbol, sector_stats = fetch_sector_members(sectors)
    print("fetch quotes")
    quotes = fetch_quotes(pool_symbols=pool_symbols, limit=args.limit)
    existing_symbols = {str(row.get("symbol") or "") for row in quotes}
    missing_required = required_symbols - existing_symbols
    for symbol in sorted(missing_required):
        fetched = fetch_json(
            SINA_QUOTES,
            {
                "page": 1,
                "num": 1,
                "sort": "changepercent",
                "asc": 0,
                "node": "hs_a",
                "symbol": symbol,
                "_s_r_a": "page",
            },
        )
        # The quote-center endpoint ignores symbol for some nodes; fall back to full-market quote already fetched.
        if fetched and isinstance(fetched, list):
            for row in fetched:
                if str(row.get("symbol") or "") == symbol:
                    quotes.append(row)
                    break
    print(f"quotes {len(quotes)}")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    daily_by_symbol: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {}
        for quote in quotes:
            symbol = str(quote.get("symbol") or "")
            futures[executor.submit(lambda s=symbol: (s, fetch_daily(s), fetch_intraday(s)))] = quote
        for done, future in enumerate(as_completed(futures), start=1):
            quote = futures[future]
            symbol = str(quote.get("symbol") or "")
            try:
                _, daily_rows, intraday_rows = future.result()
                daily_by_symbol[symbol] = daily_rows
                sector = sector_by_symbol.get(symbol)
                evaluated = evaluate_stock(
                    quote,
                    sector,
                    sector_stats.get(sector.code, {}) if sector else {},
                    daily_rows,
                    intraday_rows,
                    args,
                    watch_symbols,
                    portfolio_codes,
                )
                if evaluated:
                    results.append(evaluated)
            except Exception as exc:
                errors.append({"symbol": symbol, "code": code_for_symbol(symbol), "name": str(quote.get("name") or ""), "error": str(exc)})
            if done % 500 == 0:
                print(f"evaluated {done}/{len(quotes)}")

    portfolio_rows_for_actions = [
        {"code": code, "name": row.get("name", ""), "thesis": plan_meta.get(code, {}).get("thesis", "")}
        for code, row in portfolio_meta.items()
    ]
    sectors, sector_stats = aggregate_sector_snapshot(sectors, results)
    apply_sector_snapshot_to_results(results, sectors)

    candidates = build_data_packet_candidates(results, watch_symbols, portfolio_codes, watch_meta, portfolio_meta)
    pullback_rows = build_pullback_setup_rows(results, watch_symbols, portfolio_codes, args.checkpoint)

    market_overview = fetch_market_overview(quotes, args, results)
    market_rows = build_market_rows(sectors, sector_stats)
    hot_board_front_core_rows = build_hot_board_front_core_rows(args.checkpoint, sectors, results)
    extra_portfolio_rows = load_portfolio_rows(args.portfolio)
    portfolio_rows = portfolio_rows_for_actions + extra_portfolio_rows
    handling_rows = build_watchlist_portfolio_rows(results, watch_symbols, portfolio_rows, watch_meta)
    result_by_code = {row["code"]: row for row in results}
    portfolio_extra_rows = build_portfolio_extra_rows(portfolio_meta, plan_meta, result_by_code)
    portfolio_decision_rows = build_portfolio_decision_rule_rows(portfolio_meta, plan_meta, result_by_code, args.checkpoint)
    tech_sector_daily_rows = build_tech_sector_daily_rows(tech_sector_rows, daily_by_symbol)
    tech_sector_stock_map = build_tech_sector_stock_map(tech_sector_rows)

    write_csv(args.out / "market_overview.csv", [market_overview])
    write_csv(args.out / "market_sector_scan.csv", market_rows)
    write_csv(args.out / "hot_board_front_core.csv", hot_board_front_core_rows)
    write_csv(args.out / "candidate_scores.csv", candidates)
    write_csv(args.out / "pullback_setups.csv", pullback_rows)
    write_csv(args.out / "watchlist_portfolio_actions.csv", handling_rows)
    write_csv(args.out / "portfolio_extra.csv", portfolio_extra_rows)
    write_csv(args.out / "portfolio_decision_rules.csv", portfolio_decision_rows)
    write_csv(args.out / "tech_sector_daily_k.csv", tech_sector_daily_rows)
    write_csv(args.out / "tech_sector_stock_map.csv", tech_sector_stock_map)
    write_csv(args.out / "errors.csv", errors, ["symbol", "code", "name", "error"])

    fallback_used = any(sector.fallback_used for sector in sectors)
    fetch_attempts = max((sector.fetch_attempts for sector in sectors), default=1)
    fallback_reason = next((sector.fallback_reason for sector in sectors if sector.fallback_reason), "")
    sector_source_chain = sorted({sector.source for sector in sectors if sector.source})
    quote_source_chain = sorted({str(row.get("source") or "sina_quote_center") for row in quotes})
    field_availability = summarize_field_availability(results, INTRADAY_FIELD_AVAILABILITY_FIELDS)
    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "checkpoint": args.checkpoint,
        "data_timestamp": TODAY,
        **summary_snapshot_fields(args, results),
        "stock_pool": args.pool,
        "source_chain": sector_source_chain + quote_source_chain + ["Sina daily KLine", "Sina CN_MinlineService"],
        "sector_source_chain": sector_source_chain,
        "quote_source_chain": quote_source_chain,
        "fallback_used": fallback_used,
        "fetch_attempts": fetch_attempts,
        "fallback_reason": fallback_reason,
        "market_row_count": len(market_rows),
        "hot_board_front_core_count": len(hot_board_front_core_rows),
        "quote_count": len(quotes),
        "evaluated_count": len(results),
        "candidate_count": len(candidates),
        "pullback_setup_count": len(pullback_rows),
        "pullback_count": sum(1 for row in results if row["is_pullback_setup"]),
        "breakout_count": sum(1 for row in results if row["is_breakout_setup"]),
        "watchlist_count": len(watch_symbols),
        "portfolio_count": len(portfolio_rows),
        "tech_sector_branch_count": len({row.get("branch") for row in tech_sector_rows if row.get("branch")}),
        "tech_sector_target_count": len(tech_sector_rows),
        "tech_sector_resolved_count": sum(1 for row in tech_sector_rows if row.get("status") == "resolved"),
        "tech_sector_daily_row_count": len(tech_sector_daily_rows),
        "watchlist_portfolio_action_count": len(handling_rows),
        "portfolio_extra_count": len(portfolio_extra_rows),
        "portfolio_decision_rule_count": len(portfolio_decision_rows),
        "error_count": len(errors),
        "usable_fields": field_availability["usable_fields"],
        "unusable_fields": field_availability["unusable_fields"],
        "field_availability": field_availability,
        "known_limits": [
            "volume_ratio_vs_5d_same_time is approximated from daily five-day average when historical same-time intraday bars are unavailable",
            "yesterday_hot_sector is not yet implemented",
        ],
    }
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    decision = decision_summary.build_checkpoint_decision_summary(
        checkpoint=args.checkpoint,
        summary=summary,
        tables={
            "market_overview": [market_overview],
            "market_sector_scan": market_rows,
            "hot_board_front_core": hot_board_front_core_rows,
            "candidate_scores": candidates,
            "pullback_setups": pullback_rows,
            "watchlist_portfolio_actions": handling_rows,
            "portfolio_extra": portfolio_extra_rows,
            "portfolio_decision_rules": portfolio_decision_rows,
        },
    )
    (args.out / "checkpoint_decision_summary.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
