#!/usr/bin/env python3
from __future__ import annotations

import intraday_common as common
import scan_1030 as core


CHECKPOINT = "11:20"


def main() -> int:
    args = common.parse_common_args("11:20 A-share morning close scan", CHECKPOINT, "scan_1120")
    context = common.load_universe(args, include_intraday_eval=True)
    sectors = context["sectors"]
    results = context["results"]
    watch_symbols = context["watch_symbols"]
    portfolio_codes = context["portfolio_codes"]
    portfolio_meta = context["portfolio_meta"]
    plan_meta = context["plan_meta"]
    prior = common.prior_candidates(args, "scan_1030")
    prior_by_code = {str(row.get("股票", "")).split()[-1]: row for row in prior if row.get("股票")}
    prior_sector_rank = {row.get("板块"): row.get("涨幅排名") for row in common.prior_sector_rows(args, "scan_1030")}

    sector_rows = []
    for sector in sectors[:5]:
        old_rank = prior_sector_rank.get(sector.name, "")
        old_rank_num = common.pct_float(old_rank, 999)
        sector_rows.append(
            {
                "时间": CHECKPOINT,
                "板块": sector.name,
                "板块来源": sector.source,
                "板块类型": sector.kind,
                "fallback_used": sector.fallback_used,
                "fetch_attempts": sector.fetch_attempts,
                "fallback_reason": sector.fallback_reason,
                "10:30排名": old_rank,
                "当前排名": sector.rank,
                "是否延续": common.bool_cn(old_rank_num <= 10 and sector.rank <= 10),
                "中军表现": f"{sector.leader_name} {sector.leader_pct:.3f}%",
                "前排表现": f"{sector.leader_name} {sector.leader_pct:.3f}%",
            }
        )

    candidate_rows = []
    portfolio_rows = []
    seen_wp: set[str] = set()
    for row in results:
        prior_row = prior_by_code.get(row["code"], {})
        prior_source = common.prior_candidate_source(prior_row)
        include = common.is_prior_main_candidate(prior_row) or row["symbol"] in watch_symbols or row["code"] in portfolio_codes
        if not include:
            continue
        candidate_rows.append(
            {
                "时间": CHECKPOINT,
                "股票": f"{row['name']} {row['code']}",
                "10:30来源": prior_source or "watchlist/portfolio",
                "走势自然语言": common.stock_trajectory_text(row),
                "当前价": row["price"],
                "当前涨幅": row["pct"],
                "VWAP上/下": common.vwap_text(row),
                "是否收回VWAP": common.bool_cn(row["reclaimed_vwap"]),
                "是否跌破上午低点": common.bool_cn(row["position_in_range"] <= 0.05),
                "高点回撤%": row["drawdown_from_high_pct"],
                "成交额变化": common.amount_delta_text(row["amount_1030"], prior_row.get("成交额", "")),
            }
        )
        if row["symbol"] in watch_symbols or row["code"] in portfolio_codes:
            seen_wp.add(row["code"])
            plan = plan_meta.get(row["code"], {})
            support = common.pct_float(plan.get("key_support_1"), 0)
            recovered = support == 0 or row["price"] >= support
            risk = (support > 0 and row["price"] < support) or not row["is_above_vwap"] or bool(row["risk_flags"])
            portfolio_rows.append(
                {
                    "时间": CHECKPOINT,
                    "股票": f"{portfolio_meta.get(row['code'], {}).get('name') or row['name']} {row['code']}",
                    "走势自然语言": common.stock_trajectory_text(row),
                    "当前价": row["price"],
                    "VWAP上/下": common.vwap_text(row),
                    "是否收回关键位": common.bool_cn(recovered) if support else "unavailable",
                    "是否触发风险条件": common.bool_cn(risk),
                    "午后预案": "午后优先风险处理" if risk else "午后继续确认",
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
                "是否收回VWAP": "unavailable",
                "是否跌破上午低点": "unavailable",
                "高点回撤%": "",
                "成交额变化": "unavailable",
            }
        )
        portfolio_rows.append(
            {
                "时间": CHECKPOINT,
                "股票": f"{item['name']} {item['code']}".strip(),
                "走势自然语言": common.unavailable_trajectory_text(),
                "当前价": "",
                "VWAP上/下": "unavailable",
                "是否收回关键位": "unavailable",
                "是否触发风险条件": "unavailable",
                "午后预案": "行情未评估，午后补验证",
            }
        )

    tables = {
        "market_overview": common.standard_market_overview(args, context),
        "market_sector_scan": common.standard_market_sector_scan(args, context),
        "hot_board_front_core": common.hot_board_front_core(args, context),
        "morning_mainlines": sector_rows,
        "candidate_morning_check": candidate_rows,
        "portfolio_morning_plan": portfolio_rows,
    }
    summary = common.build_summary(args, context, {"mainline_row_count": len(sector_rows), "candidate_row_count": len(candidate_rows), "portfolio_row_count": len(portfolio_rows)})
    common.write_outputs(args, tables, summary, context["errors"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
