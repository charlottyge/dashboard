#!/usr/bin/env python3
from __future__ import annotations

import intraday_common as common
import scan_1030 as core


CHECKPOINT = "15:10"


def read_table(args, folder: str, file_name: str) -> list[dict]:
    return common.read_csv(common.previous_root(args) / folder / file_name)


def code_from_stock(value: str) -> str:
    return value.split()[-1] if value else ""


def main() -> int:
    args = common.parse_common_args("15:10 A-share after-close review", CHECKPOINT, "scan_1510")
    context = common.load_universe(args, include_intraday_eval=True)
    sectors = context["sectors"]
    sector_stats = context["sector_stats"]
    results = context["results"]
    portfolio_meta = context["portfolio_meta"]
    plan_meta = context["plan_meta"]
    prior_1030 = read_table(args, "scan_1030", "candidate_scores.csv")
    prior_1440 = read_table(args, "scan_1440", "candidate_close_confirm.csv")
    prior_0925 = read_table(args, "scan_0925", "watchlist_portfolio_open.csv")

    open_by_code = {code_from_stock(row.get("股票", "")): row for row in prior_0925}
    ten_by_code = {code_from_stock(row.get("股票", "")): row for row in prior_1030}
    close_by_code = {code_from_stock(row.get("股票", "")): row for row in prior_1440}
    result_by_code = {row["code"]: row for row in results}

    market = core.fetch_market_overview(context["quotes"])
    final_market = [
        {
            "时间": CHECKPOINT,
            "指数": f"上证 {market.get('上证', '')}; 创业板 {market.get('创业板', '')}; 科创50 {market.get('科创50', '')}",
            "成交额": market.get("成交额预估", ""),
            "涨跌家数": market.get("涨跌家数", ""),
            "涨停/跌停": market.get("涨停/跌停", ""),
        }
    ]

    amount_ranks = common.sector_amount_ranks(sectors)
    final_sectors = []
    for sector in sectors[:20]:
        stats = sector_stats.get(sector.code, {})
        final_sectors.append(
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
                "成交额排名": amount_ranks.get(sector.code, ""),
                "涨停数": stats.get("limit_up_count", ""),
                "状态": "强势延续" if sector.rank <= 10 and sector.pct > 0 else "分歧",
            }
        )

    final_stocks = []
    all_codes = set(ten_by_code) | set(close_by_code)
    for code in sorted(all_codes):
        ten = ten_by_code.get(code, {})
        close = close_by_code.get(code, {})
        result = result_by_code.get(code, {})
        final_stocks.append(
            {
                "时间": CHECKPOINT,
                "股票": ten.get("股票") or close.get("股票") or code,
                "来源": ten.get("来源(缩量回踩/放量突破/watchlist/portfolio)") or ten.get("来源(突破/回踩/watchlist/portfolio)", ""),
                "走势自然语言": common.stock_trajectory_text(result) if result else close.get("走势自然语言", "行情未评估。"),
                "开盘涨幅": open_by_code.get(code, {}).get("开盘涨幅", "unavailable"),
                "10:30涨幅": ten.get("当前涨幅", ""),
                "收盘涨幅": result.get("pct", close.get("当前涨幅", "")),
                "高点回撤%": result.get("drawdown_from_high_pct", close.get("高点回撤%", "")),
                "VWAP状态": common.vwap_text(result) if result else close.get("VWAP上/下", ""),
                "日K形态": close.get("日K形态", ""),
            }
        )

    portfolio_rows = []
    for code, holding in portfolio_meta.items():
        result = result_by_code.get(code, {})
        plan = plan_meta.get(code, {})
        current_price = common.pct_float(result.get("price"), common.pct_float(holding.get("current_snapshot"), 0))
        avg_cost = common.pct_float(holding.get("avg_cost"), 0)
        shares = common.pct_float(holding.get("shares_total"), 0)
        pnl = round((current_price - avg_cost) * shares, 2) if current_price and avg_cost and shares else ""
        support = common.pct_float(plan.get("key_support_1"), 0)
        risk = (support > 0 and current_price and current_price < support) or (result and not result.get("is_above_vwap")) or bool(result.get("risk_flags"))
        portfolio_rows.append(
            {
                "时间": CHECKPOINT,
                "股票": f"{holding.get('name', '')} {code}",
                "走势自然语言": common.stock_trajectory_text(result) if result else "行情未评估。",
                "持仓数量": holding.get("shares_total", ""),
                "成本": holding.get("avg_cost", ""),
                "收盘价": current_price or "",
                "浮盈亏": pnl,
                "今日操作": "unavailable",
                "是否触发风险条件": common.bool_cn(risk),
                "明日处理条件": plan.get("planned_sell_or_downgrade_condition") or plan.get("planned_buy_condition", ""),
            }
        )

    tables = {
        "market_overview": common.standard_market_overview(args, context),
        "market_sector_scan": common.standard_market_sector_scan(args, context),
        "hot_board_front_core": common.hot_board_front_core(args, context),
        "final_market": final_market,
        "final_sectors": final_sectors,
        "final_stocks": final_stocks,
        "portfolio_final_review": portfolio_rows,
    }
    summary = common.build_summary(args, context, {"sector_row_count": len(final_sectors), "stock_row_count": len(final_stocks), "portfolio_row_count": len(portfolio_rows)})
    common.write_outputs(args, tables, summary, context["errors"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
