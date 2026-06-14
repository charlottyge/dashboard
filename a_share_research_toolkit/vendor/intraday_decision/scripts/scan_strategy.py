#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import decision_summary
import scan_1030 as core


CHECKPOINT = "14:20"
DEFAULT_OUT = Path(f"scan_strategy_{core.TODAY}")
DEFAULT_EXPORT_ROOT = Path("/Users/char/Desktop/04 investment/tool/intraday_exports") / core.TODAY
MAX_FLOAT_SHARES = 500_000_000
ALLOWED_STRATEGIES = {
    "首板次日突破昨日高点不涨停",
    "首板次日高开高走阳线不涨停",
    "首板次日缩量回踩",
    "首板次日低开高走阳线不涨停",
}
STRATEGY_FIELD_AVAILABILITY_FIELDS = [
    "时间",
    "策略",
    "股票",
    "当前涨幅%",
    "当前价",
    "成交额",
    "换手率%",
    "昨日涨幅%",
    "昨日成交量",
    "今日成交量",
    "量比",
    "昨日是否涨停",
    "昨日高点",
    "今日是否突破昨日高点",
    "今日是否涨停",
    "流通股本",
    "选择原因",
    "匹配板块",
    "板块类型",
    "板块排名",
    "板块涨幅%",
    "板块评分_close",
    "板块评分_high",
    "板块评分_综合",
    "板块模型状态",
    "板块评分原因",
    "匹配板块列表",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A-share strategy-category scanner")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--checkpoint", default=CHECKPOINT)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-workers", type=int, default=18)
    parser.add_argument("--max-float-shares", type=float, default=MAX_FLOAT_SHARES, help="Strict max float shares for strategy candidates")
    return parser.parse_args()


def f(value: Any) -> float:
    return float(value or 0)


def pct(now: float, prev: float) -> float:
    return (now / prev - 1) * 100 if prev else 0.0


def limit_threshold(symbol: str) -> float:
    if symbol.startswith("bj"):
        return 29.5
    if symbol.startswith(("sz300", "sh688")):
        return 19.5
    return 9.5


def limit_close(symbol: str, row: dict[str, Any], prev: dict[str, Any]) -> bool:
    close = f(row["close"])
    high = f(row["high"])
    return pct(close, f(prev["close"])) >= limit_threshold(symbol) and high > 0 and abs(close / high - 1) <= 0.001


def ma(rows: list[dict[str, Any]], i: int, n: int) -> float:
    if i - n + 1 < 0:
        return 0.0
    return sum(f(row["close"]) for row in rows[i - n + 1 : i + 1]) / n


def avg_volume(rows: list[dict[str, Any]], i: int, n: int) -> float:
    if i - n < 0:
        return 0.0
    return sum(f(row["volume"]) for row in rows[i - n : i]) / n


def lowest(rows: list[dict[str, Any]], i: int, n: int) -> float:
    if i - n < 0:
        return 0.0
    return min(f(row["low"]) for row in rows[i - n : i])


def highest_level(rows: list[dict[str, Any]], i: int) -> str:
    current_high = f(rows[i]["high"])
    if not current_high:
        return "unavailable"
    matched = []
    for days in (5, 10, 20, 60):
        start = max(0, i - days + 1)
        if i - start + 1 < min(days, len(rows)):
            continue
        window_high = max(f(row["high"]) for row in rows[start : i + 1])
        if current_high >= window_high:
            matched.append(days)
    if matched:
        return f"{max(matched)}日内最高点"
    return "未创5日内最高点"


def candle(row: dict[str, Any], prev: dict[str, Any]) -> dict[str, float | bool]:
    open_ = f(row["open"])
    high = f(row["high"])
    low = f(row["low"])
    close = f(row["close"])
    return {
        "pct": pct(close, f(prev["close"])),
        "open_pct": pct(open_, f(prev["close"])),
        "body_pct": pct(close, open_),
        "pos": (close - low) / (high - low) if high != low else 1.0,
        "drawdown": (close / high - 1) * 100 if high else 0.0,
        "range_pct": pct(high, low),
        "bull": close > open_,
    }


def today_bar_from_quote(quote: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": core.TODAY,
        "open": core.num(quote.get("open"), 0) or 0,
        "high": core.num(quote.get("high"), 0) or 0,
        "low": core.num(quote.get("low"), 0) or 0,
        "close": core.num(quote.get("trade"), 0) or 0,
        "volume": core.num(quote.get("volume"), 0) or 0,
    }


