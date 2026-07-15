from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd


DEFAULT_MODEL = os.environ.get("K_DESK_AI_MODEL", "gpt-5.4-mini")
DEFAULT_PROVIDER = os.environ.get("K_DESK_AI_PROVIDER", "mock")
DEFAULT_TIMEOUT = int(os.environ.get("K_DESK_AI_TIMEOUT_SECONDS", "240"))
DEFAULT_CHUNK_SIZE = int(os.environ.get("K_DESK_AI_CHUNK_SIZE", "220"))
MAX_DIRECT_TRADES = int(os.environ.get("K_DESK_AI_MAX_DIRECT_TRADES", "300"))
MAX_FULL_CHUNK_TRADES = int(os.environ.get("K_DESK_AI_MAX_FULL_CHUNK_TRADES", "1200"))
DEFAULT_AI_TRADE_SAMPLE_LIMIT = int(os.environ.get("K_DESK_AI_TRADE_SAMPLE_LIMIT", "220"))
DEFAULT_RESPONSE_FORMAT = os.environ.get("K_DESK_AI_RESPONSE_FORMAT", "json_object").strip().lower()

MODEL_PRICES = {
    "gpt-5.4-mini": {"input_per_m": 0.75, "cached_input_per_m": 0.075, "output_per_m": 4.50},
    "gpt-5.4-nano": {"input_per_m": 0.20, "cached_input_per_m": 0.02, "output_per_m": 1.60},
}

DEFAULT_API_CONFIG = Path(os.environ.get("K_DESK_AI_CONFIG", r"D:\risk\api.txt"))
ProgressCallback = Callable[[str, str, int], None]

TRADE_COLUMNS = [
    "Ticket",
    "Open Time",
    "Close Time",
    "Type",
    "Volume",
    "Item",
    "Open Price",
    "Close Price",
    "Commission",
    "Taxes",
    "Swap",
    "Profit",
    "S/L",
    "T/P",
    "Comment",
    "Holding Seconds",
]

DEFAULT_REVIEW_RUBRIC = {
    "holding_time": "观察持仓时间分布、极短持仓占比、短持仓订单是否集中发生。",
    "order_clustering": "观察开仓和平仓是否在短时间窗口内密集发生，是否存在同向或反向集中订单段。",
    "volume_progression": "观察手数变化、亏损后是否扩大手数、是否存在网格化或阶梯式加仓。",
    "profit_loss_distribution": "观察盈利/亏损分布、盈利是否高度集中、单笔或少数订单是否贡献主要结果。",
    "stop_loss_take_profit": "观察止损止盈使用、平仓点是否集中靠近固定价格或异常窗口。",
    "market_context_limits": "说明缺少外部报价、盘口深度、成交回报和跨平台报价时，不能直接证明推盘或跨平台打点差。",
}

REFERENCE_RISK_LABELS: dict[str, str] = {}

ACCOUNT_CLASS_DEFINITIONS = {
    "B": "优质客户/正常客户：正常做单，未见明显规则滥用证据；可能符合普通散户逻辑，例如亏损后加仓、逆势扛单、盈利能力不强。",
    "M": "轻度问题观察客户：有一定异常或风险苗头，但证据不足以认定为严重问题；建议观察，可轻微加点差。",
    "P": "中度问题客户：异常比M更稳定或更重复，建议比M更强的点差/风控干预，但仍未达到abuser定性。",
    "T": "Abuser/规则滥用客户：疑似或明显利用平台规则、报价、赠金、返佣、延迟、对锁等机制获利，需要重点处置。",
    "A": "外包/外部承包客户：交易风险或管理成本过高，不适合常规内部风险池处理，建议承包给外部或单独处理。",
}

ABUSE_TYPOLOGY = {
    "market_pushing": "推盘：短时间同向密集下单，可能影响局部价格或流动性；缺盘口/深度时只能判疑似。",
    "quote_latency_arbitrage": "报价延迟套利：极短持仓、快速稳定盈利、集中在报价异常窗口；缺外部报价时只能判疑似。",
    "cross_platform_spread_arbitrage": "跨平台点差套利：利用不同平台报价/点差差异交易；需要外部报价证据确认。",
    "rebate_churning": "刷返佣：高频开平、利润不依赖方向判断，更像为交易量/返佣服务。",
    "bonus_arbitrage": "赠金套利：利用赠金规则构造高风险或对冲交易；需要赠金、入金、出金规则数据确认。",
    "short_close_trading": "短平交易：大量秒级/分钟级快进快出，尤其短持仓盈利集中。",
    "internal_lock_arbitrage": "平台内对锁套利：同品种反向仓位重叠，利用锁仓、返佣、规则差异或风险转移。",
    "high_leverage_lock_arbitrage": "高杠杆锁仓套利：高并发仓位/大手数锁仓，放大规则收益或转移风险；缺杠杆数据时只能判疑似。",
    "weekend_gap_trading": "周末跳空交易：集中在周五收盘前或周一开盘附近下注跳空。",
    "open_betting": "赌开盘：集中在交易日开盘附近押方向或利用流动性薄弱窗口。",
}

MODEL_OUTPUT_FIELDS = {
    "schema_version",
    "analysis_id",
    "stem",
    "provider",
    "model",
    "created_at",
    "privacy",
    "summary",
    "short_summary",
    "account_class",
    "account_class_reason",
    "risk_level",
    "violation_judgment",
    "behavior_definition",
    "inferred_intent",
    "suspected_categories",
    "suspected_abuse_types",
    "key_metric_interpretation",
    "evidence_orders",
    "evidence_segments",
    "explanation",
    "limitations",
    "need_quote_audit",
    "quote_audit_requests",
    "data_requests",
    "suggested_ledger_note",
    "conclusion",
}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def stem_from_trades_path(path: Path) -> str:
    name = path.name
    suffix = "_trades.csv"
    if not name.endswith(suffix):
        raise ValueError(f"trades file must end with {suffix}: {path}")
    return name[: -len(suffix)]


def stable_analysis_id(stem: str) -> str:
    return hashlib.sha256(stem.encode("utf-8")).hexdigest()[:16]


def clean_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ")
    if isinstance(value, float):
        if math.isfinite(value):
            return round(value, 8)
        return None
    return value


def load_sanitized_trades(trades_path: Path) -> pd.DataFrame:
    df = pd.read_csv(trades_path)
    keep = [col for col in TRADE_COLUMNS if col in df.columns]
    if not keep:
        raise ValueError(f"no supported trade columns found: {trades_path}")
    out = df[keep].copy()
    for col in ["Open Time", "Close Time"]:
        if col in out.columns:
            out[col] = out[col].astype(str)
    return out


def numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce").dropna()


def summarize_trades(df: pd.DataFrame) -> dict[str, Any]:
    profit = numeric_series(df, "Profit")
    hold = numeric_series(df, "Holding Seconds")
    volume = numeric_series(df, "Volume")
    symbols = sorted(str(item) for item in df["Item"].dropna().unique()) if "Item" in df.columns else []
    return {
        "trade_count": int(len(df)),
        "symbols": symbols,
        "start": str(df["Open Time"].min()) if "Open Time" in df.columns and len(df) else "",
        "end": str(df["Close Time"].max()) if "Close Time" in df.columns and len(df) else "",
        "profit_sum": round(float(profit.sum()), 2) if len(profit) else 0.0,
        "profit_median": round(float(profit.median()), 2) if len(profit) else 0.0,
        "profit_positive_count": int((profit > 0).sum()) if len(profit) else 0,
        "profit_negative_count": int((profit < 0).sum()) if len(profit) else 0,
        "holding_seconds_median": round(float(hold.median()), 2) if len(hold) else None,
        "holding_seconds_min": round(float(hold.min()), 2) if len(hold) else None,
        "short_hold_count_60s": int((hold <= 60).sum()) if len(hold) else 0,
        "short_hold_count_300s": int((hold <= 300).sum()) if len(hold) else 0,
        "volume_min": round(float(volume.min()), 4) if len(volume) else None,
        "volume_max": round(float(volume.max()), 4) if len(volume) else None,
    }


def trade_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = df.to_dict(orient="records")
    return [{key: clean_value(value) for key, value in row.items()} for row in rows]


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["_profit"] = pd.to_numeric(out.get("Profit"), errors="coerce")
    out["_hold"] = pd.to_numeric(out.get("Holding Seconds"), errors="coerce")
    out["_volume"] = pd.to_numeric(out.get("Volume"), errors="coerce")
    if "Open Time" in out.columns:
        out["_open_dt"] = pd.to_datetime(out["Open Time"], errors="coerce")
        out = out.sort_values("_open_dt", kind="stable")
    out["_prev_profit"] = out["_profit"].shift(1)
    out["_prev_volume"] = out["_volume"].shift(1)
    out["_volume_ratio_prev"] = out["_volume"] / out["_prev_volume"].replace(0, pd.NA)
    return out


def derived_feature_summary(df: pd.DataFrame) -> dict[str, Any]:
    work = add_features(df)
    martingale_candidates = work[(work["_prev_profit"] < 0) & (work["_volume_ratio_prev"] >= 1.5)]
    short_profitable = work[(work["_hold"] <= 300) & (work["_profit"] > 0)]
    same_minute_bursts = 0
    if "_open_dt" in work.columns:
        minute_counts = work["_open_dt"].dt.floor("min").value_counts()
        same_minute_bursts = int((minute_counts >= 5).sum())
    return {
        "martingale_candidate_count": int(len(martingale_candidates)),
        "short_profitable_count_300s": int(len(short_profitable)),
        "same_minute_burst_count_ge5": same_minute_bursts,
        "top_profit_tickets": top_ticket_rows(work, "_profit", 8, ascending=False),
        "largest_loss_tickets": top_ticket_rows(work, "_profit", 8, ascending=True),
        "short_hold_tickets": top_ticket_rows(work, "_hold", 8, ascending=True),
    }


def top_ticket_rows(df: pd.DataFrame, column: str, limit: int, ascending: bool) -> list[dict[str, Any]]:
    if column not in df.columns:
        return []
    rows = []
    for _, row in df.sort_values(column, ascending=ascending).head(limit).iterrows():
        rows.append(
            {
                "ticket": str(clean_value(row.get("Ticket", "")) or ""),
                "open_time": str(clean_value(row.get("Open Time", "")) or ""),
                "close_time": str(clean_value(row.get("Close Time", "")) or ""),
                "type": str(clean_value(row.get("Type", "")) or ""),
                "volume": clean_value(row.get("Volume")),
                "profit": clean_value(row.get("Profit")),
                "holding_seconds": clean_value(row.get("Holding Seconds")),
            }
        )
    return rows


def round_float(value: Any, digits: int = 4) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def safe_ratio(numerator: Any, denominator: Any, digits: int = 4) -> float:
    try:
        den = float(denominator)
        if den == 0 or not math.isfinite(den):
            return 0.0
        num = float(numerator)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(num):
        return 0.0
    return round(num / den, digits)


def max_count_in_window(times: list[pd.Timestamp], seconds: int) -> int:
    valid = sorted(ts for ts in times if pd.notna(ts))
    if not valid:
        return 0
    left = 0
    best = 0
    for right, ts in enumerate(valid):
        while left <= right and (ts - valid[left]).total_seconds() > seconds:
            left += 1
        best = max(best, right - left + 1)
    return int(best)


def max_consecutive(values: list[float], predicate) -> int:
    best = current = 0
    for value in values:
        if predicate(value):
            current += 1
            best = max(best, current)
        else:
            current = 0
    return int(best)


