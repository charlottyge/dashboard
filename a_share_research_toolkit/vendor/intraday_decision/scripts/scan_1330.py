#!/usr/bin/env python3
from __future__ import annotations

import intraday_common as common
import scan_1030 as core


CHECKPOINT = "13:30"


def main() -> int:
    args = common.parse_common_args("13:30 A-share afternoon restart scan", CHECKPOINT, "scan_1330")
    context = common.load_universe(args, include_intraday_eval=True)
    sectors = context["sectors"]
    results = context["results"]
    watch_symbols = context["watch_symbols"]
    portfolio_codes = context["portfolio_codes"]
    plan_meta = context["plan_meta"]
    prior_1030 = common.prior_candidates(args, "scan_1030")
    prior_1120 = common.read_csv(common.previous_root(args) / "scan_1120" / "candidate_morning_check.csv")
    prior_by_code = {str(row.get("股票", "")).split()[-1]: row for row in prior_1030 if row.get("股票")}
    morning_by_code = {str(row.get("股票", "")).split()[-1]: row for row in prior_1120 if row.get("股票")}
    prior_sector_rank = {row.get("板块"): row.get("涨幅排名") for row in common.prior_sector_rows(args, "scan_1030")}
    prior_sector_pct = {row.get("板块"): row.get("涨幅") for row in common.prior_sector_rows(args, "scan_1030")}

    sector_rows = []
    for sector in sectors[:15]:
        old_rank = common.pct_float(prior_sector_rank.get(sector.name), 999)
        old_pct = common.pct_float(prior_sector_pct.get(sector.name), 0)
        rank_change = old_rank - sector.rank if old_rank != 999 else ""
        pct_change = sector.pct - old_pct
        include = sector.rank <= 10 or (rank_change != "" and rank_change >= 5)
        if not include:
            continue
        sector_rows.append(
            {
                "时间": CHECKPOINT,
                "板块": sector.name,
                "板块来源": sector.source,
                "板块类型": sector.kind,
                "fallback_used": sector.fallback_used,
                "fetch_attempts": sector.fetch_attempts,
                "fallback_reason": sector.fallback_reason,
                "10:30排名": int(old_rank) if old_rank != 999 else "",
                "13:30排名": sector.rank,
                "排名变化": rank_change,
                "涨幅变化": round(pct_change, 3),
                "成交额变化": "unavailable",
                "状态": "午后上升" if rank_change != "" and rank_change > 0 else "上午强线延续" if sector.rank <= 10 else "未确认切换",
            }
        )

    candidate_rows = []
    portfolio_rows = []
    seen_wp: set[str] = set()
    for row in results:
        prior_row = prior_by_code.get(row["code"], {})
        morning_row = morning_by_code.get(row["code"], {})
        prior_source = common.prior_candidate_source(prior_row)
        include = common.is_prior_main_candidate(prior_row) or row["symbol"] in watch_symbols or row["code"] in portfolio_codes or (row["sector_rank"] != "" and row["sector_rank"] <= 10)
        if not include:
            continue
        morning_price = common.pct_float(morning_row.get("当前价"), 0)
        candidate_rows.append(
            {
                "时间": CHECKPOINT,
                "股票": f"{row['name']} {row['code']}",
                "10:30来源": prior_source or "sector/watchlist",
                "走势自然语言": common.stock_trajectory_text(row),
                "当前价": row["price"],
                "当前涨幅": row["pct"],
                "VWAP上/下": common.vwap_text(row),
                "是否突破上午高点": common.bool_cn(morning_price > 0 and row["price"] > morning_price),
                "是否跌破上午低点": common.bool_cn(row["position_in_range"] <= 0.05),
                "高点回撤%": row["drawdown_from_high_pct"],
                "是否强于板块": common.bool_cn(row["relative_strength_vs_sector"] > 0),
            }
        )
        if row["symbol"] in watch_symbols or row["code"] in portfolio_codes:
            seen_wp.add(row["code"])
            plan = plan_meta.get(row["code"], {})
            support = common.pct_float(plan.get("key_support_1"), 0)
            risk = (support > 0 and row["price"] < support) or not row["is_above_vwap"]
            portfolio_rows.append(
                {
                    "时间": CHECKPOINT,
                    "股票": f"{row['name']} {row['code']}",
                    "走势自然语言": common.stock_trajectory_text(row),
                    "当前价": row["price"],
                    "当前涨幅": row["pct"],
                    "是否收回关键位": common.bool_cn(not risk) if support else "unavailable",
                    "是否触发风险处理": common.bool_cn(risk),
                }
            )
    for item in common.watch_portfolio_items(context):
        if item["code"] in seen_wp:
            continue
        candidate_rows.append(
            {
                "时间": CHECKPOINT,
                "股票": f"{item['name']} {item['code']}".strip(),
                "10:30来源": "watchlist/portfolio",
                "走势自然语言": common.unavailable_trajectory_text(),
                "当前价": "",
                "当前涨幅": "",
                "VWAP上/下": "unavailable",
                "是否突破上午高点": "unavailable",
                "是否跌破上午低点": "unavailable",
                "高点回撤%": "",
                "是否强于板块": "unavailable",
            }
        )
        portfolio_rows.append(
            {
                "时间": CHECKPOINT,
                "股票": f"{item['name']} {item['code']}".strip(),
                "走势自然语言": common.unavailable_trajectory_text(),
                "当前价": "",
                "当前涨幅": "",
                "是否收回关键位": "unavailable",
                "是否触发风险处理": "unavailable",
            }
        )

    tables = {
        "market_overview": common.standard_market_overview(args, context),
        "market_sector_scan": common.standard_market_sector_scan(args, context),
        "hot_board_front_core": common.hot_board_front_core(args, context),
        "sector_afternoon_change": sector_rows,
        "candidate_afternoon_restart": candidate_rows,
        "portfolio_afternoon_status": portfolio_rows,
    }
    summary = common.build_summary(args, context, {"sector_change_row_count": len(sector_rows), "candidate_row_count": len(candidate_rows), "portfolio_row_count": len(portfolio_rows)})
    common.write_outputs(args, tables, summary, context["errors"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