def float_shares_from_quote(quote: dict[str, Any]) -> tuple[float | None, str]:
    price = core.num(quote.get("trade"), 0) or core.num(quote.get("close"), 0) or 0
    nmc = core.num(quote.get("nmc"), 0) or 0
    if price <= 0:
        return None, "当前价不可用，无法用流通市值推算流通股"
    if nmc <= 0:
        return None, "流通市值字段不可用，无法验证流通股"
    shares = nmc * 10_000 / price
    return shares, "用Sina nmc流通市值(万元)/当前价推算"


def build_signal_rows(symbol: str, code: str, name: str, rows: list[dict[str, Any]], i: int) -> list[dict[str, Any]]:
    row = rows[i]
    prev = rows[i - 1]
    prev2 = rows[i - 2]
    c = candle(row, prev)
    close = f(row["close"])
    high = f(row["high"])
    low = f(row["low"])
    open_ = f(row["open"])
    volume = f(row["volume"])
    prev_volume = f(prev["volume"])
    vol_yday = volume / prev_volume if prev_volume else 0.0
    vol5 = avg_volume(rows, i, 5)
    vol5_ratio = volume / vol5 if vol5 else 0.0
    ma5 = ma(rows, i, 5)
    ma10 = ma(rows, i, 10)
    prior10_low = lowest(rows, i, 10)
    day1_limit_close = limit_close(symbol, prev, prev2)
    day2_limit_close = limit_close(symbol, row, prev)

    base = {
        "时间": CHECKPOINT,
        "股票": f"{name} {code}",
        "日期": row["date"],
        "当前价": round(close, 3),
        "当前涨幅%": round(c["pct"], 3),
        "开盘涨幅%": round(c["open_pct"], 3),
        "成交量/昨日": round(vol_yday, 3),
        "成交量/5日均量": round(vol5_ratio, 3),
        "高点回撤%": round(c["drawdown"], 3),
        "日内位置%": round(float(c["pos"]) * 100, 1),
        "MA5": round(ma5, 3),
        "MA10": round(ma10, 3),
        "昨日涨停收盘": day1_limit_close,
        "今日涨停收盘": day2_limit_close,
        "是多少日内最高点": highest_level(rows, i),
    }
    out: list[dict[str, Any]] = []

    def add(strategy: str, reason: str) -> None:
        item = dict(base)
        item["策略"] = strategy
        item["命中原因"] = reason
        out.append(item)

    if day1_limit_close:
        if not day2_limit_close and close > f(prev["high"]) and bool(c["bull"]) and float(c["pos"]) >= 0.7:
            add("首板次日突破昨日高点不涨停", "昨天涨停收盘；今天不涨停；当前价/收盘价突破昨日高点；阳线；日内位置>=70%")
        if not day2_limit_close and c["open_pct"] > 0 and bool(c["bull"]) and c["pct"] > 0 and float(c["pos"]) >= 0.65 and c["drawdown"] >= -3:
            add("首板次日高开高走阳线不涨停", "昨天涨停收盘；今天不涨停；高开；阳线；收红；日内位置>=65%；高点回撤<=3%")
        if -4 <= c["pct"] <= 2 and vol_yday <= 0.8 and close >= ma5 and c["drawdown"] >= -5:
            add("首板次日缩量回踩", "昨天涨停收盘；今天涨跌幅-4%到+2%；量<=昨日80%；收在MA5上；高点回撤<=5%")
        if not day2_limit_close and c["open_pct"] < 0 and bool(c["bull"]) and c["pct"] >= -1 and float(c["pos"]) >= 0.65 and c["drawdown"] >= -3:
            add("首板次日低开高走阳线不涨停", "昨天涨停收盘；今天不涨停；低开；阳线；日内位置>=65%；高点回撤<=3%")

    if c["open_pct"] < -1 and close > f(prev["close"]) and bool(c["bull"]) and float(c["pos"]) >= 0.75 and vol5_ratio >= 1.0:
        add("低开翻红强承接", "低开超过1%；收盘翻红；阳线；日内位置>=75%；量>=5日均量")

    if close >= prior10_low * 1.08 and c["open_pct"] > 0 and bool(c["bull"]) and c["pct"] >= 3 and float(c["pos"]) >= 0.75 and vol5_ratio >= 1.2:
        add("阶段低位放量阳线启动", "当前价较近10日低点至少+8%；高开；阳线；涨幅>=3%；日内位置>=75%；量>=5日均量1.2倍")

    return out


def evaluate_quote(quote: dict[str, Any]) -> list[dict[str, Any]]:
    symbol = str(quote.get("symbol") or "")
    if not symbol:
        return []
    code = core.code_for_symbol(symbol)
    name = str(quote.get("name") or "")
    rows = core.fetch_daily(symbol, datalen=75)
    if len(rows) < 15:
        return []
    if rows[-1].get("date") != core.TODAY:
        rows.append(today_bar_from_quote(quote))
    result = build_signal_rows(symbol, code, name, rows, len(rows) - 1)
    float_shares, source = float_shares_from_quote(quote)
    for row in result:
        row["流通股(亿)"] = round(float_shares / 100_000_000, 3) if float_shares is not None else ""
        row["流通股过滤"] = "unavailable" if float_shares is None else ("pass" if float_shares <= MAX_FLOAT_SHARES else "exclude")
        row["过滤说明"] = source
    return result


