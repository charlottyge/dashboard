#!/usr/bin/env python3
from __future__ import annotations

import intraday_common as common
import scan_1030 as core


CHECKPOINT = "9:25"


def open_pct(row: dict) -> float | str:
    open_price = core.num(row.get("open"))
    prev_close = core.num(row.get("settlement"))
    if not open_price or not prev_close:
        return ""
    return round((open_price / prev_close - 1) * 100, 3)


def open_trajectory_text(quote: dict, sector_pct: float | str) -> str:
    stock_open_pct = open_pct(quote) if quote else ""
    if stock_open_pct == "":
        return "行情未评估。"
    side = "高开" if float(stock_open_pct) > 0.5 else "低开" if float(stock_open_pct) < -0.5 else "平开"
    text = f"{side} {float(stock_open_pct):+.1f}%"
    if sector_pct != "":
        text += f"，板块开盘 {float(sector_pct):+.1f}%"
    return text + "。"


def main() -> int:
    args = common.parse_common_args("9:25 A-share opening auction scan", CHECKPOINT, "scan_0925")
    context = common.load_universe(args, include_intraday_eval=False)
    sectors = context["sectors"]
    sector_stats = context["sector_stats"]
    sector_by_symbol = context["sector_by_symbol"]
    quotes = context["quotes"]
    watch_symbols = context["watch_symbols"]
    portfolio_codes = context["portfolio_codes"]
    watch_meta = context["watch_meta"]
    portfolio_meta = context["portfolio_meta"]
    amount_ranks = common.sector_amount_ranks(sectors)

    market = core.fetch_market_overview(quotes, args)
    market_temperature = [
        {
            "时间": CHECKPOINT,
            **{f"{label}开盘": market.get(label, "") for label in core.INDEX_SYMBOLS.values()},
            "涨停数": str(market.get("涨停/跌停", "")).split("/")[0] if market.get("涨停/跌停") else "",
            "跌停数": str(market.get("涨停/跌停", "")).split("/")[1] if "/" in str(market.get("涨停/跌停", "")) else "",
            "数据说明": "open fields from live quote snapshot",
        }
    ]

    selected_sectors = sectors[:10] + list(reversed(sectors[-5:]))
    sector_strength = []
    for sector in selected_sectors:
        sector_strength.append(
            {
                "时间": CHECKPOINT,
                "板块": sector.name,
                "板块来源": sector.source,
                "板块类型": sector.kind,
                "fallback_used": sector.fallback_used,
                "fetch_attempts": sector.fetch_attempts,
                "fallback_reason": sector.fallback_reason,
                "开盘涨幅": round(sector.pct, 3),
                "开盘成交额排名": amount_ranks.get(sector.code, ""),
                "昨日是否强线": "unavailable",
                "代表股": sector.leader_name,
            }
        )

    yesterday_names = ["半导体", "有色", "电池", "光通信", "AI软件"]
    yesterday_lines = []
    for name in yesterday_names:
        matched = next((sector for sector in sectors if name in sector.name), None)
        yesterday_lines.append(
            {
                "时间": CHECKPOINT,
                "昨日强线": name,
                "板块": matched.name if matched else "",
                "开盘表现": round(matched.pct, 3) if matched else "unavailable",
                "排名": matched.rank if matched else "",
            }
        )

    by_code = common.quote_by_code(quotes)
    wp_rows = []
    for symbol in sorted(watch_symbols | {core.symbol_for_code(code) for code in portfolio_codes}):
        code = core.code_for_symbol(symbol)
        quote = by_code.get(code, {})
        sector = sector_by_symbol.get(symbol)
        source = "portfolio" if code in portfolio_codes else "watchlist"
        stock_open_pct = open_pct(quote) if quote else ""
        sector_pct = round(sector.pct, 3) if sector else ""
        stronger = stock_open_pct != "" and sector_pct != "" and float(stock_open_pct) > float(sector_pct)
        meta = portfolio_meta.get(code) or watch_meta.get(code, {})
        wp_rows.append(
            {
                "时间": CHECKPOINT,
                "股票": f"{meta.get('name') or quote.get('name', '')} {code}".strip(),
                "来源(watchlist/portfolio)": source,
                "走势自然语言": open_trajectory_text(quote, sector_pct),
                "开盘涨幅": stock_open_pct,
                "所属板块": sector.name if sector else "",
                "板块开盘涨幅": sector_pct,
                "是否强于板块": common.bool_cn(stronger) if stock_open_pct != "" and sector_pct != "" else "unavailable",
                "开盘状态": "强于板块" if stronger else "未强于板块",
            }
        )

    tables = {
        "market_overview": common.standard_market_overview(args, context),
        "market_sector_scan": common.standard_market_sector_scan(args, context),
        "hot_board_front_core": common.hot_board_front_core(args, context),
        "market_temperature": market_temperature,
        "sector_strength": sector_strength,
        "yesterday_strong_lines": yesterday_lines,
        "watchlist_portfolio_open": wp_rows,
    }
    summary = common.build_summary(args, context, {"sector_row_count": len(sector_strength), "watchlist_portfolio_row_count": len(wp_rows)})
    common.write_outputs(args, tables, summary, context["errors"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
