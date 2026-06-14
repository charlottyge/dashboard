#!/usr/bin/env python3
from __future__ import annotations

import intraday_common as common
import scan_1030 as core


CHECKPOINT = "9:45"


def main() -> int:
    args = common.parse_common_args("9:45 A-share first impact scan", CHECKPOINT, "scan_0945")
    context = common.load_universe(args, include_intraday_eval=True)
    sectors = context["sectors"]
    sector_stats = context["sector_stats"]
    results = context["results"]
    watch_symbols = context["watch_symbols"]
    portfolio_codes = context["portfolio_codes"]
    portfolio_meta = context["portfolio_meta"]
    plan_meta = context["plan_meta"]
    amount_ranks = common.sector_amount_ranks(sectors)

    selected_sector_codes = {sector.code for sector in sectors[:10]}
    selected_sector_codes |= {sector.code for sector in sorted(sectors, key=lambda item: item.amount, reverse=True)[:10]}
    sector_rows = []
    for sector in sectors:
        if sector.code not in selected_sector_codes:
            continue
        stats = sector_stats.get(sector.code, {})
        sector_rows.append(
            {
                "时间": CHECKPOINT,
                "板块": sector.name,
                "板块来源": sector.source,
                "板块类型": sector.kind,
                "fallback_used": sector.fallback_used,
                "fetch_attempts": sector.fetch_attempts,
                "fallback_reason": sector.fallback_reason,
                "涨幅": round(sector.pct, 3),
                "成交额排名": amount_ranks.get(sector.code, ""),
                "涨家率": round(stats.get("advancers_ratio", ""), 3) if stats.get("advancers_ratio", "") != "" else "",
                "涨停数": stats.get("limit_up_count", ""),
                "代表中军": sector.leader_name,
                "代表前排": sector.leader_name,
            }
        )

    candidate_rows = []
    portfolio_rows = []
    seen_wp: set[str] = set()
    for row in results:
        source = core.source_for_result(row, watch_symbols, portfolio_codes)
        include = row["sector_rank"] != "" and row["sector_rank"] <= 10 or row["symbol"] in watch_symbols or row["code"] in portfolio_codes
        if not include:
            continue
        candidate_rows.append(
            {
                "时间": CHECKPOINT,
                "股票": f"{row['name']} {row['code']}",
                "来源": source or "sector_top10",
                "走势自然语言": common.stock_trajectory_text(row),
                "板块": row["sector"],
                "当前涨幅": row["pct"],
                "板块涨幅": row["sector_pct"],
                "VWAP上/下": common.vwap_text(row),
                "是否高于开盘价": common.bool_cn(row["is_above_open"]),
                "今日高点回撤%": row["drawdown_from_high_pct"],
                "量比": row["volume_ratio_vs_5d_same_time"],
                "成交额": row["amount_1030"],
                "是否强于板块": common.bool_cn(row["relative_strength_vs_sector"] > 0),
            }
        )
        if row["symbol"] in watch_symbols or row["code"] in portfolio_codes:
            seen_wp.add(row["code"])
            support = plan_meta.get(row["code"], {}).get("key_support_1", "")
            portfolio_rows.append(
                {
                    "时间": CHECKPOINT,
                    "股票": f"{row['name']} {row['code']}",
                    "走势自然语言": common.stock_trajectory_text(row),
                    "当前价": row["price"],
                    "当前涨幅": row["pct"],
                    "VWAP上/下": common.vwap_text(row),
                    "是否跌破开盘区间": common.bool_cn(not row["is_above_open"]),
                    "关键位": support,
                    "今日风险状态": "风险预警" if row["risk_flags"] or not row["is_above_vwap"] else "正常观察",
                }
            )
    for item in common.watch_portfolio_items(context):
        if item["code"] in seen_wp:
            continue
        portfolio_rows.append(
            {
                "时间": CHECKPOINT,
                "股票": f"{item['name']} {item['code']}".strip(),
                "走势自然语言": common.unavailable_trajectory_text(),
                "当前价": "",
                "当前涨幅": "",
                "VWAP上/下": "unavailable",
                "是否跌破开盘区间": "unavailable",
                "关键位": plan_meta.get(item["code"], {}).get("key_support_1", ""),
                "今日风险状态": "行情未评估",
            }
        )

    tables = {
        "market_overview": common.standard_market_overview(args, context),
        "market_sector_scan": common.standard_market_sector_scan(args, context),
        "hot_board_front_core": common.hot_board_front_core(args, context),
        "sector_first_impact": sector_rows,
        "candidate_first_impact": candidate_rows,
        "portfolio_first_impact": portfolio_rows,
    }
    summary = common.build_summary(args, context, {"sector_row_count": len(sector_rows), "candidate_row_count": len(candidate_rows), "portfolio_row_count": len(portfolio_rows)})
    common.write_outputs(args, tables, summary, context["errors"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
