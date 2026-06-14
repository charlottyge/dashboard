#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import scan_1030 as core
import decision_summary


SCRIPT_DIR = Path(__file__).resolve().parent


def parse_common_args(description: str, checkpoint: str, default_dir_name: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--pool", choices=["all-a", "watchlist"], default="all-a")
    parser.add_argument("--watchlist", type=Path, help="Optional CSV with code/name/symbol columns")
    parser.add_argument("--portfolio", type=Path, help="Optional portfolio CSV")
    parser.add_argument("--investment-dir", type=Path, default=core.DEFAULT_INVESTMENT_DIR)
    parser.add_argument("--out", type=Path, default=Path(f"{default_dir_name}_{core.TODAY}"))
    parser.add_argument("--checkpoint", default=checkpoint)
    parser.add_argument("--previous-root", type=Path, help="Directory containing prior checkpoint output folders")
    parser.add_argument("--top-sector-rank", type=int, default=10)
    parser.add_argument("--pullback-sector-rank", type=int, default=15)
    parser.add_argument("--min-amount", type=float, default=500_000_000)
    parser.add_argument("--min-free-market-cap", type=float, default=0)
    parser.add_argument("--max-workers", type=int, default=18)
    parser.add_argument("--limit", type=int, default=0, help="Optional symbol limit for testing")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def previous_root(args: argparse.Namespace) -> Path:
    if args.previous_root:
        return args.previous_root
    if args.out.name.startswith("scan_"):
        return args.out.parent
    return Path.cwd()


def prior_candidates(args: argparse.Namespace, checkpoint_dir: str = "scan_1030") -> list[dict[str, Any]]:
    return read_csv(previous_root(args) / checkpoint_dir / "candidate_scores.csv")


def prior_sector_rows(args: argparse.Namespace, checkpoint_dir: str = "scan_1030") -> list[dict[str, Any]]:
    return read_csv(previous_root(args) / checkpoint_dir / "market_sector_scan.csv")


def prior_candidate_score(row: dict[str, Any]) -> float:
    return pct_float(row.get("分数"), 0)


def prior_candidate_source(row: dict[str, Any]) -> str:
    return str(row.get("来源(缩量回踩/放量突破/watchlist/portfolio)") or row.get("来源(突破/回踩/watchlist/portfolio)") or "")


def is_prior_main_candidate(row: dict[str, Any], threshold: float = 85) -> bool:
    source = prior_candidate_source(row)
    return "放量突破" in source or "缩量回踩" in source or prior_candidate_score(row) >= threshold


def load_universe(args: argparse.Namespace, include_intraday_eval: bool = True) -> dict[str, Any]:
    default_watchlist = args.investment_dir / "watchlist.md"
    default_portfolio = args.investment_dir / "portfolio.md"
    watch_meta = core.parse_watchlist_markdown(default_watchlist)
    plan_meta = core.parse_plan_rows_from_watchlist(default_watchlist)
    tech_sector_rows = core.parse_tech_sector_branches(default_watchlist)
    tech_sector_symbols = core.tech_sector_symbols(tech_sector_rows)
    portfolio_meta = core.parse_portfolio_markdown(default_portfolio)
    watch_symbols_from_md = {core.symbol_for_code(code) for code in watch_meta}
    portfolio_symbols_from_md = {core.symbol_for_code(code) for code in portfolio_meta}
    portfolio_codes = set(portfolio_meta)
    csv_watch_symbols = core.read_symbol_pool(args.watchlist) if args.watchlist else set()
    watch_symbols = watch_symbols_from_md | csv_watch_symbols
    required_symbols = watch_symbols | portfolio_symbols_from_md | tech_sector_symbols
    pool_symbols = watch_symbols if args.pool == "watchlist" else None

    print("fetch sectors")
    sectors = core.fetch_sectors()
    print("fetch sector members")
    sector_by_symbol, sector_stats = core.fetch_sector_members(sectors)
    print("fetch quotes")
    quotes = core.fetch_quotes(pool_symbols=pool_symbols, limit=args.limit)
    quotes = ensure_required_quotes(quotes, required_symbols)
    print(f"quotes {len(quotes)}")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    daily_by_symbol: dict[str, list[dict[str, Any]]] = {}
    if include_intraday_eval:
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = {}
            for quote in quotes:
                symbol = str(quote.get("symbol") or "")
                futures[executor.submit(lambda s=symbol: (s, core.fetch_daily(s), core.fetch_intraday(s)))] = quote
            for done, future in enumerate(as_completed(futures), start=1):
                quote = futures[future]
                symbol = str(quote.get("symbol") or "")
                try:
                    _, daily_rows, intraday_rows = future.result()
                    daily_by_symbol[symbol] = daily_rows
                    sector = sector_by_symbol.get(symbol)
                    evaluated = core.evaluate_stock(
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
                    errors.append({"symbol": symbol, "code": core.code_for_symbol(symbol), "name": str(quote.get("name") or ""), "error": str(exc)})
                if done % 500 == 0:
                    print(f"evaluated {done}/{len(quotes)}")

    return {
        "args": args,
        "sectors": sectors,
        "sector_by_symbol": sector_by_symbol,
        "sector_stats": sector_stats,
        "quotes": quotes,
        "results": results,
        "errors": errors,
        "daily_by_symbol": daily_by_symbol,
        "tech_sector_rows": tech_sector_rows,
        "tech_sector_daily_rows": core.build_tech_sector_daily_rows(tech_sector_rows, daily_by_symbol),
        "tech_sector_stock_map": core.build_tech_sector_stock_map(tech_sector_rows),
        "watch_meta": watch_meta,
        "plan_meta": plan_meta,
        "portfolio_meta": portfolio_meta,
        "watch_symbols": watch_symbols,
        "portfolio_codes": portfolio_codes,
    }


def ensure_required_quotes(quotes: list[dict[str, Any]], required_symbols: set[str]) -> list[dict[str, Any]]:
    existing_symbols = {str(row.get("symbol") or "") for row in quotes}
    missing_required = required_symbols - existing_symbols
    if missing_required:
        try:
            fetched_rows = core.fetch_sina_hq_quotes(missing_required)
            if fetched_rows:
                quotes.extend(fetched_rows)
                existing_symbols = {str(row.get("symbol") or "") for row in quotes}
                missing_required = required_symbols - existing_symbols
        except Exception as exc:
            print(f"warning: Sina HQ required quote fallback unavailable: {exc}")
    for symbol in sorted(missing_required):
        fetched = None
        try:
            fetched = core.fetch_json(
                core.SINA_QUOTES,
                {
                    "page": 1,
                    "num": 1,
                    "sort": "changepercent",
                    "asc": 0,
                    "node": "hs_a",
                    "symbol": symbol,
                    "_s_r_a": "page",
                },
                retries=6,
                timeout=30,
            )
        except Exception as exc:
            print(f"warning: required quote {symbol} unavailable: {exc}")
            try:
                rows = core.fetch_tencent_quotes({symbol})
                if rows:
                    quotes.extend(rows)
            except Exception as tencent_exc:
                print(f"warning: required quote {symbol} Tencent fallback unavailable: {tencent_exc}")
            continue
        if fetched and isinstance(fetched, list):
            for row in fetched:
                if str(row.get("symbol") or "") == symbol:
                    quotes.append(row)
                    break
    return quotes


def quote_by_code(quotes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {core.code_for_symbol(str(row.get("symbol") or "")): row for row in quotes if row.get("symbol")}


def watch_portfolio_items(context: dict[str, Any]) -> list[dict[str, str]]:
    watch_meta = context.get("watch_meta", {})
    portfolio_meta = context.get("portfolio_meta", {})
    watch_symbols = context.get("watch_symbols", set())
    portfolio_codes = context.get("portfolio_codes", set())
    items: list[dict[str, str]] = []
    for code in sorted({core.code_for_symbol(symbol) for symbol in watch_symbols} | set(portfolio_codes)):
        meta = portfolio_meta.get(code) or watch_meta.get(code, {})
        items.append(
            {
                "code": code,
                "symbol": core.symbol_for_code(code),
                "name": str(meta.get("name", "")),
                "source": "portfolio" if code in portfolio_codes else "watchlist",
            }
        )
    return items


def sector_amount_ranks(sectors: list[core.Sector]) -> dict[str, int]:
    return {sector.code: rank for rank, sector in enumerate(sorted(sectors, key=lambda item: item.amount, reverse=True), start=1)}


def standard_market_overview(args: argparse.Namespace, context: dict[str, Any]) -> list[dict[str, Any]]:
    row = core.fetch_market_overview(context.get("quotes", []))
    row["时间"] = args.checkpoint
    return [row]


def standard_market_sector_scan(args: argparse.Namespace, context: dict[str, Any]) -> list[dict[str, Any]]:
    rows = core.build_market_rows(context.get("sectors", []), context.get("sector_stats", {}))
    for row in rows:
        row["时间"] = args.checkpoint
    return rows


def hot_board_front_core(args: argparse.Namespace, context: dict[str, Any], limit: int = 5, front_count: int = 3) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    results = context.get("results", [])
    sectors = context.get("sectors", [])[:limit]
    for sector in sectors:
        members = [row for row in results if row.get("sector") == sector.name]
        members.sort(key=lambda row: (pct_float(row.get("pct"), -999), pct_float(row.get("amount_1030"), 0)), reverse=True)
        amount_sorted = sorted(members, key=lambda row: pct_float(row.get("amount_1030"), 0), reverse=True)
        core_pool = [row for row in amount_sorted if row.get("role_type") == "中军"] or amount_sorted
        core_row = core_pool[0] if core_pool else {}
        front_pool = [row for row in members if row.get("code") != core_row.get("code")]
        front_rows = front_pool[:front_count]
        row = {
            "时间": args.checkpoint,
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
            "中军VWAP": vwap_text(core_row) if core_row else "unavailable",
            "数据状态": "ok" if members else "unavailable: no evaluated members for this board",
        }
        for index in range(front_count):
            front = front_rows[index] if index < len(front_rows) else {}
            prefix = f"前排{index + 1}"
            row[f"{prefix}股票"] = f"{front.get('name', '')} {front.get('code', '')}".strip() if front else ""
            row[f"{prefix}角色"] = front.get("role_type", "") if front else ""
            row[f"{prefix}涨幅"] = front.get("pct", "") if front else ""
            row[f"{prefix}成交额"] = front.get("amount_1030", "") if front else ""
            row[f"{prefix}VWAP"] = vwap_text(front) if front else "unavailable"
        if not members and getattr(sector, "leader_name", ""):
            row["前排1股票"] = sector.leader_name
            row["前排1涨幅"] = round(sector.leader_pct, 3)
            row["数据状态"] = "partial: board leader only"
        rows.append(row)
    return rows


def add_standard_market_tables(args: argparse.Namespace, context: dict[str, Any], tables: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    tables.setdefault("market_overview", standard_market_overview(args, context))
    tables.setdefault("market_sector_scan", standard_market_sector_scan(args, context))
    tables.setdefault("hot_board_front_core", hot_board_front_core(args, context))
    return tables


def bool_cn(value: Any) -> str:
    return "是" if bool(value) else "否"


def vwap_text(row: dict[str, Any]) -> str:
    if row.get("is_above_vwap") == "":
        return "unavailable"
    return "上" if row.get("is_above_vwap") else "下"


def signed_pct_text(value: Any, digits: int = 1) -> str:
    parsed = pct_float(value, 0)
    return f"{parsed:+.{digits}f}%"


def stock_trajectory_text(row: dict[str, Any]) -> str:
    prev_close = pct_float(row.get("prev_close"), 0)
    if prev_close <= 0:
        pct = row.get("pct", "")
        vwap = vwap_text(row)
        if pct == "":
            return "行情未评估。"
        return f"当前 {signed_pct_text(pct)}，VWAP {vwap}方。"

    open_price = pct_float(row.get("open"), 0)
    high = pct_float(row.get("high"), 0)
    low = pct_float(row.get("low"), 0)
    price = pct_float(row.get("price"), 0)
    if min(open_price, high, low, price) <= 0:
        return "行情未评估。"

    open_pct = (open_price / prev_close - 1) * 100
    high_pct = (high / prev_close - 1) * 100
    low_pct = (low / prev_close - 1) * 100
    current_pct = pct_float(row.get("pct"), (price / prev_close - 1) * 100)
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
    drawdown = pct_float(row.get("drawdown_from_high_pct"), 0)
    if drawdown < -3:
        parts.append(f"较高点回撤 {signed_pct_text(drawdown)}")
    return "，".join(parts) + "。"


def unavailable_trajectory_text() -> str:
    return "行情未评估。"


def pct_float(value: Any, default: float = 0.0) -> float:
    parsed = core.num(value)
    return parsed if parsed is not None else default


def amount_delta_text(current_amount: Any, previous_amount: Any) -> str:
    current = pct_float(current_amount, 0)
    previous = pct_float(previous_amount, 0)
    if current <= 0 or previous <= 0:
        return "unavailable"
    return f"{(current / previous - 1) * 100:.1f}%"


def build_summary(args: argparse.Namespace, context: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    sectors = context.get("sectors", [])
    fallback_used = any(getattr(sector, "fallback_used", False) for sector in sectors)
    fetch_attempts = max((int(getattr(sector, "fetch_attempts", 1) or 1) for sector in sectors), default=1)
    fallback_reason = next((str(getattr(sector, "fallback_reason", "")) for sector in sectors if getattr(sector, "fallback_reason", "")), "")
    sector_source_chain = sorted({str(getattr(sector, "source", "")) for sector in sectors if getattr(sector, "source", "")})
    quote_source_chain = sorted({str(row.get("source") or "sina_quote_center") for row in context.get("quotes", [])})
    field_availability = core.summarize_field_availability(
        context.get("results", []),
        core.INTRADAY_FIELD_AVAILABILITY_FIELDS,
    )
    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "checkpoint": args.checkpoint,
        "data_timestamp": core.TODAY,
        "stock_pool": args.pool,
        "source_chain": sector_source_chain + quote_source_chain + ["Sina daily KLine", "Sina CN_MinlineService"],
        "sector_source_chain": sector_source_chain,
        "quote_source_chain": quote_source_chain,
        "fallback_used": fallback_used,
        "fetch_attempts": fetch_attempts,
        "fallback_reason": fallback_reason,
        "quote_count": len(context.get("quotes", [])),
        "evaluated_count": len(context.get("results", [])),
        "watchlist_count": len(context.get("watch_symbols", [])),
        "portfolio_count": len(context.get("portfolio_meta", [])),
        "tech_sector_branch_count": len({row.get("branch") for row in context.get("tech_sector_rows", []) if row.get("branch")}),
        "tech_sector_target_count": len(context.get("tech_sector_rows", [])),
        "tech_sector_resolved_count": sum(1 for row in context.get("tech_sector_rows", []) if row.get("status") == "resolved"),
        "tech_sector_daily_row_count": len(context.get("tech_sector_daily_rows", [])),
        "error_count": len(context.get("errors", [])),
        "usable_fields": field_availability["usable_fields"],
        "unusable_fields": field_availability["unusable_fields"],
        "field_availability": field_availability,
        "known_limits": [
            "Auction/opening fields may be approximated from the live quote snapshot when historical auction ticks are unavailable",
            "volume_ratio_vs_5d_same_time is approximated from daily five-day average when historical same-time intraday bars are unavailable",
            "yesterday_hot_sector and exact core/front-row classification are rule-based approximations",
        ],
    }
    summary["_tech_sector_daily_rows"] = context.get("tech_sector_daily_rows", [])
    summary["_tech_sector_stock_map"] = context.get("tech_sector_stock_map", [])
    if extra:
        summary.update(extra)
    return summary


def write_outputs(args: argparse.Namespace, tables: dict[str, list[dict[str, Any]]], summary: dict[str, Any], errors: list[dict[str, str]]) -> None:
    args.out.mkdir(parents=True, exist_ok=True)
    tech_sector_daily_rows = summary.pop("_tech_sector_daily_rows", [])
    tech_sector_stock_map = summary.pop("_tech_sector_stock_map", [])
    for name, rows in tables.items():
        core.write_csv(args.out / f"{name}.csv", rows)
    if tech_sector_daily_rows:
        core.write_csv(args.out / "tech_sector_daily_k.csv", tech_sector_daily_rows)
    if tech_sector_stock_map:
        core.write_csv(args.out / "tech_sector_stock_map.csv", tech_sector_stock_map)
    core.write_csv(args.out / "errors.csv", errors, ["symbol", "code", "name", "error"])
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    decision = decision_summary.build_checkpoint_decision_summary(
        checkpoint=args.checkpoint,
        summary=summary,
        tables=tables,
    )
    (args.out / "checkpoint_decision_summary.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
