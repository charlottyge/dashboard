from __future__ import annotations

from datetime import datetime
from typing import Any


TRUTHY = {"true", "yes", "是", "1", "触发", "已触发"}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip().replace("%", "").replace(",", "")
    if not text or text.lower() in {"nan", "none", "null", "unavailable"}:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in TRUTHY


def _first(row: dict[str, Any], keys: list[str], default: Any = "") -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def _stock_name(row: dict[str, Any]) -> str:
    return _text(_first(row, ["股票", "stock", "name", "名称"], ""))


def _sector_name(row: dict[str, Any]) -> str:
    return _text(_first(row, ["板块", "所属板块", "sector"], ""))


def _sector_rank(row: dict[str, Any]) -> float:
    return _num(
        _first(
            row,
            [
                "涨幅排名",
                "板块排名",
                "当前排名",
                "13:30排名",
                "全天排名",
                "10:30排名",
                "sector_rank",
            ],
            999,
        ),
        999,
    )


def _sector_pct(row: dict[str, Any]) -> float:
    return _num(_first(row, ["涨幅", "板块涨幅", "开盘涨幅", "板块开盘涨幅", "sector_pct"], 0), 0)


def _stock_pct(row: dict[str, Any]) -> float:
    return _num(_first(row, ["当前涨幅", "当前涨幅%", "收盘涨幅", "10:30涨幅", "开盘涨幅", "pct"], 0), 0)


def _vwap_state(row: dict[str, Any]) -> str:
    raw = _text(_first(row, ["VWAP上/下", "VWAP状态", "中军VWAP", "vwap_status"], ""))
    if raw in {"上", "上方", "true", "True", "是"}:
        return "above"
    if raw in {"下", "下方", "false", "False", "否"}:
        return "below"
    return raw or "unavailable"


def _candidate_type(row: dict[str, Any]) -> str:
    pct = _stock_pct(row)
    drawdown = abs(_num(_first(row, ["高点回撤%", "drawdown_from_high_pct"], 0), 0))
    vwap = _vwap_state(row)
    source = _text(_first(row, ["来源", "来源(缩量回踩/放量突破/watchlist/portfolio)", "10:30来源", "策略"], ""))
    reason = _text(_first(row, ["风险标记", "hard_cap_reason", "过滤说明"], ""))
    position = _num(_first(row, ["日内位置%", "position_in_range"], 0), 0)
    if pct >= 8 or "涨停" in reason or (position >= 88 and pct >= 5):
        return "do_not_chase"
    if vwap == "below" or drawdown >= 4:
        return "theme_validator"
    if "缩量回踩" in source or "回踩" in source:
        return "watch_candidate"
    if "突破" in source and vwap == "above" and drawdown <= 3:
        return "trade_candidate"
    if "watchlist" in source or "portfolio" in source:
        return "watch_candidate"
    return "theme_validator"


def _chase_risk(row: dict[str, Any]) -> str:
    pct = _stock_pct(row)
    drawdown = abs(_num(_first(row, ["高点回撤%", "drawdown_from_high_pct"], 0), 0))
    position = _num(_first(row, ["日内位置%", "position_in_range"], 0), 0)
    distance_ma5 = _num(_first(row, ["距5日线%", "distance_to_ma5_pct"], 0), 0)
    reasons: list[str] = []
    if pct >= 8:
        reasons.append("涨幅过高")
    if position >= 88 and pct >= 5:
        reasons.append("接近日内高位")
    if drawdown >= 4:
        reasons.append("高点回撤偏大")
    if distance_ma5 >= 12:
        reasons.append("距离5日线偏远")
    return "；".join(reasons) if reasons else "normal"


def enrich_strategy_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        row["candidate_type"] = _candidate_type(row)
        row["chase_risk"] = _chase_risk(row)
    return rows


