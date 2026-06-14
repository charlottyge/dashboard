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

import decision_summary


SINA_QUOTES = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
SINA_KLINE = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
SINA_MINLINE = "https://quotes.sina.cn/cn/api/openapi.php/CN_MinlineService.getMinlineData"
SINA_SECTORS = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
SINA_HQ = "https://hq.sinajs.cn/list=sh000001,sz399006,sh000688"
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
    parser.add_argument("--top-sector-rank", type=int, default=10)
    parser.add_argument("--pullback-sector-rank", type=int, default=15)
    parser.add_argument("--min-amount", type=float, default=500_000_000)
    parser.add_argument("--min-free-market-cap", type=float, default=0)
    parser.add_argument("--max-workers", type=int, default=18)
    parser.add_argument("--limit", type=int, default=0, help="Optional symbol limit for testing")
    return parser.parse_args()


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
        "天赐材料": "002709",
        "云南锗业": "002428",
        "中天科技": "600522",
        "节能风电": "601016",
        "蓝思科技": "300433",
        "浙江新能": "600032",
    }
    holdings: dict[str, dict[str, Any]] = {}
    in_holdings = False
    header: list[str] = []
    for line in text.splitlines():
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
        holdings[code] = {
            "code": code,
            "name": name,
            "shares_total": shares_total,
            "avg_cost": avg_cost,
            "current_snapshot": current_snapshot,
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


def metrics_from_daily(daily: list[dict[str, Any]], base: dict[str, Any]) -> dict[str, Any] | None:
    if len(daily) < 8:
        return None
    today_bar = daily[-1] if daily[-1]["date"] == TODAY else None
    previous = daily[:-1] if today_bar else daily
    if len(previous) < 10:
        return None
    prev5 = previous[-5:]
    prev10 = previous[-10:]
    stage_window = previous[-19:] + [{"high": base["high"]}]
    ma5 = (sum(float(bar["close"]) for bar in previous[-4:]) + base["price"]) / 5
    ma10 = (sum(float(bar["close"]) for bar in previous[-9:]) + base["price"]) / 10
    prev5_high = max(float(bar["high"]) for bar in prev5)
    stage_high = max(float(bar["high"]) for bar in stage_window)
    return {
        "ma5": ma5,
        "ma10": ma10,
        "prev5_high": prev5_high,
        "prev5_high_is_stage_high": abs(prev5_high - stage_high) < 1e-6,
        "recent5_gain_pct": (base["price"] / float(prev5[0]["close"]) - 1) * 100,
        "prev_close": float(previous[-1]["close"]),
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
    checkpoint_row = latest_at_or_before(intraday_rows, args.checkpoint)
    if not checkpoint_row:
        return None
    base = build_base_quote(quote, checkpoint_row)
    if not base:
        return None
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
    base["reclaimed_vwap"] = base["is_above_vwap"] and any(num(row.get("p"), 0) < num(row.get("avg_p"), 0) for row in intraday_rows if str(row.get("m") or "") <= f"{args.checkpoint}:00")
    base["sustained_vwap_break_0945_1030"] = sustained_vwap_break(intraday_rows, "09:45:00", args.checkpoint)
    base["volume_ratio_vs_5d_same_time"] = same_time_volume_ratio(daily, intraday_rows, checkpoint_row)

    daily["distance_to_ma5_pct"] = (price - daily["ma5"]) / daily["ma5"] * 100
    daily["is_new_5d_high"] = price > daily["prev5_high"] and high > daily["prev5_high"]
    daily["reclaimed_ma5"] = price >= daily["ma5"] and low < daily["ma5"]

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
        "ma5": round(daily["ma5"], 3),
        "ma10": round(daily["ma10"], 3),
        "prev5_high": round(daily["prev5_high"], 3),
        "prev5_high_is_stage_high": daily["prev5_high_is_stage_high"],
        "recent5_gain_pct": round(daily["recent5_gain_pct"], 3),
        "distance_to_ma5_pct": round(daily["distance_to_ma5_pct"], 3),
        "drawdown_from_high_pct": round(base["drawdown_from_high_pct"], 3),
        "drawdown_from_high_abs_pct": round(base["drawdown_from_high_abs_pct"], 3),
        "position_in_range": round(base["position_in_range"], 3),
        "is_above_vwap": base["is_above_vwap"],
        "is_above_open": base["is_above_open"],
        "is_new_5d_high": daily["is_new_5d_high"],
        "reclaimed_ma5": daily["reclaimed_ma5"],
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


def fetch_market_overview(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    overview: dict[str, Any] = {
        "时间": CHECKPOINT,
        "上证": "",
        "创业板": "",
        "科创50": "",
        "成交额预估": round(sum(num(row.get("amount"), 0) or 0 for row in quotes), 0),
        "涨跌家数": "",
        "涨停/跌停": "",
    }
    try:
        raw = subprocess.run(
            ["curl", "-fsSL", "-A", "Mozilla/5.0", "-e", "https://finance.sina.com.cn", SINA_HQ],
            check=True,
            capture_output=True,
            timeout=15,
        ).stdout.decode("gbk", "replace")
        index_map = {"sh000001": "上证", "sz399006": "创业板", "sh000688": "科创50"}
        for line in raw.splitlines():
            match = re.match(r"var hq_str_(\w+)=\"(.*)\";", line)
            if not match:
                continue
            symbol, payload = match.groups()
            parts = payload.split(",")
            if len(parts) < 4:
                continue
            close = num(parts[3])
            prev_close = num(parts[2])
            pct = (close / prev_close - 1) * 100 if close and prev_close else None
            overview[index_map.get(symbol, symbol)] = round(pct, 3) if pct is not None else ""
    except Exception as exc:
        overview["指数错误"] = str(exc)
    up = sum(1 for row in quotes if (num(row.get("changepercent"), 0) or 0) > 0)
    down = sum(1 for row in quotes if (num(row.get("changepercent"), 0) or 0) < 0)
    limit_up = sum(1 for row in quotes if is_limit_up(str(row.get("symbol") or ""), num(row.get("changepercent"), 0) or 0))
    limit_down = sum(1 for row in quotes if is_limit_down(str(row.get("symbol") or ""), num(row.get("changepercent"), 0) or 0))
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
    candidates = build_data_packet_candidates(results, watch_symbols, portfolio_codes, watch_meta, portfolio_meta)

    market_overview = fetch_market_overview(quotes)
    market_rows = build_market_rows(sectors, sector_stats)
    hot_board_front_core_rows = build_hot_board_front_core_rows(args.checkpoint, sectors, results)
    extra_portfolio_rows = load_portfolio_rows(args.portfolio)
    portfolio_rows = portfolio_rows_for_actions + extra_portfolio_rows
    handling_rows = build_watchlist_portfolio_rows(results, watch_symbols, portfolio_rows, watch_meta)
    result_by_code = {row["code"]: row for row in results}
    portfolio_extra_rows = build_portfolio_extra_rows(portfolio_meta, plan_meta, result_by_code)
    tech_sector_daily_rows = build_tech_sector_daily_rows(tech_sector_rows, daily_by_symbol)
    tech_sector_stock_map = build_tech_sector_stock_map(tech_sector_rows)

    write_csv(args.out / "market_overview.csv", [market_overview])
    write_csv(args.out / "market_sector_scan.csv", market_rows)
    write_csv(args.out / "hot_board_front_core.csv", hot_board_front_core_rows)
    write_csv(args.out / "candidate_scores.csv", candidates)
    write_csv(args.out / "watchlist_portfolio_actions.csv", handling_rows)
    write_csv(args.out / "portfolio_extra.csv", portfolio_extra_rows)
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
            "watchlist_portfolio_actions": handling_rows,
            "portfolio_extra": portfolio_extra_rows,
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