def score_level(score: float) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    if score >= 20:
        return "low"
    return "none"


def clamp_score(value: float) -> int:
    if not math.isfinite(value):
        return 0
    return int(max(0, min(100, round(value))))


def score_entry(score: float, evidence: dict[str, Any], limitations: list[str] | None = None) -> dict[str, Any]:
    score_value = clamp_score(score)
    return {
        "score": score_value,
        "level": score_level(score_value),
        "evidence": evidence,
        "limitations": limitations or [],
    }


def direction_series(work: pd.DataFrame) -> pd.Series:
    if "Type" not in work.columns:
        return pd.Series([""] * len(work), index=work.index)
    return work["Type"].astype(str).str.lower()


def overlap_metrics(work: pd.DataFrame) -> dict[str, Any]:
    if "_open_dt" not in work.columns or "Close Time" not in work.columns:
        return {"max_concurrent_positions": 0, "max_opposite_locked_pairs": 0, "locked_event_count": 0}
    data = work.copy()
    data["_close_dt"] = pd.to_datetime(data["Close Time"], errors="coerce")
    data["_direction"] = direction_series(data)
    events: list[tuple[pd.Timestamp, int, str, str]] = []
    for _, row in data.iterrows():
        symbol = str(row.get("Item", ""))
        direction = "buy" if str(row.get("_direction", "")).startswith("buy") else "sell" if str(row.get("_direction", "")).startswith("sell") else ""
        if not symbol or not direction or pd.isna(row.get("_open_dt")) or pd.isna(row.get("_close_dt")):
            continue
        events.append((row["_open_dt"], 1, symbol, direction))
        events.append((row["_close_dt"], -1, symbol, direction))
    events.sort(key=lambda item: (item[0], -item[1]))
    state: dict[str, dict[str, int]] = {}
    max_concurrent = 0
    max_locked = 0
    locked_events = 0
    for _, delta, symbol, direction in events:
        bucket = state.setdefault(symbol, {"buy": 0, "sell": 0})
        bucket[direction] = max(0, bucket[direction] + delta)
        concurrent = bucket["buy"] + bucket["sell"]
        locked = min(bucket["buy"], bucket["sell"])
        max_concurrent = max(max_concurrent, concurrent)
        max_locked = max(max_locked, locked)
        if locked:
            locked_events += 1
    return {
        "max_concurrent_positions": int(max_concurrent),
        "max_opposite_locked_pairs": int(max_locked),
        "locked_event_count": int(locked_events),
    }


def calculate_local_risk_indicators(df: pd.DataFrame) -> dict[str, Any]:
    work = add_features(df)
    n = int(len(work))
    if n == 0:
        return {"trade_count": 0}
    profit = work["_profit"].fillna(0)
    hold = work["_hold"].fillna(0)
    volume = work["_volume"].fillna(0)
    open_times = work["_open_dt"].dropna().tolist() if "_open_dt" in work.columns else []
    close_dt = pd.to_datetime(work.get("Close Time"), errors="coerce") if "Close Time" in work.columns else pd.Series(dtype="datetime64[ns]")
    duration_days = 0.0
    if open_times and len(close_dt.dropna()):
        duration_days = max((close_dt.max() - min(open_times)).total_seconds() / 86400, 1 / 24)
    elif open_times:
        duration_days = max((max(open_times) - min(open_times)).total_seconds() / 86400, 1 / 24)

    wins = profit[profit > 0]
    losses = profit[profit < 0]
    gross_profit = float(wins.sum()) if len(wins) else 0.0
    gross_loss = abs(float(losses.sum())) if len(losses) else 0.0
    sorted_profit_abs = profit.abs().sort_values(ascending=False)
    top1_abs = float(sorted_profit_abs.head(1).sum()) if len(sorted_profit_abs) else 0.0
    top5_abs = float(sorted_profit_abs.head(5).sum()) if len(sorted_profit_abs) else 0.0
    total_abs_profit = float(profit.abs().sum())
    short_10 = work[work["_hold"].le(10)]
    short_60 = work[work["_hold"].le(60)]
    short_300 = work[work["_hold"].le(300)]
    short_60_profit = short_60[short_60["_profit"] > 0]
    short_300_profit = short_300[short_300["_profit"] > 0]
    martingale = work[(work["_prev_profit"] < 0) & (work["_volume_ratio_prev"] >= 1.5)]
    direction = direction_series(work)
    buy_count = int(direction.str.startswith("buy").sum())
    sell_count = int(direction.str.startswith("sell").sum())

    intervals = pd.Series(open_times).sort_values().diff().dt.total_seconds().dropna() if open_times else pd.Series(dtype=float)
    active_days = int(pd.Series(open_times).dt.date.nunique()) if open_times else 0
    hour_counts = pd.Series(open_times).dt.hour.value_counts().to_dict() if open_times else {}
    session_counts = {
        "asia_0_7": int(sum(count for hour, count in hour_counts.items() if 0 <= int(hour) <= 7)),
        "europe_8_15": int(sum(count for hour, count in hour_counts.items() if 8 <= int(hour) <= 15)),
        "us_16_23": int(sum(count for hour, count in hour_counts.items() if 16 <= int(hour) <= 23)),
    }
    monday_open = 0
    friday_close = 0
    day_open = 0
    if open_times:
        dt_series = pd.Series(open_times)
        monday_open = int(((dt_series.dt.dayofweek == 0) & (dt_series.dt.hour <= 2)).sum())
        friday_close = int(((dt_series.dt.dayofweek == 4) & (dt_series.dt.hour >= 20)).sum())
        day_open = int((dt_series.dt.minute <= 15).sum())

    overlap = overlap_metrics(work)
    trade_frequency = {
        "duration_days": round_float(duration_days, 3),
        "active_days": active_days,
        "trades_per_day": round_float(n / duration_days if duration_days else n, 2),
        "median_interval_seconds": round_float(intervals.median(), 2) if len(intervals) else None,
        "max_orders_60s": max_count_in_window(open_times, 60),
        "max_orders_300s": max_count_in_window(open_times, 300),
        "max_orders_900s": max_count_in_window(open_times, 900),
        "session_counts": session_counts,
    }
    holding = {
        "median_seconds": round_float(hold.median(), 2),
        "mean_seconds": round_float(hold.mean(), 2),
        "min_seconds": round_float(hold.min(), 2),
        "ratio_le_10s": safe_ratio(len(short_10), n),
        "ratio_le_60s": safe_ratio(len(short_60), n),
        "ratio_le_300s": safe_ratio(len(short_300), n),
        "short_60_profitable_count": int(len(short_60_profit)),
        "short_300_profitable_count": int(len(short_300_profit)),
        "short_300_profit_sum": round_float(short_300_profit["_profit"].sum() if len(short_300_profit) else 0, 2),
    }
    profitability = {
        "net_profit": round_float(profit.sum(), 2),
        "gross_profit": round_float(gross_profit, 2),
        "gross_loss_abs": round_float(gross_loss, 2),
        "profit_factor": round_float(gross_profit / gross_loss, 4) if gross_loss else None,
        "win_rate": safe_ratio(len(wins), n),
        "avg_win": round_float(wins.mean(), 2) if len(wins) else None,
        "avg_loss": round_float(losses.mean(), 2) if len(losses) else None,
        "payoff_ratio": round_float((wins.mean() / abs(losses.mean())) if len(wins) and len(losses) and losses.mean() else 0, 4),
        "top1_abs_profit_concentration": safe_ratio(top1_abs, total_abs_profit),
        "top5_abs_profit_concentration": safe_ratio(top5_abs, total_abs_profit),
        "max_consecutive_wins": max_consecutive(profit.tolist(), lambda value: value > 0),
        "max_consecutive_losses": max_consecutive(profit.tolist(), lambda value: value < 0),
    }
    volume_metrics = {
        "total_lots": round_float(volume.sum(), 4),
        "avg_lots": round_float(volume.mean(), 4),
        "max_lots": round_float(volume.max(), 4),
        "volume_after_loss_increase_count": int(len(martingale)),
        "volume_after_loss_increase_ratio": safe_ratio(len(martingale), n),
        "max_volume_ratio_after_loss": round_float(martingale["_volume_ratio_prev"].max(), 4) if len(martingale) else None,
    }
    direction_metrics = {
        "buy_count": buy_count,
        "sell_count": sell_count,
        "buy_sell_balance": safe_ratio(min(buy_count, sell_count), max(buy_count, sell_count) or 1),
        **overlap,
    }
    sl = work.get("S/L", pd.Series([""] * n)).astype(str).str.strip()
    tp = work.get("T/P", pd.Series([""] * n)).astype(str).str.strip()
    stop_take = {
        "stop_loss_usage_ratio": safe_ratio(((sl != "") & (sl != "0") & (sl.str.lower() != "nan")).sum(), n),
        "take_profit_usage_ratio": safe_ratio(((tp != "") & (tp != "0") & (tp.str.lower() != "nan")).sum(), n),
    }
    event_windows = {
        "monday_first_3h_count": monday_open,
        "friday_after_20_count": friday_close,
        "first_15min_each_hour_count": day_open,
    }
    pattern_scores = {
        "short_close_trading": score_entry(
            safe_ratio(len(short_60), n) * 55 + safe_ratio(len(short_300), n) * 35 + safe_ratio(len(short_300_profit), max(len(short_300), 1)) * 20,
            {"short_60_count": int(len(short_60)), "short_300_count": int(len(short_300)), "short_300_profitable_count": int(len(short_300_profit))},
        ),
        "quote_latency_arbitrage": score_entry(
            safe_ratio(len(short_10[short_10["_profit"] > 0]), max(len(short_10), 1)) * 45
            + safe_ratio(float(short_60_profit["_profit"].sum()) if len(short_60_profit) else 0, gross_profit or 1) * 35
            + safe_ratio(len(short_10), n) * 20,
            {"short_10_count": int(len(short_10)), "short_10_profitable_count": int(len(short_10[short_10["_profit"] > 0])), "short_60_profit_sum": round_float(short_60_profit["_profit"].sum() if len(short_60_profit) else 0, 2)},
            ["缺少外部报价和tick级成交环境，不能确认报价延迟，只能作为疑似指标。"],
        ),
        "cross_platform_spread_arbitrage": score_entry(
            safe_ratio(len(short_60_profit), n) * 45 + safe_ratio(gross_profit, gross_loss or 1) * 15 + safe_ratio(len(set(work.get("Item", []))), 1) * 0,
            {"short_profitable_count_60s": int(len(short_60_profit)), "single_symbol": int(work["Item"].nunique()) == 1 if "Item" in work.columns else None},
            ["缺少跨平台报价源，无法确认点差套利，只能判断交易形态是否接近。"],
        ),
        "market_pushing": score_entry(
            max(0, trade_frequency["max_orders_60s"] - 3) * 8 + max(0, trade_frequency["max_orders_300s"] - 8) * 4,
            {"max_orders_60s": trade_frequency["max_orders_60s"], "max_orders_300s": trade_frequency["max_orders_300s"]},
            ["缺少盘口深度和成交回报，不能确认是否真的推盘。"],
        ),
        "rebate_churning": score_entry(
            min(60, safe_ratio(n, max(duration_days, 1 / 24)) * 0.8) + safe_ratio(len(short_300), n) * 25 + safe_ratio(volume.sum(), max(abs(float(profit.sum())), 1)) * 2,
            {"trades_per_day": trade_frequency["trades_per_day"], "total_lots": volume_metrics["total_lots"], "net_profit": profitability["net_profit"]},
            ["缺少返佣规则和佣金归属数据，不能确认刷返佣。"],
        ),
        "bonus_arbitrage": score_entry(
            10 + safe_ratio(volume.sum(), n or 1) * 2,
            {"total_lots": volume_metrics["total_lots"], "avg_lots": volume_metrics["avg_lots"]},
            ["缺少赠金、入金、出金和活动规则数据，不能确认赠金套利。"],
        ),
        "internal_lock_arbitrage": score_entry(
            overlap["max_opposite_locked_pairs"] * 35 + safe_ratio(overlap["locked_event_count"], max(n * 2, 1)) * 30,
            overlap,
        ),
        "high_leverage_lock_arbitrage": score_entry(
            (
                overlap["max_concurrent_positions"] * 6
                + overlap["max_opposite_locked_pairs"] * 25
                + safe_ratio(volume.max(), max(volume.mean(), 0.01)) * 5
            )
            if overlap["max_opposite_locked_pairs"] >= 2 and overlap["max_concurrent_positions"] >= 5
            else min(25, overlap["max_opposite_locked_pairs"] * 12 + safe_ratio(volume.max(), max(volume.mean(), 0.01)) * 4),
            {**overlap, "max_lots": volume_metrics["max_lots"], "avg_lots": volume_metrics["avg_lots"]},
            ["缺少账户杠杆、保证金和权益数据，不能确认高杠杆套利。"],
        ),
        "weekend_gap_trading": score_entry(
            safe_ratio(monday_open + friday_close, n) * 100,
            event_windows,
            ["仅按报表时间窗口识别周末/开盘附近交易，需结合交易品种实际开收盘时间确认。"],
        ),
        "open_betting": score_entry(
            safe_ratio(day_open, n) * 70,
            event_windows,
            ["仅按每小时前15分钟做代理指标，实际开盘窗口需按品种交易时间确认。"],
        ),
    }
    max_abuse_score = max((entry["score"] for entry in pattern_scores.values()), default=0)
    if max_abuse_score >= 75:
        local_class = "T"
    elif max_abuse_score >= 55 or holding["ratio_le_300s"] >= 0.45 or volume_metrics["volume_after_loss_increase_ratio"] >= 0.12:
        local_class = "P"
    elif max_abuse_score >= 30 or holding["ratio_le_300s"] >= 0.2 or volume_metrics["volume_after_loss_increase_ratio"] >= 0.05:
        local_class = "M"
    else:
        local_class = "B"
    if overlap["max_opposite_locked_pairs"] >= 3 and overlap["max_concurrent_positions"] >= 12:
        local_class = "A"
    return {
        "trade_count": n,
        "trade_frequency": trade_frequency,
        "holding": holding,
        "profitability": profitability,
        "volume_and_martingale": volume_metrics,
        "direction_and_locking": direction_metrics,
        "stop_take_profit": stop_take,
        "event_windows": event_windows,
        "pattern_scores": pattern_scores,
        "local_class_candidate": local_class,
        "local_class_reason": "本地候选分类仅由统计阈值生成，供模型复核，不作为最终定性。",
    }