def split_by_float_share_filter(rows: list[dict[str, Any]], max_float_shares: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    passed: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    for row in rows:
        float_shares_100m = core.num(row.get("流通股(亿)"))
        if float_shares_100m is None:
            row["流通股过滤"] = "unavailable"
            row["过滤说明"] = row.get("过滤说明") or "流通股不可用，严格筛选主表排除"
            unavailable.append(row)
            continue
        float_shares = float_shares_100m * 100_000_000
        if float_shares <= max_float_shares:
            row["流通股过滤"] = "pass"
            row["过滤说明"] = f"流通股 {float_shares_100m:.3f}亿 <= {max_float_shares / 100_000_000:.1f}亿"
            passed.append(row)
        else:
            row["流通股过滤"] = "exclude"
            row["过滤说明"] = f"流通股 {float_shares_100m:.3f}亿 > {max_float_shares / 100_000_000:.1f}亿"
            excluded.append(row)
    return passed, excluded, unavailable


def filter_allowed_strategies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("策略") or "") in ALLOWED_STRATEGIES]


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def load_board_scores(out: Path) -> dict[str, dict[str, dict[str, Any]]]:
    candidates = [
        out.parent / "sector_rotation_model_60d" / "latest_board_signals.csv",
        DEFAULT_EXPORT_ROOT / "sector_rotation_model_60d" / "latest_board_signals.csv",
    ]
    candidates.extend(sorted(DEFAULT_EXPORT_ROOT.parent.glob("*/sector_rotation_model_60d/latest_board_signals.csv"), reverse=True))
    for path in candidates:
        rows = read_csv(path)
        if rows:
            return {
                "by_code": {str(row.get("code") or ""): row for row in rows},
                "by_name": {str(row.get("board") or ""): row for row in rows},
            }
    return {"by_code": {}, "by_name": {}}


def board_member_symbols(sector: core.Sector) -> set[str]:
    symbols: set[str] = set()
    if sector.source.startswith("eastmoney"):
        try:
            payload = core.fetch_json(
                core.EASTMONEY_BOARD_RANK,
                {
                    "pn": 1,
                    "pz": 500,
                    "po": 1,
                    "np": 1,
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                    "fltt": 2,
                    "invt": 2,
                    "fid": "f3",
                    "fs": f"b:{sector.code}",
                    "fields": "f12,f14,f2,f3",
                },
            )
            for row in (payload.get("data") or {}).get("diff") or []:
                if row.get("f12"):
                    symbols.add(core.symbol_for_code(str(row.get("f12"))))
        except Exception:
            return set()
    else:
        try:
            rows = core.fetch_json(
                core.SINA_QUOTES,
                {
                    "page": 1,
                    "num": 500,
                    "sort": "changepercent",
                    "asc": 0,
                    "node": sector.code,
                    "symbol": "",
                    "_s_r_a": "page",
                },
            )
            for row in rows:
                if row.get("symbol"):
                    symbols.add(str(row.get("symbol")))
        except Exception:
            return set()
    return symbols