def build_checkpoint_decision_summary(
    *,
    checkpoint: str,
    summary: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    sector_rows = _collect_rows(
        tables,
        [
            "market_sector_scan",
            "sector_first_impact",
            "morning_mainlines",
            "sector_afternoon_change",
            "sector_close_confirm",
            "final_sectors",
            "sector_strength",
            "hot_board_front_core",
        ],
    )
    candidate_rows = _collect_rows(
        tables,
        [
            "candidate_scores",
            "candidate_first_impact",
            "candidate_morning_check",
            "candidate_afternoon_restart",
            "candidate_close_confirm",
            "final_stocks",
        ],
    )
    portfolio_rows = _collect_rows(
        tables,
        [
            "watchlist_portfolio_actions",
            "watchlist_portfolio_open",
            "portfolio_first_impact",
            "portfolio_morning_plan",
            "portfolio_afternoon_status",
            "portfolio_close_confirm",
            "portfolio_final_review",
            "portfolio_decision_rules",
        ],
    )

    confirmed = _confirmed_mainlines(sector_rows)
    weakening = _weakening_mainlines(sector_rows)
    improving = _new_improving_lines(sector_rows)
    do_not_chase = _do_not_chase(candidate_rows)
    portfolio_priority = _portfolio_priority(portfolio_rows)
    return {
        "version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "checkpoint": checkpoint,
        "data_timestamp": summary.get("data_timestamp", ""),
        "market_state": _market_state(confirmed, weakening, improving, summary),
        "risk_preference": _risk_preference(do_not_chase, portfolio_priority, summary),
        "confirmed_mainlines": confirmed,
        "weakening_mainlines": weakening,
        "new_improving_lines": improving,
        "do_not_chase": do_not_chase,
        "portfolio_priority": portfolio_priority,
        "next_checkpoint_watch": _next_checkpoint_watch(checkpoint, confirmed, weakening, improving, portfolio_priority),
        "data_quality": {
            "fallback_used": bool(summary.get("fallback_used", False)),
            "fetch_attempts": summary.get("fetch_attempts", ""),
            "fallback_reason": summary.get("fallback_reason", ""),
            "error_count": summary.get("error_count", 0),
            "usable_field_count": summary.get("field_availability", {}).get("usable_field_count", ""),
            "unusable_field_count": summary.get("field_availability", {}).get("unusable_field_count", ""),
            "source_chain": summary.get("source_chain", []),
        },
    }


def build_strategy_decision_summary(
    *,
    checkpoint: str,
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    excluded_rows: list[dict[str, Any]],
    unavailable_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    do_not_chase = _do_not_chase(rows)
    by_type: dict[str, int] = {}
    for row in rows:
        key = _text(row.get("candidate_type") or _candidate_type(row))
        by_type[key] = by_type.get(key, 0) + 1
    return {
        "version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "checkpoint": checkpoint,
        "data_timestamp": summary.get("data_timestamp", ""),
        "market_state": "策略包扫描，不强行生成市场状态",
        "risk_preference": "低" if do_not_chase else "中",
        "confirmed_mainlines": [],
        "weakening_mainlines": [],
        "new_improving_lines": [],
        "candidate_type_counts": by_type,
        "do_not_chase": do_not_chase,
        "portfolio_priority": [],
        "next_checkpoint_watch": [
            "对 trade_candidate 等待回踩/VWAP 承接，不把策略命中直接等同于可买",
            "对 do_not_chase 只作为题材强度验证样本，观察尾盘是否回落",
            "复核流通股过滤、板块匹配和命中原因是否完整",
        ],
        "data_quality": {
            "fallback_used": False,
            "fetch_attempts": "",
            "fallback_reason": "",
            "error_count": summary.get("error_count", 0),
            "float_excluded_count": len(excluded_rows),
            "float_unavailable_count": len(unavailable_rows),
            "source_chain": summary.get("source_chain", []),
        },
    }


def _collect_rows(tables: dict[str, list[dict[str, Any]]], names: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in names:
        rows.extend(tables.get(name, []))
    return rows


def _confirmed_mainlines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        name = _sector_name(row)
        if not name or name in seen:
            continue
        rank = _sector_rank(row)
        pct = _sector_pct(row)
        status = _text(_first(row, ["状态", "状态(延续/分歧/切换)", "数据状态"], ""))
        if rank <= 5 or "确认" in status or "延续" in status or "Leading" in status:
            output.append(
                _sector_decision_item(row, confirmed=True, default_state="continue_strong")
            )
            seen.add(name)
        if len(output) >= 6:
            break
    return output


def _weakening_mainlines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        name = _sector_name(row)
        if not name or name in seen:
            continue
        status = _text(_first(row, ["状态", "状态(延续/分歧/切换)", "尾盘变化"], ""))
        pct = _sector_pct(row)
        change = _num(_first(row, ["排名变化", "尾盘变化", "涨幅变化"], 0), 0)
        if pct < 0 or change < -5 or any(token in status for token in ["分歧", "退潮", "回落", "fade", "Weakening"]):
            output.append(
                _sector_decision_item(row, confirmed=False, default_state="afternoon_fade")
            )
            seen.add(name)
        if len(output) >= 6:
            break
    return output


def _new_improving_lines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        name = _sector_name(row)
        if not name or name in seen:
            continue
        status = _text(_first(row, ["状态", "状态(延续/分歧/切换)", "尾盘变化"], ""))
        change = _num(_first(row, ["排名变化", "尾盘变化", "涨幅变化"], 0), 0)
        if change > 3 or any(token in status for token in ["切换", "新", "改善", "午后确认", "首次"]):
            output.append(
                _sector_decision_item(row, confirmed=False, default_state="afternoon_reflow", force_tier="branch_rotation")
            )
            seen.add(name)
        if len(output) >= 6:
            break
    return output


def _sector_decision_item(
    row: dict[str, Any],
    *,
    confirmed: bool,
    default_state: str,
    force_tier: str | None = None,
) -> dict[str, Any]:
    rank = _sector_rank(row)
    stage = _stage(row, confirmed=confirmed)
    rebound_type = _rebound_type(row, stage)
    structure = _structure_score(row)
    crowding = _crowding_signal(row)
    return {
        "name": _sector_name(row),
        "rank": rank if rank != 999 else "",
        "pct": _sector_pct(row),
        "theme_tier": force_tier or _theme_tier(row, confirmed=confirmed),
        "intraday_state": _intraday_state(row, default_state),
        "stage": stage,
        "rebound_type": rebound_type,
        "structure_score": structure["score"],
        "structure_state": structure["state"],
        "crowding_signal": crowding,
        "two_day_acceleration": _two_day_acceleration(row),
        "reason": _sector_reason(row),
    }


def _do_not_chase(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        name = _stock_name(row)
        if not name or name in seen:
            continue
        candidate_type = _text(row.get("candidate_type") or _candidate_type(row))
        chase_risk = _text(row.get("chase_risk") or _chase_risk(row))
        if candidate_type == "do_not_chase" or chase_risk != "normal":
            output.append(
                {
                    "stock": name,
                    "pct": _stock_pct(row),
                    "candidate_type": candidate_type,
                    "reason": chase_risk,
                    "confirm_if": _confirm_if(row),
                    "invalidate_if": _invalidate_if(row),
                }
            )
            seen.add(name)
        if len(output) >= 8:
            break
    return output


def _portfolio_priority(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_stock: dict[str, dict[str, Any]] = {}
    for row in rows:
        stock = _stock_name(row)
        if not stock:
            continue
        priority, action_type, reason = _portfolio_action(row)
        item = {
            "stock": stock,
            "priority": priority,
            "action_type": action_type,
            "reason": reason,
            "trigger_price": _first(row, ["风险线", "止损线", "第一保护线", "关键位", "关键位1", "明日处理条件", "明日处理"], ""),
            "invalid_condition": _first(row, ["原计划失效条件", "是否触发风险条件", "是否触发风险处理"], ""),
        }
        existing = by_stock.get(stock)
        if existing is None or _portfolio_priority_row_quality(item, row) > _portfolio_priority_row_quality(existing, {}):
            by_stock[stock] = item
    output = list(by_stock.values())
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    output.sort(key=lambda item: order.get(str(item["priority"]), 9))
    return output[:10]


def _portfolio_priority_row_quality(item: dict[str, Any], row: dict[str, Any]) -> int:
    quality = 0
    if _text(_first(row, ["类型"], "")):
        quality += 5
    if _text(item.get("trigger_price")):
        quality += 3
    if _text(item.get("reason")) and item.get("reason") != "触发风险条件":
        quality += 1
    return quality


def _portfolio_action(row: dict[str, Any]) -> tuple[str, str, str]:
    position_type = _text(_first(row, ["类型"], ""))
    if "必须处理" in position_type:
        return "P0", "risk_handle", position_type
    if "修复失败" in position_type:
        return "P1", "watch_key_level", position_type
    if "冲高后保护" in position_type:
        return "P1", "profit_protect", position_type
    if "强势趋势" in position_type:
        return "P2", "hold_observe", position_type
    risk = _truthy(_first(row, ["是否触发风险条件", "是否触发风险处理", "risk_condition_met"], ""))
    risk_status = _text(_first(row, ["今日风险状态", "明日处理", "午后预案"], ""))
    vwap = _vwap_state(row)
    stronger = _text(_first(row, ["是否强于板块"], ""))
    if risk or "风险" in risk_status or "跌破" in risk_status:
        return "P0", "risk_handle", risk_status or "触发风险条件"
    if vwap == "below" or stronger == "否":
        return "P1", "watch_key_level", "弱于板块或位于 VWAP 下方"
    if stronger == "是" or vwap == "above":
        return "P2", "hold_observe", "强于板块或仍在 VWAP 上方"
    return "P3", "ignore_for_now", "暂无明确触发条件"


def _theme_tier(row: dict[str, Any], confirmed: bool = False) -> str:
    status = _text(_first(row, ["状态", "状态(延续/分歧/切换)", "数据状态"], ""))
    rank = _sector_rank(row)
    pct = _sector_pct(row)
    if any(token in status for token in ["退潮", "分歧", "回落"]):
        return "fading"
    if confirmed and rank <= 3 and pct > 1:
        return "mainline_confirmed"
    if rank <= 10 and pct > 0:
        return "mainline_watch"
    if pct < 0:
        return "risk_off"
    return "pulse_only"


def _stage(row: dict[str, Any], confirmed: bool = False) -> str:
    pct = _sector_pct(row)
    status = _text(_first(row, ["状态", "状态(延续/分歧/切换)", "数据状态", "尾盘变化"], ""))
    structure = _structure_score(row)
    if _defense_failed(row):
        return "defense_failed"
    if any(token in status for token in ["退潮", "回落", "分歧"]):
        return "downgraded"
    if _crowding_signal(row) == "high_crowding":
        return "high_crowding"
    if structure["state"] == "末端扩散":
        return "late_diffusion"
    if pct > 0 and ("修复" in status or "反弹" in status):
        return "rebound_only"
    if _two_day_acceleration(row):
        return "two_day_acceleration"
    if confirmed and structure["score"] >= 75:
        return "confirming"
    if confirmed:
        return "mainline_candidate"
    if pct < 0:
        return "downgraded"
    return "watch"


def _rebound_type(row: dict[str, Any], stage: str) -> str:
    pct = _sector_pct(row)
    status = _text(_first(row, ["状态", "状态(延续/分歧/切换)", "数据状态", "尾盘变化"], ""))
    structure = _structure_score(row)
    if stage in {"confirming", "mainline_candidate"} and structure["score"] >= 75:
        return "mainline_confirmed"
    if "修复失败" in status or "反抽失败" in status or stage == "downgraded":
        return "failed_rebound"
    if stage == "rebound_only" or ("修复" in status and structure["score"] < 75):
        return "rebound_only"
    if pct > 0 and structure["state"] in {"趋势资金回流", "结构健康"}:
        return "reversal_candidate"
    return "none"


def _structure_score(row: dict[str, Any]) -> dict[str, Any]:
    has_structure_fields = any(key in row for key in ["中军涨幅", "前排1涨幅", "前排2涨幅", "前排3涨幅"])
    core = _num(_first(row, ["中军涨幅", "中军收盘位置"], ""), 0)
    front_values = [
        _num(_first(row, [f"前排{index}涨幅"], ""), 0)
        for index in range(1, 4)
    ]
    front_values = [value for value in front_values if value != 0]
    front = sum(front_values) / len(front_values) if front_values else 0
    sector_pct = _sector_pct(row)
    limit_up = _num(_first(row, ["涨停数", "final_limit_up_count"], ""), 0)
    if not has_structure_fields:
        score = 30 if sector_pct > 0 or limit_up >= 2 else 0
        return {"score": score, "state": "结构待验证"}

    core_strong = core > 0
    front_strong = front > 0
    broad_strong = sector_pct > 0 or limit_up >= 2
    score = 0
    if core_strong:
        score += 40
    if front_strong:
        score += 30
    if broad_strong:
        score += 30

    if core_strong and front_strong and broad_strong:
        state = "结构健康"
    elif core_strong and not front_strong:
        state = "趋势资金回流"
    elif front_strong and not core_strong:
        state = "情绪脉冲"
    elif broad_strong and not core_strong and not front_strong:
        state = "末端扩散"
    else:
        state = "结构转弱"
    return {"score": score, "state": state}


def _crowding_signal(row: dict[str, Any]) -> str:
    pct = _sector_pct(row)
    limit_up = _num(_first(row, ["涨停数", "final_limit_up_count"], ""), 0)
    front_values = [
        _num(_first(row, [f"前排{index}涨幅"], ""), 0)
        for index in range(1, 4)
    ]
    front_values = [value for value in front_values if value != 0]
    front_avg = sum(front_values) / len(front_values) if front_values else 0
    if pct >= 8 or front_avg >= 10 or limit_up >= 5:
        return "high_crowding"
    if pct >= 5 or front_avg >= 7 or limit_up >= 3:
        return "elevated"
    return "normal"


def _two_day_acceleration(row: dict[str, Any]) -> bool:
    status = _text(_first(row, ["状态", "状态(延续/分歧/切换)", "数据状态"], ""))
    pct = _sector_pct(row)
    return pct >= 4 and any(token in status for token in ["延续", "确认", "趋势"])


def _defense_failed(row: dict[str, Any]) -> bool:
    name = _sector_name(row)
    pct = _sector_pct(row)
    defensive_keywords = ["煤炭", "火电", "电力", "特高压", "虚拟电厂"]
    return pct < 0 and any(keyword in name for keyword in defensive_keywords)


def _intraday_state(row: dict[str, Any], default: str) -> str:
    status = _text(_first(row, ["状态", "状态(延续/分歧/切换)", "尾盘变化"], ""))
    vwap = _vwap_state(row)
    if "尾盘确认" in status:
        return "late_confirm"
    if any(token in status for token in ["退潮", "分歧", "回落"]):
        return "afternoon_fade"
    if "切换" in status or "午后确认" in status:
        return "afternoon_reflow"
    if vwap == "below":
        return "fake_open"
    return default


def _sector_reason(row: dict[str, Any]) -> str:
    parts = []
    rank = _sector_rank(row)
    if rank != 999:
        parts.append(f"排名 {rank:g}")
    parts.append(f"涨幅 {_sector_pct(row):.2f}%")
    status = _text(_first(row, ["状态", "状态(延续/分歧/切换)", "数据状态"], ""))
    if status:
        parts.append(status)
    source = _text(_first(row, ["板块来源"], ""))
    if source:
        parts.append(source)
    return "；".join(parts)


def _market_state(
    confirmed: list[dict[str, Any]],
    weakening: list[dict[str, Any]],
    improving: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    if summary.get("fallback_used"):
        quality = "，数据部分 fallback"
    else:
        quality = ""
    if confirmed and weakening:
        return f"主线分化：强线仍在，但部分方向走弱{quality}"
    if confirmed and improving:
        return f"主线延续 + 分支轮动{quality}"
    if confirmed:
        return f"主线延续{quality}"
    if improving:
        return f"日内切换/新方向改善{quality}"
    if weakening:
        return f"高位退潮或弱修复{quality}"
    return f"暂无清晰主线{quality}"


def _risk_preference(do_not_chase: list[dict[str, Any]], portfolio_priority: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    p0_count = sum(1 for item in portfolio_priority if item.get("priority") == "P0")
    error_count = _num(summary.get("error_count"), 0)
    if p0_count or len(do_not_chase) >= 5 or error_count > 100:
        return "低"
    if do_not_chase or error_count > 0:
        return "中"
    return "高"


def _next_checkpoint_watch(
    checkpoint: str,
    confirmed: list[dict[str, Any]],
    weakening: list[dict[str, Any]],
    improving: list[dict[str, Any]],
    portfolio_priority: list[dict[str, Any]],
) -> list[str]:
    next_name = {
        "9:25": "09:45",
        "09:25": "09:45",
        "9:45": "10:30",
        "09:45": "10:30",
        "10:30": "11:20",
        "11:20": "13:30",
        "13:30": "14:30",
        "14:40": "15:10",
        "14:30": "15:10",
        "15:10": "明日开盘",
    }.get(str(checkpoint), "下一 checkpoint")
    watches = []
    if confirmed:
        watches.append(f"{next_name} 检查 {confirmed[0]['name']} 是否维持前排且中军/VWAP 不走弱")
    if improving:
        watches.append(f"{next_name} 检查 {improving[0]['name']} 是否从脉冲升级为连续性")
    if weakening:
        watches.append(f"{next_name} 检查 {weakening[0]['name']} 是否继续跌出前排或出现回流")
    p0 = [item for item in portfolio_priority if item.get("priority") == "P0"]
    if p0:
        watches.append(f"{next_name} 优先复核持仓 {p0[0]['stock']} 的风险触发条件")
    if not watches:
        watches.append(f"{next_name} 等待板块排名、VWAP 承接和持仓风险条件给出更明确方向")
    return watches


def _confirm_if(row: dict[str, Any]) -> str:
    sector = _sector_name(row)
    vwap = "维持 VWAP 上方"
    stock = _stock_name(row)
    if sector:
        return f"{stock} {vwap}，且 {sector} 不跌出前排"
    return f"{stock} {vwap}，尾盘不明显回落"


def _invalidate_if(row: dict[str, Any]) -> str:
    stock = _stock_name(row)
    return f"{stock} 跌回 VWAP 下方，或高点回撤继续扩大"