def select_high_signal_trades(df: pd.DataFrame, limit: int = DEFAULT_AI_TRADE_SAMPLE_LIMIT) -> pd.DataFrame:
    work = add_features(df)
    if len(work) <= limit:
        return work.drop(columns=[col for col in work.columns if col.startswith("_")], errors="ignore")
    buckets = [
        work[work["_hold"].le(60)].sort_values("_profit", ascending=False).head(80),
        work[work["_hold"].le(300)].sort_values("_hold", ascending=True).head(80),
        work[(work["_prev_profit"] < 0) & (work["_volume_ratio_prev"] >= 1.5)].head(80),
        work.sort_values("_profit", ascending=False).head(60),
        work.sort_values("_profit", ascending=True).head(60),
        work.tail(60),
    ]
    selected = pd.concat(buckets, ignore_index=True)
    if "Ticket" in selected.columns:
        selected = selected.drop_duplicates(subset=["Ticket"])
    else:
        selected = selected.drop_duplicates()
    selected = selected.head(limit)
    return selected.drop(columns=[col for col in selected.columns if col.startswith("_")], errors="ignore")


def split_trade_chunks(df: pd.DataFrame, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[pd.DataFrame]:
    if len(df) <= MAX_DIRECT_TRADES:
        return [df]
    if "Open Time" in df.columns:
        work = df.copy()
        work["_open_dt"] = pd.to_datetime(work["Open Time"], errors="coerce")
        work = work.sort_values("_open_dt", kind="stable").drop(columns=["_open_dt"])
    else:
        work = df
    return [work.iloc[i : i + chunk_size].copy() for i in range(0, len(work), chunk_size)]


def estimate_tokens_for_payload(payload: dict[str, Any]) -> int:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # Conservative mixed Chinese/JSON approximation.
    return max(1, int(len(text) / 2.8))


def estimate_cost_for_payload(
    payload: dict[str, Any],
    df: pd.DataFrame,
    model: str = DEFAULT_MODEL,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> dict[str, Any]:
    input_tokens = estimate_tokens_for_payload(payload)
    output_tokens = 3200
    price = MODEL_PRICES.get(model, MODEL_PRICES["gpt-5.4-mini"])
    estimated = input_tokens / 1_000_000 * price["input_per_m"] + output_tokens / 1_000_000 * price["output_per_m"]
    sample_policy = payload.get("sample_policy") if isinstance(payload, dict) else {}
    sampled_trade_count = sample_policy.get("sampled_trade_count") if isinstance(sample_policy, dict) else None
    return {
        "model": model,
        "trade_count": int(len(df)),
        "api_call_count": 1,
        "sampled_trade_count": int(sampled_trade_count if sampled_trade_count is not None else len(select_high_signal_trades(df))),
        "chunk_count": 1,
        "chunk_size": chunk_size,
        "estimated_input_tokens": int(input_tokens),
        "estimated_output_tokens": int(output_tokens),
        "estimated_cost_usd": round(float(estimated), 4),
        "price": price,
    }


def estimate_cost(df: pd.DataFrame, model: str = DEFAULT_MODEL, chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict[str, Any]:
    payload = build_direct_analysis_prompt("estimate", {}, df)
    return estimate_cost_for_payload(payload, df, model, chunk_size)


def system_prompt() -> str:
    return (
        "你是资深金融交易风控复核人员。"
        "本地系统已经完成关键统计和二级风控指标计算，你必须把local_metrics视为权威计算结果，不要重新心算或改写数值。"
        "你的任务不是堆砌专业术语，而是像人工风控复核一样，把账户行为讲成一条清楚的证据链：先说定级，再说为什么，再说为什么不能升级或降级，最后给处置建议。"
        "分析必须围绕可验证事实展开：具体订单、时间段、持仓秒数、手数、盈亏、胜率、profit factor、短持仓占比、成组订单、方向结构、锁仓/加仓/返佣/赠金/外部报价证据。"
        "每一个风险判断都要能回答三个问题：这个账户哪里不像普通客户？这些证据支持到B/M/P/T/A哪一级？还缺什么证据才能确认更严重的违规？"
        "不要写空泛表达，例如“存在一定风险”“需要结合上下文”“疑似异常模式”但不解释原因。不要绕圈重复同一指标。不要把local_metrics逐项机械复述。"
        "分类必须证据驱动：没有外部报价、盘口深度、成交回报、赠金/返佣规则、杠杆权益数据时，只能写疑似或证据不足，不能写已确认。"
        "如果交易形态明显强于普通散户，但缺少确认abuse的外部证据，应优先考虑M/P，而不是在B和T之间跳跃。P适合：异常明确、重复出现、建议加点差观察，但证据不足以定T。"
        "可以推测用户意图，但必须以“可能/疑似/更像”表达，并说明依据和置信度，不能把主观推测当事实。"
        "short_summary和conclusion必须高度凝练：用1到2句中文，先给用户特征标签，再说核心问题和建议等级。"
        "behavior_definition要定义交易风格和风险画像；inferred_intent要解释可能意图；key_metric_interpretation只解释关键指标如何支持或反驳结论；explanation必须按结论、证据链、反证、定级理由、建议动作组织。"
        "输出必须是严格JSON，不要输出Markdown。不要输出plan、草稿、思考步骤、进度JSON或任何第二个JSON对象；只能输出最终分析JSON对象。不要输出真实账号、客户个人信息或任何输入中不存在的字段。"
    )


def output_schema_instruction() -> str:
    return (
        "返回严格JSON字段：schema_version, analysis_id, stem, provider, model, created_at, privacy, summary, local_metrics, "
        "short_summary, account_class, account_class_reason, risk_level, violation_judgment, behavior_definition, inferred_intent, "
        "suspected_categories, suspected_abuse_types, key_metric_interpretation, evidence_orders, evidence_segments, "
        "explanation, limitations, suggested_ledger_note。必须包含conclusion字段。account_class只能是B/M/P/T/A。"
        "short_summary和conclusion必须非常短，只能1到2句；格式类似“短线黄金高胜率账户，成组短平盈利明显；证据不足以定T，建议P加点差观察。”"
        "account_class_reason必须直接说明为什么是该等级，以及为什么不是更低或更高等级。"
        "behavior_definition写交易风格和风险画像：账户像什么类型的交易者，和普通散户/abuser的区别在哪里。"
        "inferred_intent写可能意图：用户可能在捕捉什么窗口、用什么方式获利、哪些只是推测。"
        "key_metric_interpretation只解释关键指标，不要逐项复述全部local_metrics；每个指标都必须说明它支持或反驳哪个结论。"
        "explanation必须用连贯自然语言写成5段逻辑：1结论和建议等级；2核心异常证据链；3关键订单/时间段；4反证和证据缺口；5建议动作。"
        "risk_level只能是：低、中、高、严重。violation_judgment只能是：未见违规、疑似违规、较大概率违规、证据不足。"
        "suspected_categories和suspected_abuse_types可以为空数组；不得因看到分类口径就强行归类。"
        "evidence_orders内每项必须包含真实存在的ticket、open_time、close_time、reason、confidence。reason不能只说“高信号订单”，必须说明该订单如何支持证据链。"
        "evidence_segments用于成组订单或关键时间窗口；每项应说明该时间段为什么重要。"
        "limitations必须列出无法确认的部分，例如外部报价、盘口深度、成交回报、返佣/赠金、杠杆权益。"
        "不要输出plan字段、进度字段、草稿字段或多个JSON对象；不要把输出字段放入local_metrics内部；local_metrics只能保留输入里的本地指标。"
    )


def analysis_style_reference() -> dict[str, Any]:
    return {
        "purpose": "Use this as the preferred reasoning style. Do not copy account-specific facts unless supported by the current input.",
        "structure": [
            "结论：一句话给账户画像、等级和建议动作。",
            "为什么不是普通客户：用胜率、profit factor、短持仓、成组订单等说明异常点。",
            "核心异常点：把指标和具体订单串成证据链，而不是罗列指标。",
            "可能的交易意图：说明更像什么策略，以及哪些只是推测。",
            "为什么不能升级到T：列出缺少的外部证据和反证。",
            "为什么不是更低等级：说明异常重复性和处置必要性。",
            "建议动作：给出加点差/观察/升级复核条件。",
        ],
        "example_tone": (
            "短线黄金高胜率账户，成组短平盈利明显，疑似策略化捕捉报价/波动窗口；"
            "当前证据不足以定T，建议P加点差观察。分析应解释该账户哪里不像普通散户，"
            "哪些订单构成证据链，为什么还不能确认跨平台套利或报价延迟套利。"
        ),
        "bad_patterns_to_avoid": [
            "只说存在风险但不说明风险来自哪些订单和指标。",
            "把local_metrics逐项复述成指标清单。",
            "一边说证据不足，一边直接定T且不给反证逻辑。",
            "把缺少外部报价的推测写成已确认事实。",
            "证据订单reason只写高信号订单、需结合K线等空话。",
        ],
    }


def output_schema_instruction() -> str:
    return (
        "Return one strict JSON object only. Required fields: schema_version, analysis_id, stem, provider, model, "
        "created_at, privacy, summary, local_metrics, short_summary, conclusion, account_class, account_class_reason, "
        "risk_level, violation_judgment, behavior_definition, inferred_intent, suspected_categories, "
        "suspected_abuse_types, key_metric_interpretation, evidence_orders, evidence_segments, explanation, "
        "limitations, suggested_ledger_note, need_quote_audit, quote_audit_requests, data_requests. "
        "account_class must be one of B/M/P/T/A. risk_level must be one of 低/中/高/严重. "
        "violation_judgment must be one of 未见违规/疑似违规/较大概率违规/证据不足. "
        "short_summary and conclusion must be concise Chinese, 1-2 sentences. "
        "For every quote_audit_requests or data_requests item, you must answer two business questions clearly in Chinese: "
        "1) 为什么要这些数据; 2) 拿到这些数据会得到什么风控结果. Do not write vague requests such as only "
        "'need external quotes', 'need execution logs', or 'may affect classification'. "
        "If missing evidence may materially affect M/P/T/A classification, set need_quote_audit=true and fill "
        "quote_audit_requests. If quote audit is not needed, set need_quote_audit=false and quote_audit_requests=[]. "
        "quote_audit_requests is an array of objects with fields: reason_code, symbol, start, end, timeframes, "
        "related_tickets, current_uncertainty, data_to_check, why_needed, pass_condition, fail_condition, "
        "if_confirmed_conclusion, if_not_confirmed_conclusion, classification_impact, priority, question. "
        "Request at most 3 quote windows. Each quote request must be tied to specific tickets or evidence_segments. "
        "Do not request full-history quotes. Prefer bounded windows: M1 <= 2 hours, M5 <= 12 hours, M15 <= 3 days, "
        "H1 <= 30 days, H4 <= 90 days. "
        "data_requests is an array of non-quote missing evidence requests, each with fields: data_type, "
        "current_uncertainty, data_to_check, why_needed, pass_condition, fail_condition, if_confirmed_conclusion, "
        "if_not_confirmed_conclusion, classification_impact, priority. Use it for external quotes, tick/execution logs, "
        "depth, slippage, rebate/bonus rules, leverage/margin/equity, deposits/withdrawals, or account linkage. "
        "Field meanings: current_uncertainty=当前无法确认的具体问题; data_to_check=要核查的数据表/字段/时间范围; "
        "why_needed=为什么这个数据能解决不确定点; pass_condition=数据出现什么特征就支持风险假设; "
        "fail_condition=数据出现什么特征就削弱或反驳风险假设; if_confirmed_conclusion=满足pass_condition后得到的风控结论; "
        "if_not_confirmed_conclusion=满足fail_condition后应如何降级、排除或维持观察; classification_impact=对B/M/P/T/A定级和处置的具体影响. "
        "limitations must still list what cannot be confirmed. Do not output markdown, plan, progress, draft, "
        "or multiple JSON objects."
    )


def quote_cache_files(out_dir: Path, stem: str) -> list[Path]:
    return sorted(Path(out_dir).glob(f"{stem}_*_quote_cache_*.csv"))


def infer_report_symbol_from_cache(stem: str, path: Path) -> str:
    name = path.name
    prefix = f"{stem}_"
    marker = "_quote_cache_"
    if name.startswith(prefix) and marker in name:
        return name[len(prefix) : name.index(marker)]
    return path.stem


def quote_bar_summary(bars: pd.DataFrame, timeframe: str) -> dict[str, Any]:
    if bars.empty:
        return {"timeframe": timeframe, "rows": 0}
    work = bars.copy()
    work["range"] = (work["high"] - work["low"]).abs()
    return {
        "timeframe": timeframe,
        "rows": int(len(work)),
        "start": str(work["time"].min()),
        "end": str(work["time"].max()),
        "avg_range": round_float(work["range"].mean(), 5),
        "median_range": round_float(work["range"].median(), 5),
        "p95_range": round_float(work["range"].quantile(0.95), 5) if len(work) >= 20 else round_float(work["range"].max(), 5),
        "max_range": round_float(work["range"].max(), 5),
        "avg_spread": round_float(work["spread"].mean(), 5) if "spread" in work.columns else None,
        "max_spread": round_float(work["spread"].max(), 5) if "spread" in work.columns else None,
    }


def resample_bars(bars: pd.DataFrame, rule: str) -> pd.DataFrame:
    if bars.empty:
        return bars
    work = bars.set_index("time").sort_index()
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "spread" in work.columns:
        agg["spread"] = "mean"
    out = work.resample(rule).agg(agg).dropna(subset=["open", "high", "low", "close"]).reset_index()
    return out


def price_position(price: Any, low: Any, high: Any) -> float | None:
    try:
        p = float(price)
        lo = float(low)
        hi = float(high)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(p) or not math.isfinite(lo) or not math.isfinite(hi) or hi == lo:
        return None
    return round((p - lo) / (hi - lo), 4)


def sampled_trade_quote_context(sampled: pd.DataFrame, bars_by_symbol: dict[str, pd.DataFrame], limit: int = 30) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    if sampled.empty or not bars_by_symbol:
        return contexts
    for _, row in sampled.head(limit).iterrows():
        symbol = str(row.get("Item", ""))
        bars = bars_by_symbol.get(symbol)
        if bars is None or bars.empty:
            continue
        open_dt = pd.to_datetime(row.get("Open Time"), errors="coerce")
        close_dt = pd.to_datetime(row.get("Close Time"), errors="coerce")
        if pd.isna(open_dt):
            continue
        minute = open_dt.floor("min")
        match = bars[bars["time"].eq(minute)]
        if match.empty:
            continue
        bar = match.iloc[0]
        open_price = clean_value(row.get("Open Price"))
        close_price = clean_value(row.get("Close Price"))
        after_1m = bars[bars["time"].eq(minute + pd.Timedelta(minutes=1))]
        after_5m = bars[bars["time"].eq(minute + pd.Timedelta(minutes=5))]
        hold_window = bars[(bars["time"] >= minute) & (bars["time"] <= close_dt.floor("min"))] if pd.notna(close_dt) else pd.DataFrame()
        contexts.append(
            {
                "ticket": str(clean_value(row.get("Ticket", "")) or ""),
                "symbol": symbol,
                "open_time": str(clean_value(row.get("Open Time", "")) or ""),
                "close_time": str(clean_value(row.get("Close Time", "")) or ""),
                "holding_seconds": clean_value(row.get("Holding Seconds")),
                "profit": clean_value(row.get("Profit")),
                "m1_at_open": {
                    "time": str(bar["time"]),
                    "open": round_float(bar["open"], 5),
                    "high": round_float(bar["high"], 5),
                    "low": round_float(bar["low"], 5),
                    "close": round_float(bar["close"], 5),
                    "range": round_float(float(bar["high"]) - float(bar["low"]), 5),
                    "spread": round_float(bar.get("spread"), 5) if "spread" in bar else None,
                },
                "open_price_position_in_m1": price_position(open_price, bar["low"], bar["high"]),
                "close_price_position_in_m1": price_position(close_price, bar["low"], bar["high"]),
                "move_after_open_1m": round_float(float(after_1m.iloc[0]["close"]) - float(open_price), 5) if len(after_1m) and open_price is not None else None,
                "move_after_open_5m": round_float(float(after_5m.iloc[0]["close"]) - float(open_price), 5) if len(after_5m) and open_price is not None else None,
                "hold_window_m1_count": int(len(hold_window)) if not hold_window.empty else 0,
                "hold_window_max_range": round_float((hold_window["high"] - hold_window["low"]).max(), 5) if not hold_window.empty else None,
            }
        )
    return contexts


def build_market_context(stem: str, out_dir: Path, df: pd.DataFrame, sampled: pd.DataFrame) -> dict[str, Any]:
    files = quote_cache_files(out_dir, stem)
    if not files:
        return {"available": False, "reason": "quote cache not found"}
    mapping_path = out_dir / f"{stem}_mapping.json"
    mapping = {}
    if mapping_path.exists():
        try:
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        except Exception as exc:
            mapping = {"error": str(exc)}
    summaries = []
    bars_by_symbol: dict[str, pd.DataFrame] = {}
    for path in files:
        symbol = infer_report_symbol_from_cache(stem, path)
        try:
            bars = pd.read_csv(path)
            bars["time"] = pd.to_datetime(bars["time"], errors="coerce")
            for col in ["open", "high", "low", "close", "spread"]:
                if col in bars.columns:
                    bars[col] = pd.to_numeric(bars[col], errors="coerce")
            bars = bars.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time")
        except Exception as exc:
            summaries.append({"symbol": symbol, "cache_file": path.name, "error": str(exc)})
            continue
        if bars.empty:
            summaries.append({"symbol": symbol, "cache_file": path.name, "error": "empty quote cache"})
            continue
        bars_by_symbol[symbol] = bars
        summaries.append(
            {
                "symbol": symbol,
                "cache_file": path.name,
                "m1": quote_bar_summary(bars, "M1"),
                "h1": quote_bar_summary(resample_bars(bars, "1h"), "H1"),
                "h4": quote_bar_summary(resample_bars(bars, "4h"), "H4"),
                "alignment": mapping.get(symbol, {}) if isinstance(mapping, dict) else {},
            }
        )
    return {
        "available": bool(summaries),
        "source": "local_quote_cache",
        "quote_cache_count": len(files),
        "symbols": summaries,
        "sampled_trade_quote_context": sampled_trade_quote_context(sampled, bars_by_symbol),
        "quote_request_policy": {
            "enabled_design": True,
            "max_requests_per_analysis": 3,
            "note": "If evidence remains insufficient, the model may request a bounded quote audit window; full quote history is not sent by default.",
        },
    }


def load_quote_bars_by_symbol(stem: str, out_dir: Path) -> dict[str, pd.DataFrame]:
    bars_by_symbol: dict[str, pd.DataFrame] = {}
    for path in quote_cache_files(out_dir, stem):
        symbol = infer_report_symbol_from_cache(stem, path)
        try:
            bars = pd.read_csv(path)
            bars["time"] = pd.to_datetime(bars["time"], errors="coerce")
            for col in ["open", "high", "low", "close", "spread"]:
                if col in bars.columns:
                    bars[col] = pd.to_numeric(bars[col], errors="coerce")
            bars = bars.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time")
        except Exception:
            continue
        if not bars.empty:
            bars_by_symbol[symbol] = bars
    return bars_by_symbol


def safe_datetime(value: Any) -> pd.Timestamp | None:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts


def compact_records(df: pd.DataFrame, limit: int = 60) -> list[dict[str, Any]]:
    if df.empty:
        return []
    use = df.head(limit).copy()
    rows: list[dict[str, Any]] = []
    for _, row in use.iterrows():
        item: dict[str, Any] = {}
        for col in use.columns:
            value = clean_value(row.get(col))
            if col == "time" and value is not None:
                value = str(value)
            item[str(col)] = value
        rows.append(item)
    return rows


def normalize_timeframes(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    elif value:
        raw = [value]
    else:
        raw = ["M1"]
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip().upper()
        if text in {"1M", "1MIN", "M1"}:
            text = "M1"
        elif text in {"5M", "5MIN", "M5"}:
            text = "M5"
        elif text in {"15M", "15MIN", "M15"}:
            text = "M15"
        elif text in {"1H", "H1"}:
            text = "H1"
        elif text in {"4H", "H4"}:
            text = "H4"
        if text in {"M1", "M5", "M15", "H1", "H4"} and text not in out:
            out.append(text)
    return out or ["M1"]


def trades_for_tickets(df: pd.DataFrame, tickets: Any) -> pd.DataFrame:
    if "Ticket" not in df.columns:
        return pd.DataFrame()
    if not isinstance(tickets, list):
        tickets = [tickets] if tickets else []
    wanted = {str(item) for item in tickets if str(item or "").strip()}
    if not wanted:
        return pd.DataFrame()
    return df[df["Ticket"].map(lambda value: str(clean_value(value) or "") in wanted)]


def infer_request_window(req: dict[str, Any], df: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None, str]:
    start = safe_datetime(req.get("start"))
    end = safe_datetime(req.get("end"))
    source = "request"
    if start is None or end is None:
        related = trades_for_tickets(df, req.get("related_tickets"))
        if not related.empty:
            opens = pd.to_datetime(related.get("Open Time"), errors="coerce").dropna()
            closes = pd.to_datetime(related.get("Close Time"), errors="coerce").dropna()
            points = list(opens) + list(closes)
            if points:
                start = min(points) - pd.Timedelta(minutes=2)
                end = max(points) + pd.Timedelta(minutes=2)
                source = "related_tickets"
    if start is not None and end is not None and end < start:
        start, end = end, start
    return start, end, source


def clamp_window(start: pd.Timestamp, end: pd.Timestamp, max_hours: float) -> tuple[pd.Timestamp, pd.Timestamp, bool]:
    max_delta = pd.Timedelta(hours=max_hours)
    if end - start <= max_delta:
        return start, end, False
    return start, start + max_delta, True


def quote_window_result(
    req: dict[str, Any],
    df: pd.DataFrame,
    bars_by_symbol: dict[str, pd.DataFrame],
    index: int,
) -> dict[str, Any]:
    symbol = str(req.get("symbol") or "").strip()
    if symbol not in bars_by_symbol and len(bars_by_symbol) == 1:
        symbol = next(iter(bars_by_symbol))
    start, end, window_source = infer_request_window(req, df)
    result: dict[str, Any] = {
        "request_index": index,
        "reason_code": req.get("reason_code", ""),
        "symbol": symbol or req.get("symbol", ""),
        "requested_start": req.get("start", ""),
        "requested_end": req.get("end", ""),
        "related_tickets": req.get("related_tickets", []),
        "requested_timeframes": normalize_timeframes(req.get("timeframes")),
        "status": "unavailable",
        "source": "local_quote_cache",
        "window_source": window_source,
    }
    if start is None or end is None:
        result["unavailable_reason"] = "Could not determine a bounded time window from request or related tickets."
        return result
    if symbol not in bars_by_symbol:
        result["unavailable_reason"] = "No local quote cache was found for requested symbol."
        result["actual_start"] = str(start)
        result["actual_end"] = str(end)
        return result
    bars = bars_by_symbol[symbol]
    tf_rules = {"M1": ("1min", 2), "M5": ("5min", 12), "M15": ("15min", 72), "H1": ("1h", 720), "H4": ("4h", 2160)}
    timeframe_results: dict[str, Any] = {}
    any_rows = False
    for tf in result["requested_timeframes"]:
        rule, max_hours = tf_rules.get(tf, ("1min", 2))
        ws, we, clamped = clamp_window(start, end, max_hours)
        source_bars = bars if tf == "M1" else resample_bars(bars, rule)
        window = source_bars[(source_bars["time"] >= ws) & (source_bars["time"] <= we)].copy()
        if not window.empty:
            any_rows = True
            window["range"] = (window["high"] - window["low"]).abs()
        timeframe_results[tf] = {
            "status": "fulfilled" if not window.empty else "empty",
            "actual_start": str(ws),
            "actual_end": str(we),
            "clamped": clamped,
            "rows": int(len(window)),
            "summary": quote_bar_summary(window, tf) if not window.empty else {"timeframe": tf, "rows": 0},
            "price_path": {
                "first_open": round_float(window.iloc[0]["open"], 5) if not window.empty else None,
                "last_close": round_float(window.iloc[-1]["close"], 5) if not window.empty else None,
                "min_low": round_float(window["low"].min(), 5) if not window.empty else None,
                "max_high": round_float(window["high"].max(), 5) if not window.empty else None,
                "net_move": round_float(float(window.iloc[-1]["close"]) - float(window.iloc[0]["open"]), 5) if not window.empty else None,
                "max_single_bar_range": round_float(window["range"].max(), 5) if not window.empty else None,
            },
            "sampled_bars": compact_records(window[["time", "open", "high", "low", "close"] + (["spread"] if "spread" in window.columns else [])], 80),
        }
    related = trades_for_tickets(df, req.get("related_tickets"))
    rows_by_timeframe = {tf: item.get("rows", 0) for tf, item in timeframe_results.items()}
    fulfilled_timeframes = [tf for tf, item in timeframe_results.items() if item.get("status") == "fulfilled"]
    result.update(
        {
            "status": "fulfilled" if any_rows else "empty",
            "actual_start": str(start),
            "actual_end": str(end),
            "timeframe_results": timeframe_results,
            "related_trades": trade_records(related) if not related.empty else [],
            "obtained_data_summary": (
                f"已从本地报价缓存补充 {symbol} 在 {start} -> {end} 的OHLC/Spread窗口；"
                f"覆盖周期：{', '.join(f'{tf}={rows_by_timeframe.get(tf, 0)}根' for tf in rows_by_timeframe)}。"
                if any_rows
                else "未在本地报价缓存中找到该窗口的可用K线数据。"
            ),
            "supplemented_evidence_summary": (
                "补充了该时间窗内价格路径、波动范围、点差均值/极值、单根最大波动以及关联订单窗口走势，"
                "用于核查首轮报告中的报价窗口、锁仓链、短持仓盈利或加仓段假设。"
                if any_rows
                else "没有形成可用报价补充证据。"
            ),
            "review_effect": (
                "已作为二次AI复核输入；它可以支持或削弱价格窗口类怀疑，但不能替代tick级bid/ask、成交回报延迟或外部报价对照。"
                if any_rows
                else "未能补充报价证据，二次复核仍需依赖订单统计和其他证据。"
            ),
            "fulfilled_timeframes": fulfilled_timeframes,
            "local_interpretation": (
                "Local quote cache was supplied for the requested bounded window. It contains OHLC/spread bars, "
                "not tick-level bid/ask or execution-log latency. The second model pass must use this data to confirm "
                "or weaken price-window hypotheses, and must leave tick/execution conclusions unresolved if tick/log data is absent."
            ),
        }
    )
    return result


def collect_supplemental_evidence(
    stem: str,
    out_dir: Path,
    df: pd.DataFrame,
    initial_result: dict[str, Any],
) -> dict[str, Any]:
    quote_requests = normalize_dict_list(initial_result.get("quote_audit_requests"))[:3]
    data_requests = normalize_dict_list(initial_result.get("data_requests"))[:8]
    bars_by_symbol = load_quote_bars_by_symbol(stem, out_dir)
    quote_results = [quote_window_result(req, df, bars_by_symbol, index + 1) for index, req in enumerate(quote_requests)]
    data_results: list[dict[str, Any]] = []
    for index, req in enumerate(data_requests, 1):
        data_results.append(
            {
                "request_index": index,
                "data_type": req.get("data_type", ""),
                "priority": req.get("priority", ""),
                "status": "unavailable",
                "source": "not_configured",
                "requested_data": req.get("data_to_check") or req.get("reason") or "",
                "not_obtained_summary": "未拿到该类数据。",
                "why_not_obtained": "当前本地流程没有配置这类数据源或固定导出文件，只能读取已生成的交易CSV和本地报价缓存。",
                "review_effect": "该项不能作为已确认事实；二次AI只能把它作为仍未解决的限制条件，不能据此上调定级。",
                "unavailable_reason": (
                    "This local workflow has no configured source for execution logs, external quotes, depth, "
                    "rebate/bonus rules, deposits/withdrawals, or margin/equity/leverage snapshots. Do not treat "
                    "this request as confirmed evidence."
                ),
            }
        )
    return {
        "enabled": True,
        "stage": "second_pass_supplement",
        "quote_audit_results": quote_results,
        "data_request_results": data_results,
        "summary": {
            "quote_requests_total": len(quote_requests),
            "quote_requests_fulfilled": sum(1 for item in quote_results if item.get("status") == "fulfilled"),
            "quote_requests_empty": sum(1 for item in quote_results if item.get("status") == "empty"),
            "data_requests_total": len(data_requests),
            "data_requests_unavailable": len(data_results),
        },
        "limitations": [
            "Supplemental quote evidence uses local cached OHLC/spread bars only.",
            "Tick-level bid/ask, execution latency, external venue quotes, depth, rebate/bonus, deposit/withdrawal, and margin/equity data are not automatically available unless a data source is later configured.",
        ],
    }


def compact_initial_result_for_second_pass(result: dict[str, Any]) -> dict[str, Any]:
    keep = [
        "schema_version",
        "analysis_id",
        "stem",
        "summary",
        "local_metrics",
        "short_summary",
        "conclusion",
        "account_class",
        "account_class_reason",
        "risk_level",
        "violation_judgment",
        "behavior_definition",
        "inferred_intent",
        "suspected_categories",
        "suspected_abuse_types",
        "key_metric_interpretation",
        "evidence_orders",
        "evidence_segments",
        "explanation",
        "limitations",
        "need_quote_audit",
        "quote_audit_requests",
        "data_requests",
        "suggested_ledger_note",
    ]
    return {key: result.get(key) for key in keep if key in result}


def supplemental_output_instruction() -> str:
    return (
        output_schema_instruction()
        + " This is the second-pass finalization after supplemental evidence. "
        + "Add a top-level supplemental_audit object copied from the supplied supplemental_evidence with your concise "
        + "review_status per request. Distinguish clearly between data actually supplied and data still unavailable. "
        + "If local quote bars resolve a quote request, reduce or remove that quote request from quote_audit_requests; "
        + "if tick/execution/external data remains unavailable, keep the unresolved request and do not claim confirmation. "
        + "Set supplemental_pass_completed=true and api_call_count_expected=2 in the final JSON."
    )


def build_supplemental_prompt(
    stem: str,
    rules: dict[str, str],
    df: pd.DataFrame,
    initial_result: dict[str, Any],
    supplemental_evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task": "finalize_trade_risk_review_after_supplemental_evidence",
        "analysis_id": stable_analysis_id(stem),
        "stem": stem,
        "classification_definitions": ACCOUNT_CLASS_DEFINITIONS,
        "abuse_typology": ABUSE_TYPOLOGY,
        "review_rubric": DEFAULT_REVIEW_RUBRIC,
        "optional_reference_labels": rules,
        "summary": summarize_trades(df),
        "features": derived_feature_summary(df),
        "local_metrics": initial_result.get("local_metrics") or calculate_local_risk_indicators(df),
        "initial_model_result": compact_initial_result_for_second_pass(initial_result),
        "supplemental_evidence": supplemental_evidence,
        "sampled_trades": trade_records(select_high_signal_trades(df)),
        "output_requirements": supplemental_output_instruction(),
    }


def combine_cost_estimates(first: dict[str, Any], second: dict[str, Any] | None = None) -> dict[str, Any]:
    if not second:
        out = dict(first or {})
        out.setdefault("api_call_count", 1)
        return out
    out = dict(first or {})
    out["api_call_count"] = int((first or {}).get("api_call_count") or 1) + int((second or {}).get("api_call_count") or 1)
    out["estimated_input_tokens"] = int((first or {}).get("estimated_input_tokens") or 0) + int((second or {}).get("estimated_input_tokens") or 0)
    out["estimated_output_tokens"] = int((first or {}).get("estimated_output_tokens") or 0) + int((second or {}).get("estimated_output_tokens") or 0)
    out["estimated_cost_usd"] = round_float(float((first or {}).get("estimated_cost_usd") or 0) + float((second or {}).get("estimated_cost_usd") or 0), 6)
    out["supplemental_second_pass"] = second
    return out


def build_direct_analysis_prompt(
    stem: str,
    rules: dict[str, str],
    df: pd.DataFrame,
    market_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sampled = select_high_signal_trades(df)
    local_metrics = calculate_local_risk_indicators(df)
    payload = {
        "task": "professional_account_risk_review",
        "analysis_id": stable_analysis_id(stem),
        "stem": stem,
        "classification_definitions": ACCOUNT_CLASS_DEFINITIONS,
        "abuse_typology": ABUSE_TYPOLOGY,
        "review_rubric": DEFAULT_REVIEW_RUBRIC,
        "analysis_style_reference": analysis_style_reference(),
        "optional_reference_labels": rules,
        "anti_bias_instruction": "先用指标和具体订单建立证据链，再给B/M/P/T/A分类；证据不足必须降级或写明疑似，不能强行认定违规。若异常明确但不能确认abuse，优先考虑M/P并给观察或加点差建议。",
        "summary": summarize_trades(df),
        "features": derived_feature_summary(df),
        "local_metrics": local_metrics,
        "sample_policy": {
            "full_trade_count": int(len(df)),
            "sampled_trade_count": int(len(sampled)),
            "sample_reason": "样本由本地按短持仓、短持仓盈利、亏损后加仓、最大盈利、最大亏损、最近交易等高信号规则抽取；local_metrics覆盖全量交易。",
            "all_trades_included": int(len(sampled)) == int(len(df)),
        },
        "sampled_trades": trade_records(sampled),
        "output_requirements": output_schema_instruction(),
    }
    if market_context:
        payload["market_context"] = market_context
    return payload


def build_chunk_prompt(stem: str, rules: dict[str, str], global_summary: dict[str, Any], chunk: pd.DataFrame, index: int, count: int) -> dict[str, Any]:
    return {
        "task": "analyze_trade_chunk",
        "analysis_id": stable_analysis_id(f"{stem}:{index}"),
        "stem": stem,
        "chunk_index": index,
        "chunk_count": count,
        "review_rubric": DEFAULT_REVIEW_RUBRIC,
        "optional_reference_labels": rules,
        "anti_bias_instruction": "不要从标签出发倒推结论。请先分析数据事实；没有充分证据时，suspected_categories返回空数组，并降低风险等级。",
        "global_summary": global_summary,
        "chunk_summary": summarize_trades(chunk),
        "chunk_features": derived_feature_summary(chunk),
        "trades": trade_records(chunk),
        "output_requirements": output_schema_instruction(),
    }


def build_aggregate_prompt(stem: str, rules: dict[str, str], df: pd.DataFrame, chunk_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "task": "aggregate_trade_risk",
        "analysis_id": stable_analysis_id(stem),
        "stem": stem,
        "review_rubric": DEFAULT_REVIEW_RUBRIC,
        "optional_reference_labels": rules,
        "anti_bias_instruction": "不要按标签清单倒推结论。只汇总有订单证据支持的观察；证据不足时，suspected_categories返回空数组，降低风险等级并写明限制。",
        "global_summary": summarize_trades(df),
        "global_features": derived_feature_summary(df),
        "chunk_results": chunk_results,
        "output_requirements": output_schema_instruction(),
    }


def extract_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    texts: list[str] = []
    output = payload.get("output", []) or []
    if isinstance(output, dict):
        output = [output]
    for item in output:
        if not isinstance(item, dict):
            continue
        content_items = item.get("content", []) or []
        if isinstance(content_items, dict):
            content_items = [content_items]
        for content in content_items:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                texts.append(text)
    return "\n".join(texts).strip()


def parse_json_text(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(value, dict):
            candidates.append(value)
        index = start + max(end, 1)
    if not candidates:
        raise RuntimeError("AI response did not contain JSON")
    for item in candidates:
        if item.get("schema_version") and (item.get("account_class") or item.get("short_summary")):
            return item
    for item in candidates:
        if item.get("answer") or item.get("key_points"):
            return item
    return candidates[-1]


def load_api_config() -> dict[str, str]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    config_path = DEFAULT_API_CONFIG
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        key = key or str(data.get("key", "")).strip()
        base_url = base_url or str(data.get("url", "")).strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured and api config has no key")
    if not base_url:
        base_url = "https://api.openai.com"
    return {"key": key, "base_url": base_url.rstrip("/")}


def call_openai_json(payload: dict[str, Any], model: str) -> dict[str, Any]:
    config = load_api_config()
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    }
    if DEFAULT_RESPONSE_FORMAT == "json_object":
        body["text"] = {"format": {"type": "json_object"}}
    req = urllib.request.Request(
        config["base_url"] + "/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {config['key']}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API failed: HTTP {exc.code} {detail}") from exc
    text = extract_response_text(json.loads(raw))
    try:
        return parse_json_text(text)
    except Exception as exc:
        snippet = " ".join(text.split())[:800]
        raise RuntimeError(f"AI response JSON parse failed: {exc}; response_snippet={snippet}") from exc


def compact_ai_result_context(ai_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "stem": ai_result.get("stem", ""),
        "created_at": ai_result.get("created_at", ""),
        "summary": ai_result.get("summary", {}),
        "short_summary": ai_result.get("short_summary") or ai_result.get("conclusion", ""),
        "account_class": ai_result.get("account_class", ""),
        "account_class_reason": ai_result.get("account_class_reason", ""),
        "risk_level": ai_result.get("risk_level", ""),
        "violation_judgment": ai_result.get("violation_judgment", ""),
        "behavior_definition": ai_result.get("behavior_definition", ""),
        "inferred_intent": ai_result.get("inferred_intent", ""),
        "suspected_categories": ai_result.get("suspected_categories", []),
        "suspected_abuse_types": ai_result.get("suspected_abuse_types", []),
        "key_metric_interpretation": ai_result.get("key_metric_interpretation", ""),
        "explanation": ai_result.get("explanation", ""),
        "limitations": ai_result.get("limitations", []),
        "local_metrics": ai_result.get("local_metrics", {}),
        "evidence_orders": (ai_result.get("evidence_orders") or [])[:20],
        "evidence_segments": (ai_result.get("evidence_segments") or [])[:10],
    }


def compact_chat_messages(chat_state: dict[str, Any], limit: int = 6) -> list[dict[str, str]]:
    messages = chat_state.get("messages") or []
    out: list[dict[str, str]] = []
    for msg in messages[-limit:]:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).strip()
        content = str(msg.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            out.append({"role": role, "content": content[:1800], "created_at": str(msg.get("created_at", ""))})
    return out


def build_followup_prompt(
    stem: str,
    ai_result: dict[str, Any],
    chat_state: dict[str, Any],
    question: str,
) -> dict[str, Any]:
    return {
        "task": "answer_followup_question_for_trade_risk_review",
        "stem": stem,
        "instruction": (
            "你是金融风控复核人员。请基于既有AI分析结果、本地计算指标、关键证据订单和对话上下文回答追问。"
            "不要重新计算local_metrics里的数值；如信息不足，明确说明还缺什么证据。"
            "回答要直接、专业、可复核。可以引用订单号，referenced_tickets只能使用上下文中真实存在的ticket。"
            "不要为了迎合用户问题而改变原始证据含义；如果追问推断过强，要指出置信度限制。"
        ),
        "token_saving_policy": {
            "full_raw_trades_sent": False,
            "context_strategy": "analysis_result + local_metrics + evidence_orders + conversation_summary + last_messages",
            "recent_message_limit": 6,
        },
        "analysis_context": compact_ai_result_context(ai_result),
        "conversation_summary": str(chat_state.get("conversation_summary", ""))[:3000],
        "recent_messages": compact_chat_messages(chat_state, 6),
        "question": question,
        "output_requirements": (
            "返回严格JSON，字段为 answer, key_points, referenced_tickets, limitations, conversation_summary。"
            "answer用中文，针对问题展开说明；key_points为3到6条要点；referenced_tickets为订单号数组；"
            "limitations说明本次回答的不确定性；conversation_summary用于压缩保存本轮对话上下文，控制在1200字以内。"
        ),
    }


def heuristic_followup_answer(stem: str, ai_result: dict[str, Any], chat_state: dict[str, Any], question: str) -> dict[str, Any]:
    context = compact_ai_result_context(ai_result)
    tickets = [str(item.get("ticket", "")) for item in context.get("evidence_orders", []) if item.get("ticket")]
    short = context.get("short_summary") or "当前结果未形成简短结论"
    answer = (
        f"基于当前已保存的AI分析和本地指标，核心判断是：{short}。"
        "本次为本地备用回答，未调用外部模型；可先结合证据订单与K线位置人工复核。"
        f"你的问题是：{question}"
    )
    old_summary = str(chat_state.get("conversation_summary", "")).strip()
    new_summary = (old_summary + "\n" if old_summary else "") + f"用户追问：{question}\n备用回答：{short}"
    return {
        "answer": answer,
        "key_points": [
            f"账户分类：{context.get('account_class') or '-'}",
            f"风险等级：{context.get('risk_level') or '-'}",
            f"违规判断：{context.get('violation_judgment') or '-'}",
            "如需更细结论，应使用openai/newapi provider进行模型追问。",
        ],
        "referenced_tickets": tickets[:5],
        "limitations": ["mock模式不会调用外部模型，回答只基于已保存结论做压缩复述。"],
        "conversation_summary": new_summary[-1200:],
    }


def answer_followup_question(
    stem: str,
    ai_result: dict[str, Any],
    chat_state: dict[str, Any],
    question: str,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    provider = (provider or DEFAULT_PROVIDER or "mock").lower()
    model = model or DEFAULT_MODEL
    if provider in {"openai", "newapi"}:
        payload = build_followup_prompt(stem, ai_result, chat_state, question)
        result = call_openai_json(payload, model)
    elif provider == "mock":
        result = heuristic_followup_answer(stem, ai_result, chat_state, question)
    else:
        raise RuntimeError(f"unsupported AI provider: {provider}")
    result.setdefault("answer", "")
    result.setdefault("key_points", [])
    result.setdefault("referenced_tickets", [])
    result.setdefault("limitations", [])
    result.setdefault("conversation_summary", str(chat_state.get("conversation_summary", ""))[:1200])
    result["provider"] = provider
    result["model"] = model
    result["created_at"] = now_text()
    return result


def heuristic_chunk_result(stem: str, df: pd.DataFrame, rules: dict[str, str], index: int, count: int) -> dict[str, Any]:
    work = add_features(df)
    evidence: list[dict[str, Any]] = []
    categories: list[str] = []

    short = work[work["_hold"].le(300)]
    if len(short) >= max(5, len(work) * 0.15):
        categories.append("scalping")
        for _, row in short.sort_values("_profit", ascending=False).head(8).iterrows():
            evidence.append(evidence_from_row(row, "持仓时间不超过5分钟，符合剥头皮复核条件", 0.62))

    martingale = work[(work["_prev_profit"] < 0) & (work["_volume_ratio_prev"] >= 1.5)]
    if len(martingale) >= 3:
        categories.append("martingale")
        for _, row in martingale.head(8).iterrows():
            evidence.append(evidence_from_row(row, "亏损后手数明显放大，疑似马丁/加码", 0.66))

    if summarize_trades(df)["profit_sum"] > 0 and len(categories) >= 2:
        categories.append("malicious_abuser")

    categories = sorted(set(categories)) or ["other_suspicious_pattern"]
    risk = "低"
    if len(evidence) >= 5 or len(categories) >= 2:
        risk = "中"
    if "malicious_abuser" in categories or len(evidence) >= 12:
        risk = "高"

    segment = []
    if evidence:
        segment = [
            {
                "segment_id": f"CHUNK-{index}-SEG-1",
                "start_time": min(item["open_time"] for item in evidence if item["open_time"]),
                "end_time": max(item["close_time"] for item in evidence if item["close_time"]),
                "tickets": [item["ticket"] for item in evidence if item["ticket"]],
                "categories": categories,
                "reason": "该订单段命中本地启发式疑似风险，需结合K线人工复核。",
            }
        ]
    return {
        "schema_version": "1.0",
        "analysis_id": stable_analysis_id(f"{stem}:{index}"),
        "stem": stem,
        "provider": "mock",
        "model": "heuristic-mock",
        "created_at": now_text(),
        "privacy": {"account_sent": False, "statement_sent": False, "trade_detail_sent": True},
        "summary": summarize_trades(df),
        "risk_level": risk,
        "conclusion": f"分块{index}/{count}预分析：{risk}风险，命中 {', '.join(categories)}。",
        "suspected_categories": categories,
        "evidence_orders": evidence,
        "evidence_segments": segment,
        "explanation": "mock provider用于验证分块、聚合、图表跳转和账台联动流程。",
        "limitations": ["mock结果不是最终风控判断。"],
        "suggested_ledger_note": "",
    }


def evidence_from_row(row: pd.Series, reason: str, confidence: float) -> dict[str, Any]:
    return {
        "ticket": str(clean_value(row.get("Ticket", "")) or ""),
        "open_time": str(clean_value(row.get("Open Time", "")) or ""),
        "close_time": str(clean_value(row.get("Close Time", "")) or ""),
        "type": str(clean_value(row.get("Type", "")) or ""),
        "volume": clean_value(row.get("Volume")),
        "profit": clean_value(row.get("Profit")),
        "holding_seconds": clean_value(row.get("Holding Seconds")),
        "reason": reason,
        "confidence": confidence,
    }


def aggregate_results(stem: str, df: pd.DataFrame, rules: dict[str, str], chunk_results: list[dict[str, Any]], provider: str, model: str) -> dict[str, Any]:
    categories = sorted({cat for result in chunk_results for cat in result.get("suspected_categories", [])})
    evidence_by_ticket: dict[str, dict[str, Any]] = {}
    for result in chunk_results:
        for order in result.get("evidence_orders", []) or []:
            ticket = str(order.get("ticket", ""))
            if ticket:
                evidence_by_ticket[ticket] = order
    segments = [seg for result in chunk_results for seg in (result.get("evidence_segments", []) or [])]
    risks = [result.get("risk_level", "低") for result in chunk_results]
    rank = {"低": 0, "中": 1, "高": 2, "严重": 3}
    risk = max(risks or ["低"], key=lambda item: rank.get(str(item), 0))
    if len(categories) >= 3 and rank.get(risk, 0) < 2:
        risk = "高"
    categories = categories or ["other_suspicious_pattern"]
    conclusion = f"AI预分析：{risk}风险，命中 {', '.join(categories)}；该结论为辅助复核，不自动定性。"
    result = {
        "schema_version": "1.0",
        "analysis_id": stable_analysis_id(stem),
        "stem": stem,
        "provider": provider,
        "model": model,
        "created_at": now_text(),
        "privacy": {"account_sent": False, "statement_sent": False, "trade_detail_sent": True},
        "rules": rules,
        "summary": summarize_trades(df),
        "features": derived_feature_summary(df),
        "cost_estimate": estimate_cost(df, model),
        "risk_level": risk,
        "conclusion": conclusion,
        "suspected_categories": categories,
        "evidence_orders": list(evidence_by_ticket.values())[:40],
        "evidence_segments": segments[:20],
        "explanation": "已按订单时间分块分析，并聚合可疑订单、订单段和全局特征。",
        "limitations": ["AI结论仅供复核；缺少外部报价、盘口深度或跨平台价格源时，推盘和跨平台打点差只能判断为疑似。"],
        "suggested_ledger_note": conclusion,
        "chunk_results": chunk_results,
    }
    return validate_evidence(result, df)


def validate_evidence(result: dict[str, Any], df: pd.DataFrame) -> dict[str, Any]:
    known = {str(clean_value(value) or "") for value in df.get("Ticket", pd.Series(dtype=object)).tolist()}
    result["evidence_orders"] = [
        order for order in result.get("evidence_orders", []) or [] if str(order.get("ticket", "")) in known
    ]
    for segment in result.get("evidence_segments", []) or []:
        segment["tickets"] = [ticket for ticket in segment.get("tickets", []) if str(ticket) in known]
    result["evidence_segments"] = [
        segment for segment in result.get("evidence_segments", []) or [] if segment.get("tickets")
    ]
    return result


def compact_text(text: Any, max_chars: int = 60) -> str:
    value = " ".join(str(text or "").replace("\n", " ").split())
    if len(value) <= max_chars:
        return value
    cut_points = [value.find("。"), value.find("；"), value.find(";")]
    cut_points = [pos for pos in cut_points if 0 < pos <= max_chars]
    if cut_points:
        return value[: min(cut_points) + 1]
    return value[:max_chars].rstrip("，,；;。 ") + "。"


def infer_compact_label(result: dict[str, Any], metrics: dict[str, Any]) -> str:
    existing = compact_text(result.get("short_summary") or result.get("conclusion"), 60)
    if existing:
        return existing
    pattern_scores = metrics.get("pattern_scores", {}) if isinstance(metrics, dict) else {}
    top = sorted(pattern_scores.items(), key=lambda item: int((item[1] or {}).get("score", 0)), reverse=True)
    top_name = top[0][0] if top else ""
    label_map = {
        "quote_latency_arbitrage": "短平盈利型，疑似报价延迟套利。",
        "cross_platform_spread_arbitrage": "短平盈利型，疑似跨平台点差套利。",
        "short_close_trading": "短平交易型，需复核是否EA快进快出。",
        "market_pushing": "密集下单型，疑似推盘。",
        "rebate_churning": "高频交易量型，疑似刷返佣。",
        "bonus_arbitrage": "规则收益型，疑似赠金套利。",
        "internal_lock_arbitrage": "对锁重叠型，疑似平台内对锁套利。",
        "high_leverage_lock_arbitrage": "高并发锁仓型，疑似高杠杆锁仓套利。",
        "weekend_gap_trading": "周末窗口型，疑似赌跳空。",
        "open_betting": "开盘窗口型，疑似赌开盘。",
    }
    return label_map.get(top_name, "普通交易型，未见明确abuser证据。")


def normalize_short_summary(result: dict[str, Any]) -> dict[str, Any]:
    metrics = result.get("local_metrics") or {}
    short = infer_compact_label(result, metrics)
    result["short_summary"] = compact_text(short, 60)
    result["conclusion"] = compact_text(result.get("conclusion") or result["short_summary"], 60)
    if len(result["conclusion"]) > len(result["short_summary"]) + 10:
        result["conclusion"] = result["short_summary"]
    if not result.get("suggested_ledger_note"):
        result["suggested_ledger_note"] = result["short_summary"]
    return result


def is_empty_model_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def normalize_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "需要", "是"}


def normalize_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def repair_model_result_shape(result: dict[str, Any]) -> dict[str, Any]:
    local_metrics = result.get("local_metrics")
    if isinstance(local_metrics, dict):
        hoisted: list[str] = []
        for key in sorted(MODEL_OUTPUT_FIELDS):
            if key in local_metrics and is_empty_model_value(result.get(key)):
                result[key] = local_metrics.pop(key)
                hoisted.append(key)
        if hoisted:
            warnings = result.setdefault("result_repair_warnings", [])
            if isinstance(warnings, list):
                warnings.append(
                    "Model placed output fields inside local_metrics; fields were hoisted to top level: "
                    + ", ".join(hoisted)
                )
    if "limitations" in result:
        result["limitations"] = normalize_text_list(result.get("limitations"))
    if "suspected_categories" in result:
        result["suspected_categories"] = normalize_text_list(result.get("suspected_categories"))
    if "suspected_abuse_types" in result:
        result["suspected_abuse_types"] = normalize_text_list(result.get("suspected_abuse_types"))
    result["need_quote_audit"] = normalize_bool(result.get("need_quote_audit"))
    result["quote_audit_requests"] = normalize_dict_list(result.get("quote_audit_requests"))
    result["data_requests"] = normalize_dict_list(result.get("data_requests"))
    return result


def local_fallback_result(stem: str, df: pd.DataFrame, provider: str, model: str, note: str = "") -> dict[str, Any]:
    metrics = calculate_local_risk_indicators(df)
    class_candidate = metrics.get("local_class_candidate", "M")
    class_risk = {"B": "低", "M": "中", "P": "中", "T": "高", "A": "严重"}
    pattern_scores = metrics.get("pattern_scores", {})
    abuse_types = [name for name, entry in pattern_scores.items() if int(entry.get("score", 0)) >= 45]
    sampled = select_high_signal_trades(df, 16)
    evidence = []
    for _, row in sampled.head(12).iterrows():
        evidence.append(evidence_from_row(row, "本地指标抽取的高信号订单，需结合K线和订单上下文复核。", 0.5))
    conclusion = infer_compact_label({}, metrics)
    result = {
        "schema_version": "1.0",
        "analysis_id": stable_analysis_id(stem),
        "stem": stem,
        "provider": provider,
        "model": model,
        "analysis_source": "local_fallback",
        "model_call_failed": provider != "mock",
        "created_at": now_text(),
        "privacy": {"account_sent": False, "statement_sent": False, "trade_detail_sent": True},
        "summary": summarize_trades(df),
        "features": derived_feature_summary(df),
        "local_metrics": metrics,
        "cost_estimate": estimate_cost(df, model),
        "short_summary": conclusion,
        "account_class": class_candidate,
        "account_class_reason": metrics.get("local_class_reason", ""),
        "risk_level": class_risk.get(class_candidate, "中"),
        "violation_judgment": "证据不足" if class_candidate in {"B", "M"} else "疑似违规",
        "behavior_definition": "本地统计兜底定义，正式结论应以AI复核和人工审核为准。",
        "inferred_intent": "无法仅凭本地统计确认主观意图；只能根据交易形态推测。",
        "suspected_categories": abuse_types,
        "suspected_abuse_types": abuse_types,
        "key_metric_interpretation": "本地已计算持仓、频率、盈亏集中度、亏损后加仓、锁仓/对锁和事件窗口等二级指标。",
        "evidence_orders": evidence,
        "evidence_segments": [],
        "explanation": f"{conclusion} {note}".strip(),
        "limitations": ["本地兜底不具备外部报价、盘口深度、返佣/赠金、杠杆权益等数据，不能单独确认违规。"],
        "suggested_ledger_note": conclusion,
    }
    return validate_evidence(normalize_short_summary(result), df)


def analyze_with_mock(stem: str, df: pd.DataFrame, rules: dict[str, str]) -> dict[str, Any]:
    result = local_fallback_result(stem, df, "mock", "heuristic-mock", "mock模式未调用外部模型。")
    result["model_call_failed"] = False
    return result


def notify_progress(progress: ProgressCallback | None, message: str, percent: int) -> None:
    if progress:
        progress("running", message, percent)


def analyze_with_openai(
    stem: str,
    df: pd.DataFrame,
    rules: dict[str, str],
    model: str,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    notify_progress(progress, "正在计算本地二级风控指标和抽样证据", 25)
    aggregate_payload = build_direct_analysis_prompt(stem, rules, df)
    notify_progress(progress, "本地证据包已完成，正在调用AI模型", 55)
    try:
        result = call_openai_json(aggregate_payload, model)
        notify_progress(progress, "模型已返回，正在解析JSON并校验证据订单", 82)
        result = repair_model_result_shape(result)
        result["analysis_source"] = "model"
        result["model_call_failed"] = False
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        print(f"[{now_text()}] AI model call failed for {stem}: {error_text}", file=sys.stderr)
        notify_progress(progress, "模型调用失败，正在生成本地兜底分析", 82)
        result = local_fallback_result(stem, df, "openai", model, "模型调用失败，返回本地兜底结果。")
        result["analysis_source"] = "local_fallback"
        result["model_call_failed"] = True
        result["model_error"] = error_text[:2000]
    result["provider"] = "openai"
    result["model"] = model
    result.setdefault("analysis_source", "model")
    result.setdefault("model_call_failed", False)
    result.setdefault("summary", summarize_trades(df))
    result.setdefault("features", derived_feature_summary(df))
    result.setdefault("local_metrics", aggregate_payload["local_metrics"])
    result = repair_model_result_shape(result)
    result.setdefault("short_summary", result.get("conclusion", ""))
    result.setdefault("account_class", aggregate_payload["local_metrics"].get("local_class_candidate", "M"))
    result.setdefault("account_class_reason", "")
    result.setdefault("violation_judgment", "证据不足")
    result.setdefault("behavior_definition", "")
    result.setdefault("inferred_intent", "")
    result.setdefault("suspected_abuse_types", result.get("suspected_categories", []))
    result.setdefault("key_metric_interpretation", "")
    result["cost_estimate"] = estimate_cost(df, model)
    result["privacy"] = {"account_sent": False, "statement_sent": False, "trade_detail_sent": True}
    notify_progress(progress, "正在整理最终AI报告", 92)
    return validate_evidence(normalize_short_summary(result), df)


def analyze_with_openai(
    stem: str,
    df: pd.DataFrame,
    rules: dict[str, str],
    model: str,
    out_dir: Path,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    notify_progress(progress, "正在计算本地二级风控指标和抽样订单", 25)
    sampled = select_high_signal_trades(df)
    notify_progress(progress, "正在读取本地K线报价缓存并生成M1/H1/H4行情摘要", 38)
    market_context = build_market_context(stem, out_dir, df, sampled)
    aggregate_payload = build_direct_analysis_prompt(stem, rules, df, market_context=market_context)
    first_cost = estimate_cost_for_payload(aggregate_payload, df, model)
    second_cost: dict[str, Any] | None = None
    notify_progress(progress, "本地证据包已完成，正在调用AI模型", 55)
    try:
        result = call_openai_json(aggregate_payload, model)
        notify_progress(progress, "首轮模型已返回，正在解析补充核查请求", 72)
        result = repair_model_result_shape(result)
        result["analysis_source"] = "model"
        result["model_call_failed"] = False
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        print(f"[{now_text()}] AI model call failed for {stem}: {error_text}", file=sys.stderr)
        notify_progress(progress, "模型调用失败，正在生成本地兜底分析", 82)
        result = local_fallback_result(stem, df, "openai", model, "模型调用失败，返回本地兜底结果。")
        result["analysis_source"] = "local_fallback"
        result["model_call_failed"] = True
        result["model_error"] = error_text[:2000]
    result["provider"] = "openai"
    result["model"] = model
    result.setdefault("analysis_source", "model")
    result.setdefault("model_call_failed", False)
    result.setdefault("summary", aggregate_payload.get("summary") or summarize_trades(df))
    result.setdefault("features", aggregate_payload.get("features") or derived_feature_summary(df))
    result.setdefault("local_metrics", aggregate_payload["local_metrics"])
    result.setdefault("market_context", aggregate_payload.get("market_context", {}))
    result = repair_model_result_shape(result)

    should_second_pass = (
        not result.get("model_call_failed")
        and bool((result.get("quote_audit_requests") or []) or (result.get("data_requests") or []))
    )
    if should_second_pass:
        notify_progress(progress, "正在按AI请求读取本地可用的补充核查数据", 78)
        supplemental_evidence = collect_supplemental_evidence(stem, out_dir, df, result)
        result["supplemental_audit"] = supplemental_evidence
        result["supplemental_pass_completed"] = False
        result["supplemental_model_call_failed"] = False
        supplemental_path = out_dir / f"{stem}_ai_supplemental_evidence.json"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            supplemental_path.write_text(json.dumps(supplemental_evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            result["supplemental_evidence_save_error"] = f"{type(exc).__name__}: {exc}"[:500]
        notify_progress(progress, "补充数据包已生成，正在进行二次AI复核", 84)
        second_payload = build_supplemental_prompt(stem, rules, df, result, supplemental_evidence)
        second_cost = estimate_cost_for_payload(second_payload, df, model)
        try:
            second_result = call_openai_json(second_payload, model)
            notify_progress(progress, "二次AI复核已返回，正在合并最终结论", 90)
            second_result = repair_model_result_shape(second_result)
            second_result["analysis_source"] = "model_second_pass"
            second_result["model_call_failed"] = False
            second_result["supplemental_pass_completed"] = True
            second_result["supplemental_model_call_failed"] = False
            second_result["supplemental_audit"] = supplemental_evidence
            second_result["first_pass_summary"] = compact_initial_result_for_second_pass(result)
            second_result.setdefault("summary", result.get("summary") or aggregate_payload.get("summary"))
            second_result.setdefault("features", result.get("features") or aggregate_payload.get("features"))
            second_result.setdefault("local_metrics", result.get("local_metrics") or aggregate_payload["local_metrics"])
            second_result.setdefault("market_context", result.get("market_context") or aggregate_payload.get("market_context", {}))
            result = second_result
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            print(f"[{now_text()}] AI supplemental model call failed for {stem}: {error_text}", file=sys.stderr)
            result["supplemental_pass_completed"] = False
            result["supplemental_model_call_failed"] = True
            result["supplemental_model_error"] = error_text[:2000]
            result.setdefault("limitations", [])
            if isinstance(result["limitations"], list):
                result["limitations"].append("二次补充数据已生成，但二次AI复核失败；当前结论仍为首轮模型结论。")
    else:
        result["supplemental_pass_completed"] = False
        result["supplemental_audit"] = {
            "enabled": True,
            "stage": "second_pass_supplement",
            "summary": {"quote_requests_total": 0, "data_requests_total": 0},
            "note": "首轮模型未提出补充核查请求，未触发二次AI复核。",
        }

    result.setdefault("short_summary", result.get("conclusion", ""))
    result.setdefault("account_class", aggregate_payload["local_metrics"].get("local_class_candidate", "M"))
    result.setdefault("account_class_reason", "")
    result.setdefault("violation_judgment", "证据不足")
    result.setdefault("behavior_definition", "")
    result.setdefault("inferred_intent", "")
    result.setdefault("suspected_abuse_types", result.get("suspected_categories", []))
    result.setdefault("key_metric_interpretation", "")
    result["cost_estimate"] = combine_cost_estimates(first_cost, second_cost)
    result["privacy"] = {"account_sent": False, "statement_sent": False, "trade_detail_sent": True}
    notify_progress(progress, "正在整理最终AI报告", 92)
    return validate_evidence(normalize_short_summary(result), df)


def load_rules(rules_path: Path | None) -> dict[str, str]:
    rules = dict(REFERENCE_RISK_LABELS)
    if rules_path and rules_path.exists():
        loaded = json.loads(rules_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            rules.update({str(k): str(v) for k, v in loaded.items()})
    return rules


def analyze_trades_file(
    trades_path: Path,
    out_dir: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    rules_path: Path | None = None,
    progress: ProgressCallback | None = None,
) -> Path:
    trades_path = Path(trades_path)
    out_dir = Path(out_dir or trades_path.parent)
    stem = stem_from_trades_path(trades_path)
    notify_progress(progress, "正在读取交易订单缓存", 8)
    rules = load_rules(rules_path)
    df = load_sanitized_trades(trades_path)
    notify_progress(progress, f"已读取 {len(df)} 笔订单，准备生成AI证据包", 15)
    provider = (provider or DEFAULT_PROVIDER or "mock").lower()
    model = model or DEFAULT_MODEL
    if provider in {"openai", "newapi"}:
        result = analyze_with_openai(stem, df, rules, model, out_dir, progress)
    elif provider == "mock":
        notify_progress(progress, "mock模式：正在用本地指标生成测试结果", 45)
        result = analyze_with_mock(stem, df, rules)
    else:
        raise RuntimeError(f"unsupported AI provider: {provider}")
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / f"{stem}_ai_analysis.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    request_path = out_dir / f"{stem}_ai_request_redacted.json"
    request_path.write_text(
        json.dumps(
            {
                "analysis_id": stable_analysis_id(stem),
                "privacy": {"account_sent": False, "statement_sent": False, "trade_detail_sent": True},
                "review_rubric": DEFAULT_REVIEW_RUBRIC,
                "optional_reference_labels": rules,
                "summary": result.get("summary") or summarize_trades(df),
                "features": result.get("features") or derived_feature_summary(df),
                "local_metrics": result.get("local_metrics") or calculate_local_risk_indicators(df),
                "market_context": result.get("market_context", {}),
                "supplemental_audit": result.get("supplemental_audit", {}),
                "supplemental_pass_completed": bool(result.get("supplemental_pass_completed")),
                "supplemental_model_call_failed": bool(result.get("supplemental_model_call_failed")),
                "cost_estimate": result.get("cost_estimate") or estimate_cost(df, model),
                "trade_columns": list(df.columns),
                "trade_count": int(len(df)),
                "sampled_trade_count": int((result.get("cost_estimate") or {}).get("sampled_trade_count") or len(select_high_signal_trades(df))),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    notify_progress(progress, "AI报告已生成", 100)
    return result_path


def estimate_trades_file(trades_path: Path, model: str | None = None) -> dict[str, Any]:
    df = load_sanitized_trades(Path(trades_path))
    return estimate_cost(df, model or DEFAULT_MODEL)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Analyze generated K-line trade CSV with optional AI provider.")
    parser.add_argument("--trades", required=True)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--rules", default="")
    parser.add_argument("--estimate-only", action="store_true")
    args = parser.parse_args()
    if args.estimate_only:
        print(json.dumps(estimate_trades_file(Path(args.trades), args.model), ensure_ascii=False, indent=2))
        return
    path = analyze_trades_file(
        Path(args.trades),
        Path(args.out_dir) if args.out_dir else None,
        provider=args.provider,
        model=args.model,
        rules_path=Path(args.rules) if args.rules else None,
    )
    print(path)


if __name__ == "__main__":
    main()