def enrich_strategy_rows(rows: list[dict[str, Any]], out: Path) -> tuple[list[dict[str, Any]], list[core.Sector]]:
    if not rows:
        return rows, []
    selected_symbols = {core.symbol_for_code(str(row["股票"]).split()[-1]) for row in rows if row.get("股票")}
    board_scores = load_board_scores(out)
    sectors = core.fetch_sectors()
    matches: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in selected_symbols}
    for sector in sectors:
        symbols = board_member_symbols(sector)
        if not symbols:
            continue
        score = board_scores["by_code"].get(sector.code) or board_scores["by_name"].get(sector.name, {})
        for symbol in selected_symbols & symbols:
            matches.setdefault(symbol, []).append(
                {
                    "board": sector.name,
                    "kind": sector.kind,
                    "code": sector.code,
                    "rank": sector.rank,
                    "pct": sector.pct,
                    "close_score": core.num(score.get("close_model_score"), ""),
                    "high_score": core.num(score.get("high_model_score"), ""),
                    "combined_score": core.num(score.get("combined_model_score"), ""),
                    "status": score.get("status", ""),
                    "reason": score.get("model_reason", ""),
                }
            )
    for row in rows:
        symbol = core.symbol_for_code(str(row["股票"]).split()[-1])
        items = matches.get(symbol, [])
        items.sort(key=lambda item: (float(item["combined_score"] or 0), -float(item["rank"] or 999)), reverse=True)
        best = items[0] if items else {}
        row["匹配板块"] = best.get("board", "")
        row["板块类型"] = best.get("kind", "")
        row["板块排名"] = best.get("rank", "")
        row["板块涨幅%"] = round(float(best.get("pct", 0) or 0), 3) if best else ""
        row["板块评分_close"] = best.get("close_score", "")
        row["板块评分_high"] = best.get("high_score", "")
        row["板块评分_综合"] = best.get("combined_score", "")
        row["板块模型状态"] = best.get("status", "")
        row["板块评分原因"] = best.get("reason", "")
        row["匹配板块列表"] = "；".join(item["board"] for item in items[:5])
    return rows, sectors


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    print("fetch quotes")
    quotes = core.fetch_quotes(limit=args.limit)
    print(f"quotes {len(quotes)}")
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {executor.submit(evaluate_quote, quote): quote for quote in quotes}
        for done, future in enumerate(as_completed(futures), start=1):
            quote = futures[future]
            symbol = str(quote.get("symbol") or "")
            try:
                rows.extend(future.result())
            except Exception as exc:
                errors.append({"symbol": symbol, "code": core.code_for_symbol(symbol), "name": str(quote.get("name") or ""), "error": str(exc)})
            if done % 500 == 0:
                print(f"evaluated {done}/{len(quotes)}")

    rows.sort(key=lambda item: (str(item["策略"]), -float(item["当前涨幅%"]), str(item["股票"])))
    raw_candidate_count = len(rows)
    rows = filter_allowed_strategies(rows)
    strategy_filtered_count = raw_candidate_count - len(rows)
    rows, excluded_rows, unavailable_rows = split_by_float_share_filter(rows, args.max_float_shares)
    summary_by_strategy: dict[str, int] = {}
    for row in rows:
        summary_by_strategy[str(row["策略"])] = summary_by_strategy.get(str(row["策略"]), 0) + 1
    summary_rows = [{"时间": CHECKPOINT, "策略": key, "数量": value} for key, value in sorted(summary_by_strategy.items())]
    rows, sectors = enrich_strategy_rows(rows, args.out)
    rows = decision_summary.enrich_strategy_candidates(rows)

    write_csv(args.out / "strategy_candidates.csv", rows)
    write_csv(args.out / "strategy_candidates_float_excluded.csv", excluded_rows)
    write_csv(args.out / "strategy_candidates_float_unavailable.csv", unavailable_rows)
    write_csv(args.out / "strategy_summary.csv", summary_rows)
    write_csv(args.out / "errors.csv", errors)
    field_availability = core.summarize_field_availability(rows, STRATEGY_FIELD_AVAILABILITY_FIELDS)
    sector_source_chain = sorted({sector.source for sector in sectors if sector.source})
    fallback_used = any(sector.fallback_used for sector in sectors)
    fetch_attempts = max((sector.fetch_attempts for sector in sectors), default=1)
    fallback_reason = next((sector.fallback_reason for sector in sectors if sector.fallback_reason), "")
    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "checkpoint": args.checkpoint,
        "data_timestamp": core.TODAY,
        "quote_count": len(quotes),
        "evaluated_count": len(quotes) - len(errors),
        "strategy_count": len(summary_by_strategy),
        "candidate_event_count": len(rows),
        "unique_stock_count": len({row["股票"] for row in rows}),
        "allowed_strategies": sorted(ALLOWED_STRATEGIES),
        "strategy_filtered_count": strategy_filtered_count,
        "float_share_filter_enabled": True,
        "max_float_shares": args.max_float_shares,
        "float_excluded_count": len(excluded_rows),
        "float_unavailable_count": len(unavailable_rows),
        "error_count": len(errors),
        "strategies": summary_by_strategy,
        "source_chain": ["Sina quote center", "Sina daily KLine"] + sector_source_chain + ["sector_rotation_model_60d latest_board_signals"],
        "sector_source_chain": sector_source_chain,
        "quote_source_chain": ["Sina quote center"],
        "fallback_used": fallback_used,
        "fetch_attempts": fetch_attempts,
        "fallback_reason": fallback_reason,
        "usable_fields": field_availability["usable_fields"],
        "unusable_fields": field_availability["unusable_fields"],
        "field_availability": field_availability,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    decision = decision_summary.build_strategy_decision_summary(
        checkpoint=args.checkpoint,
        summary=summary,
        rows=rows,
        excluded_rows=excluded_rows,
        unavailable_rows=unavailable_rows,
    )
    (args.out / "checkpoint_decision_summary.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
