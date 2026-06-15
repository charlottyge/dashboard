#!/usr/bin/env python3
from __future__ import annotations

import intraday_common as common
import scan_1030 as core


CHECKPOINT = "14:40"


def candle_type(row: dict) -> str:
    pct = common.pct_float(row.get("pct"), 0)
    drawdown = abs(common.pct_float(row.get("drawdown_from_high_pct"), 0))
    if drawdown >= 5 and pct > 0:
        return "长上影"
    if pct >= 5 and drawdown <= 2:
        return "强阳接近高位"
    if pct < 0:
        return "阴线/回落"
    return "震荡"


def main() -> int:
    args = common.parse_common_args("14:40 A-share closing confirmation scan", CHECKPOINT, "scan_1440")
    context = common.load_universe(args, include_intraday_eval=True)
    sectors = context["sectors"]
    sector_stats = context["sector_stats"]
    results = context["results"]
    watch_symbols = context["watch_symbols"]
    portfolio_codes = context["portfolio_codes"]
    portfolio_meta = context["portfolio_meta"]
    plan_meta = context["plan_meta"]
    prior_1030 = common.prior_candidates(args, "scan_1030")
    prior_1330 = common.read_csv(common.previous_root(args) / "scan_1330" / "sector_afternoon_change.csv")
    prior_by_code = {str(row.get("股票", "")).split()[-1]: row for row in prior_1030 if row.get("股票")}
    rank_1330 = {row.get("板块"): row.get("13:30排名") for row in prior_1330}

    market_overview = core.fetch_market_overview(context["quotes"], args, results)
    index_text = "; ".join(f"{label} {market_overview.get(label, '')}" for label in core.INDEX_SYMBOLS.values())
    market_rows = [
        {
            "时间": CHECKPOINT,
            "指数涨幅": index_text,
            "成交额": market_overview.get("成交额预估", ""),
            "涨跌家数": market_overview.get("涨跌家数", ""),
            "涨停/跌停": market_overview.get("涨停/跌停", ""),
        }
    ]

    sector_rows = []
    for sector in sectors[:10]:
        old_rank = common.pct_float(rank_1330.get(sector.name), 999)
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
                "全天排名": sector.rank,
                "13:30排名": int(old_rank) if old_rank != 999 else "",
                "尾盘变化": old_rank - sector.rank if old_rank != 999 else "unavailable",
                "涨停数": stats.get("limit_up_count", ""),
                "中军收盘位置": f"{sector.leader_name} {sector.leader_pct:.3f}%",
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
                "来源": prior_source or core.source_for_result(row, watch_symbols, portfolio_codes),
                "走势自然语言": common.stock_trajectory_text(row),
                "当前价": row["price"],
                "当前涨幅": row["pct"],
                "VWAP上/下": common.vwap_text(row),
                "收盘接近高点%": round(100 - abs(row["drawdown_from_high_pct"]), 3),
                "高点回撤%": row["drawdown_from_high_pct"],
                "日K形态": candle_type(row),
                "成交量状态": "爆量" if row["volume_ratio_vs_5d_same_time"] > 5 else "放量" if row["volume_ratio_vs_5d_same_time"] >= 1.5 else "缩量",
                "是否强于板块": common.bool_cn(row["relative_strength_vs_sector"] > 0),
            }
        )
        if row["symbol"] in watch_symbols or row["code"] in portfolio_codes:
            seen_wp.add(row["code"])
            holding = portfolio_meta.get(row["code"], {})
            avg_cost = common.pct_float(holding.get("avg_cost"), 0)
            shares = common.pct_float(holding.get("shares_total"), 0)
            pnl = round((row["price"] - avg_cost) * shares, 2) if avg_cost and shares else ""
            support = common.pct_float(plan_meta.get(row["code"], {}).get("key_support_1"), 0)
            recovered = support == 0 or row["price"] >= support
            risk = (support > 0 and not recovered) or not row["is_above_vwap"] or bool(row["risk_flags"])
            portfolio_rows.append(
                {
                    "时间": CHECKPOINT,
                    "股票": f"{row['name']} {row['code']}",
                    "走势自然语言": common.stock_trajectory_text(row),
                    "当前价": row["price"],
                    "当前浮盈亏": pnl,
                    "是否触发风险条件": common.bool_cn(risk),
                    "是否收回关键位": common.bool_cn(recovered) if support else "unavailable",
                    "明日处理": "按风险条件处理" if risk else "按原计划继续观察",
                }
            )
    for item in common.watch_portfolio_items(context):
        if item["code"] in seen_wp:
            continue
        candidate_rows.append(
            {
                "时间": CHECKPOINT,
                "股票": f"{item['name']} {item['code']}".strip(),
                "来源": item["source"],
                "走势自然语言": common.unavailable_trajectory_text(),
                "当前价": "",
                "当前涨幅": "",
                "VWAP上/下": "unavailable",
                "收盘接近高点%": "",
                "高点回撤%": "",
                "日K形态": "unavailable",
                "成交量状态": "unavailable",
                "是否强于板块": "unavailable",
            }
        )
        portfolio_rows.append(
            {
                "时间": CHECKPOINT,
                "股票": f"{item['name']} {item['code']}".strip(),
                "走势自然语言": common.unavailable_trajectory_text(),
                "当前价": "",
                "当前浮盈亏": "",
                "是否触发风险条件": "unavailable",
                "是否收回关键位": "unavailable",
                "明日处理": "行情未评估，盘后补验证",
            }
        )

    tables = {
        "market_overview": common.standard_market_overview(args, context),
        "market_sector_scan": common.standard_market_sector_scan(args, context),
        "hot_board_front_core": common.hot_board_front_core(args, context),
        "market_close_confirm": market_rows,
        "sector_close_confirm": sector_rows,
        "candidate_close_confirm": candidate_rows,
        "portfolio_close_confirm": portfolio_rows,
    }
    summary = common.build_summary(args, context, {"sector_row_count": len(sector_rows), "candidate_row_count": len(candidate_rows), "portfolio_row_count": len(portfolio_rows)})
    common.write_outputs(args, tables, summary, context["errors"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
