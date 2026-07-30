from __future__ import annotations

import argparse
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


POOL_SIZE = 30
PORTFOLIO_EQUITY_USD = 100_000.0
TOTAL_CLIENT_BUDGET = 0.25
MAX_CLIENT_WEIGHT = 0.03
MIN_ORDER_LOTS = 0.01
BATCH_WINDOW_MS = 250


def canonical_symbol(symbol: str) -> str:
    return str(symbol).upper().split(".", 1)[0]


def percentile_rank(series: pd.Series) -> pd.Series:
    return series.rank(method="average", pct=True).fillna(0.5)


def winsorize(series: pd.Series, low: float = 0.01, high: float = 0.99) -> pd.Series:
    finite = series.replace([np.inf, -np.inf], np.nan)
    lo = finite.quantile(low)
    hi = finite.quantile(high)
    return finite.clip(lo, hi)


def normalize_with_cap(raw: pd.Series, budget: float, cap: float) -> pd.Series:
    weights = pd.Series(0.0, index=raw.index)
    remaining = set(raw[raw > 0].index)
    remaining_budget = budget
    while remaining and remaining_budget > 1e-12:
        subtotal = raw.loc[list(remaining)].sum()
        if subtotal <= 0:
            break
        proposed = raw.loc[list(remaining)] / subtotal * remaining_budget
        over = proposed[proposed > cap]
        if over.empty:
            weights.loc[proposed.index] = proposed
            break
        for idx in over.index:
            weights.loc[idx] = cap
            remaining.remove(idx)
            remaining_budget -= cap
    return weights


def detect_money_scale(frame: pd.DataFrame) -> pd.Series:
    currency = frame["Currency"].fillna("").astype(str).str.upper()
    account_type = frame["mt_type_name"].fillna("").astype(str).str.upper()
    is_cent = currency.isin({"USC", "USCENT", "CENT"}) | account_type.str.contains(
        "USC|CENT", regex=True
    )
    return pd.Series(np.where(is_cent, 0.01, 1.0), index=frame.index)


def build_pool(input_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates = pd.read_csv(input_dir / "candidate_features.tsv", sep="\t")
    daily = pd.read_csv(input_dir / "daily_20260726.tsv", sep="\t")
    routes = pd.read_csv(input_dir / "crm_route.tsv", sep="\t")
    risk = pd.read_csv(input_dir / "risk_60d.tsv", sep="\t")

    routes = routes.rename(columns={"mt_login": "Login"})
    frame = candidates.merge(daily, on="Login", how="inner", validate="one_to_one")
    frame = frame.merge(routes, on="Login", how="inner", validate="one_to_one")
    frame = frame.merge(risk, on="Login", how="left", validate="one_to_one")
    frame["money_scale"] = detect_money_scale(frame)

    money_columns = [
        "net_5d",
        "net_20d",
        "net_60d",
        "gross_profit_20d",
        "gross_loss_20d",
        "observed_spread_cost_20d",
        "adverse_slippage_20d",
        "Balance",
        "Credit",
        "Profit",
        "min_balance_60d",
        "min_equity_60d",
    ]
    for column in money_columns:
        frame[f"{column}_usd"] = pd.to_numeric(frame[column], errors="coerce") * frame[
            "money_scale"
        ]

    frame["equity_pre_usd"] = (
        frame["Balance_usd"] + frame["Credit_usd"] + frame["Profit_usd"]
    )
    frame["pf_20d"] = frame["gross_profit_20d_usd"] / frame[
        "gross_loss_20d_usd"
    ].replace(0, np.nan)
    frame["stress_net_15x_20d_usd"] = frame["net_20d_usd"] - 0.5 * frame[
        "observed_spread_cost_20d_usd"
    ]
    frame["ret_5d"] = frame["net_5d_usd"] / frame["equity_pre_usd"]
    frame["ret_20d"] = frame["net_20d_usd"] / frame["equity_pre_usd"]
    frame["stress_ret_20d"] = frame["stress_net_15x_20d_usd"] / frame[
        "equity_pre_usd"
    ]
    frame["stress_survival"] = (
        frame["stress_net_15x_20d_usd"] / frame["net_20d_usd"].replace(0, np.nan)
    ).clip(-1.0, 1.0)

    margin_ok = frame["min_margin_level_60d"].isna() | (
        frame["min_margin_level_60d"] >= 80.0
    )
    frame["hard_gate"] = (
        (frame["equity_pre_usd"] >= 100.0)
        & (frame["closes_5d"] >= 5)
        & (frame["closes_20d"] >= 20)
        & (frame["net_5d_usd"] > 0)
        & (frame["net_20d_usd"] > 0)
        & (frame["stress_net_15x_20d_usd"] > 0)
        & (frame["pf_20d"] >= 1.05)
        & (frame["negative_balance_days_60d"].fillna(0) == 0)
        & (frame["negative_equity_days_60d"].fillna(0) == 0)
        & (frame["so_compensation_days_60d"].fillna(0) == 0)
        & margin_ok
    )

    eligible = frame.loc[frame["hard_gate"]].copy()
    if len(eligible) < POOL_SIZE:
        raise RuntimeError(f"Only {len(eligible)} accounts passed the gates; need {POOL_SIZE}.")

    eligible["score_recent"] = percentile_rank(winsorize(eligible["ret_5d"]))
    eligible["score_medium"] = percentile_rank(winsorize(eligible["ret_20d"]))
    eligible["score_stress"] = percentile_rank(winsorize(eligible["stress_ret_20d"]))
    eligible["score_pf"] = percentile_rank(eligible["pf_20d"].clip(0, 3))
    eligible["score_survival"] = percentile_rank(eligible["stress_survival"])
    eligible["raw_score"] = (
        0.35 * eligible["score_recent"]
        + 0.25 * eligible["score_medium"]
        + 0.20 * eligible["score_stress"]
        + 0.10 * eligible["score_pf"]
        + 0.10 * eligible["score_survival"]
    )
    eligible["confidence"] = np.minimum(1.0, np.sqrt(eligible["closes_20d"] / 100.0))
    eligible["dynamic_score"] = 0.5 + eligible["confidence"] * (
        eligible["raw_score"] - 0.5
    )

    ranked = eligible.sort_values(
        ["dynamic_score", "stress_ret_20d"], ascending=False
    )
    pool = ranked.loc[ranked["dynamic_score"] > 0.55].head(POOL_SIZE).copy()
    if len(pool) < 10:
        raise RuntimeError(
            f"Only {len(pool)} accounts have a positive deployable score above 0.55."
        )
    pool["client_alias"] = [f"C{i:03d}" for i in range(1, len(pool) + 1)]
    pool["weight_alpha"] = np.maximum(pool["dynamic_score"] - 0.55, 0) ** 1.5
    pool["base_weight"] = normalize_with_cap(
        pool["weight_alpha"], TOTAL_CLIENT_BUDGET, MAX_CLIENT_WEIGHT
    )
    pool["rank"] = np.arange(1, len(pool) + 1)
    return pool, frame


def reduce_copied_position(current: float, deal_sign: float, lots: float) -> float:
    if current > 0 and deal_sign < 0:
        return max(0.0, current - lots)
    if current < 0 and deal_sign > 0:
        return min(0.0, current + lots)
    return current


@dataclass
class ActualPosition:
    lots: float = 0.0
    average_price: float = 0.0
    realized_pnl: float = 0.0
    spread_cost: float = 0.0
    turnover_lots: float = 0.0

    def execute(
        self,
        delta: float,
        fill_price: float,
        bid: float,
        ask: float,
        contract_size: float,
        rate_profit: float,
    ) -> tuple[float, float]:
        if abs(delta) < 1e-12:
            return 0.0, 0.0
        before = self.lots
        spread_cost_before = self.spread_cost
        realized_delta = 0.0
        if before == 0 or math.copysign(1, before) == math.copysign(1, delta):
            total = abs(before) + abs(delta)
            self.average_price = (
                (abs(before) * self.average_price + abs(delta) * fill_price) / total
            )
            self.lots = before + delta
        else:
            closing = min(abs(before), abs(delta))
            direction = 1.0 if before > 0 else -1.0
            if contract_size > 0 and rate_profit > 0:
                realized_delta = (
                    (fill_price - self.average_price)
                    * direction
                    * contract_size
                    * rate_profit
                    * closing
                )
            remainder = abs(delta) - closing
            if remainder > 1e-12:
                self.lots = math.copysign(remainder, delta)
                self.average_price = fill_price
            else:
                self.lots = before + delta
                if abs(self.lots) < 1e-12:
                    self.lots = 0.0
                    self.average_price = 0.0

        spread = max(0.0, ask - bid)
        if contract_size > 0 and rate_profit > 0:
            self.spread_cost += (
                0.5 * spread * contract_size * rate_profit * abs(delta)
            )
        self.realized_pnl += realized_delta
        self.turnover_lots += abs(delta)
        return realized_delta, self.spread_cost - spread_cost_before


def intraday_multiplier(net_usd: float, equity_usd: float) -> float:
    if equity_usd <= 0 or net_usd >= 0:
        return 1.0
    loss_rate = -net_usd / equity_usd
    if loss_rate >= 0.02:
        return 0.0
    if loss_rate >= 0.01:
        return 0.5 * (0.02 - loss_rate) / 0.01
    return 1.0 - 0.5 * loss_rate / 0.01


def simulate(input_dir: Path, output_dir: Path, pool: pd.DataFrame) -> dict[str, object]:
    deals = pd.read_csv(input_dir / "deals_20260727.tsv", sep="\t")
    deals["TimeMsc"] = pd.to_datetime(deals["TimeMsc"])
    selected_logins = set(pool["Login"].astype(int))
    deals = deals.loc[deals["Login"].astype(int).isin(selected_logins)].copy()
    deals["product"] = deals["Symbol"].map(canonical_symbol)
    deals = deals.sort_values(["TimeMsc", "Deal"], kind="stable")

    pool_by_login = pool.set_index("Login")
    alias_by_login = pool_by_login["client_alias"].to_dict()
    equity_by_login = pool_by_login["equity_pre_usd"].to_dict()
    scale_by_login = pool_by_login["money_scale"].to_dict()
    base_weight_by_login = pool_by_login["base_weight"].to_dict()

    copied_positions: dict[tuple[int, int, str], float] = defaultdict(float)
    source_intraday_net: dict[int, float] = defaultdict(float)
    effective_weight: dict[int, float] = dict(base_weight_by_login)
    quotes: dict[str, tuple[float, float, float, float]] = {}
    actual: dict[str, ActualPosition] = defaultdict(ActualPosition)
    last_execution_time: dict[str, pd.Timestamp] = {}
    timeline: list[dict[str, object]] = []
    ignored_close_deals = 0
    client_copied_deals: dict[int, int] = defaultdict(int)
    client_copied_source_lots: dict[int, float] = defaultdict(float)
    client_shadow_source_pnl: dict[int, float] = defaultdict(float)
    client_shadow_spread_cost: dict[int, float] = defaultdict(float)
    client_min_intraday_net: dict[int, float] = defaultdict(float)
    first_reduction_time: dict[int, pd.Timestamp] = {}
    stop_time: dict[int, pd.Timestamp] = {}

    def client_product_position(login: int, product: str) -> float:
        return sum(
            value
            for (pos_login, _position_id, pos_product), value in copied_positions.items()
            if pos_login == login and pos_product == product
        )

    def target_for(product: str) -> tuple[float, float, float, int]:
        contributions = []
        active_count = 0
        for login in selected_logins:
            source_lots = client_product_position(login, product)
            if abs(source_lots) < 1e-12:
                continue
            active_count += 1
            contribution = (
                source_lots
                * PORTFOLIO_EQUITY_USD
                * effective_weight[login]
                / max(equity_by_login[login], 1.0)
            )
            contributions.append(contribution)
        gross_long = sum(max(value, 0.0) for value in contributions)
        gross_short = sum(max(-value, 0.0) for value in contributions)
        return sum(contributions), gross_long, gross_short, active_count

    def product_unrealized(product: str) -> float:
        if product not in quotes:
            return 0.0
        position = actual[product]
        if position.lots == 0:
            return 0.0
        bid, ask, contract_size, rate_profit = quotes[product]
        if contract_size <= 0 or rate_profit <= 0:
            return 0.0
        mid = (bid + ask) / 2.0
        direction = 1.0 if position.lots > 0 else -1.0
        return (
            (mid - position.average_price)
            * direction
            * contract_size
            * rate_profit
            * abs(position.lots)
        )

    def portfolio_unrealized() -> float:
        return sum(product_unrealized(product) for product in actual)

    def maybe_execute(
        row: pd.Series,
        target: float,
        gross_long: float,
        gross_short: float,
        active_count: int,
        force: bool = False,
    ) -> None:
        product = row["product"]
        position = actual[product]
        delta = target - position.lots
        if abs(delta) < MIN_ORDER_LOTS:
            return
        deadband = max(MIN_ORDER_LOTS, 0.05 * max(abs(target), abs(position.lots), 0.01))
        if abs(delta) < deadband:
            return
        now = row["TimeMsc"]
        is_reduction = (
            abs(target) < abs(position.lots)
            or (target != 0 and position.lots != 0 and target * position.lots < 0)
        )
        last_time = last_execution_time.get(product)
        if (
            not force
            and not is_reduction
            and last_time is not None
            and (now - last_time).total_seconds() * 1000 < BATCH_WINDOW_MS
        ):
            return
        bid, ask, contract_size, rate_profit = quotes[product]
        if bid <= 0 or ask <= 0 or ask < bid:
            return
        fill = ask if delta > 0 else bid
        before = position.lots
        realized_delta, spread_cost_delta = position.execute(
            delta, fill, bid, ask, contract_size, rate_profit
        )
        last_execution_time[product] = now
        gross = gross_long + gross_short
        internal_offset = 0.0 if gross <= 0 else 1.0 - abs(target) / gross
        cumulative_realized = sum(item.realized_pnl for item in actual.values())
        product_unrealized_after = product_unrealized(product)
        portfolio_unrealized_after = portfolio_unrealized()
        entry_names = {0: "OPEN", 1: "CLOSE", 2: "REVERSAL", 3: "OUT_BY"}
        timeline.append(
            {
                "time": now,
                "product": product,
                "trigger_client": alias_by_login[int(row["Login"])],
                "source_side": "BUY" if int(row["Action"]) == 0 else "SELL",
                "source_entry": int(row["Entry"]),
                "source_entry_name": entry_names.get(int(row["Entry"]), "OTHER"),
                "source_lots": float(row["lots"]),
                "trigger_base_weight": base_weight_by_login[int(row["Login"])],
                "trigger_effective_weight": effective_weight[int(row["Login"])],
                "target_lots": target,
                "actual_before_lots": before,
                "execution_side": "BUY" if delta > 0 else "SELL",
                "order_delta_lots": delta,
                "actual_after_lots": position.lots,
                "position_direction_after": (
                    "LONG" if position.lots > 0 else "SHORT" if position.lots < 0 else "FLAT"
                ),
                "fill_price": fill,
                "bid": bid,
                "ask": ask,
                "spread_price": ask - bid,
                "contract_size": contract_size,
                "rate_profit": rate_profit,
                "position_average_price_after": position.average_price,
                "gross_long_lots": gross_long,
                "gross_short_lots": gross_short,
                "internally_offset_lots": max(0.0, gross - abs(target)),
                "internal_offset_pct": internal_offset,
                "active_clients": active_count,
                "realized_pnl_delta_usd": realized_delta,
                "cumulative_product_realized_pnl_usd": position.realized_pnl,
                "cumulative_realized_pnl_usd": cumulative_realized,
                "spread_cost_delta_usd": spread_cost_delta,
                "cumulative_spread_cost_usd": sum(
                    item.spread_cost for item in actual.values()
                ),
                "product_unrealized_pnl_after_usd": product_unrealized_after,
                "product_marked_pnl_after_usd": (
                    position.realized_pnl + product_unrealized_after
                ),
                "portfolio_unrealized_pnl_after_usd": portfolio_unrealized_after,
                "portfolio_marked_pnl_after_usd": (
                    cumulative_realized + portfolio_unrealized_after
                ),
            }
        )

    for row in deals.itertuples(index=False):
        login = int(row.Login)
        product = row.product
        scale = scale_by_login[login]
        event_source_net_usd = (
            float(row.Profit)
            + float(row.Storage)
            + float(row.Commission)
            + float(row.Fee)
        ) * scale
        previous_effective_weight = effective_weight[login]
        source_intraday_net[login] += event_source_net_usd
        client_min_intraday_net[login] = min(
            client_min_intraday_net[login], source_intraday_net[login]
        )
        effective_weight[login] = base_weight_by_login[login] * intraday_multiplier(
            source_intraday_net[login], equity_by_login[login]
        )
        if (
            effective_weight[login] < previous_effective_weight - 1e-12
            and login not in first_reduction_time
        ):
            first_reduction_time[login] = pd.Timestamp(row.TimeMsc)
        if effective_weight[login] <= 1e-12 and login not in stop_time:
            stop_time[login] = pd.Timestamp(row.TimeMsc)

        bid = float(row.MarketBid)
        ask = float(row.MarketAsk)
        if bid > 0 and ask >= bid:
            quotes[product] = (
                bid,
                ask,
                float(row.ContractSize),
                float(row.RateProfit),
            )
        elif product not in quotes:
            price = float(row.Price)
            quotes[product] = (
                price,
                price,
                float(row.ContractSize),
                float(row.RateProfit),
            )

        key = (login, int(row.PositionID), product)
        current = copied_positions[key]
        deal_sign = 1.0 if int(row.Action) == 0 else -1.0
        lots = float(row.lots)
        entry = int(row.Entry)
        copied_event_lots = 0.0
        if entry == 0:
            copied_positions[key] = current + deal_sign * lots
            copied_event_lots = lots
        elif entry in (1, 3):
            updated = reduce_copied_position(current, deal_sign, lots)
            if updated == current and abs(current) < 1e-12:
                ignored_close_deals += 1
            copied_event_lots = max(0.0, abs(current) - abs(updated))
            copied_positions[key] = updated
        elif entry == 2:
            close_lots = float(row.volume_closed_lots)
            updated = reduce_copied_position(current, deal_sign, close_lots)
            open_lots = max(0.0, lots - close_lots)
            copied_event_lots = max(0.0, abs(current) - abs(updated)) + open_lots
            copied_positions[key] = updated + deal_sign * open_lots

        if copied_event_lots > 1e-12:
            copied_fraction = min(1.0, copied_event_lots / max(lots, 1e-12))
            allocation_multiplier = (
                PORTFOLIO_EQUITY_USD
                * effective_weight[login]
                / max(equity_by_login[login], 1.0)
            )
            client_copied_deals[login] += 1
            client_copied_source_lots[login] += copied_event_lots
            client_shadow_source_pnl[login] += (
                event_source_net_usd * copied_fraction * allocation_multiplier
            )
            spread = max(0.0, ask - bid)
            contract_size = float(row.ContractSize)
            rate_profit = float(row.RateProfit)
            if contract_size > 0 and rate_profit > 0:
                client_shadow_spread_cost[login] += (
                    0.5
                    * spread
                    * contract_size
                    * rate_profit
                    * copied_event_lots
                    * allocation_multiplier
                )

        target, gross_long, gross_short, active_count = target_for(product)
        maybe_execute(
            pd.Series(row._asdict()), target, gross_long, gross_short, active_count
        )

    if timeline:
        final_row_by_product = deals.groupby("product", sort=False).tail(1)
        for _, row in final_row_by_product.iterrows():
            product = row["product"]
            target, gross_long, gross_short, active_count = target_for(product)
            maybe_execute(row, target, gross_long, gross_short, active_count, force=True)

    timeline_df = pd.DataFrame(timeline)
    if timeline_df.empty:
        raise RuntimeError("The selected pool produced no executable position changes.")

    active_deals = deals.groupby("Login").size().rename("yesterday_deals")
    client_results = pool.join(active_deals, on="Login")
    client_results["yesterday_deals"] = client_results["yesterday_deals"].fillna(0).astype(int)
    client_results["intraday_source_net_usd"] = client_results["Login"].map(
        source_intraday_net
    ).fillna(0.0)
    client_results["end_weight"] = client_results["Login"].map(effective_weight)
    client_results["copied_deals"] = client_results["Login"].map(
        client_copied_deals
    ).fillna(0).astype(int)
    client_results["copied_source_lots"] = client_results["Login"].map(
        client_copied_source_lots
    ).fillna(0.0)
    client_results["allocated_shadow_source_pnl_usd"] = client_results["Login"].map(
        client_shadow_source_pnl
    ).fillna(0.0)
    client_results["allocated_shadow_spread_cost_usd"] = client_results["Login"].map(
        client_shadow_spread_cost
    ).fillna(0.0)
    client_results["allocated_shadow_stress_15x_pnl_usd"] = (
        client_results["allocated_shadow_source_pnl_usd"]
        - 0.5 * client_results["allocated_shadow_spread_cost_usd"]
    )
    client_results["min_intraday_source_net_usd"] = client_results["Login"].map(
        client_min_intraday_net
    ).fillna(0.0)
    client_results["first_reduction_time"] = client_results["Login"].map(
        first_reduction_time
    )
    client_results["stop_time"] = client_results["Login"].map(stop_time)

    product_rows = []
    total_unrealized_pnl = 0.0
    for product, group in timeline_df.groupby("product"):
        state = actual[product]
        bid, ask, contract_size, rate_profit = quotes[product]
        mid = (bid + ask) / 2.0
        unrealized_pnl = 0.0
        if state.lots != 0 and contract_size > 0 and rate_profit > 0:
            direction = 1.0 if state.lots > 0 else -1.0
            unrealized_pnl = (
                (mid - state.average_price)
                * direction
                * contract_size
                * rate_profit
                * abs(state.lots)
            )
        total_unrealized_pnl += unrealized_pnl
        product_rows.append(
            {
                "product": product,
                "executions": len(group),
                "turnover_lots": state.turnover_lots,
                "max_long_lots": max(0.0, group["actual_after_lots"].max()),
                "max_short_lots": min(0.0, group["actual_after_lots"].min()),
                "end_lots": state.lots,
                "realized_pnl_usd": state.realized_pnl,
                "unrealized_pnl_usd": unrealized_pnl,
                "total_marked_pnl_usd": state.realized_pnl + unrealized_pnl,
                "estimated_spread_cost_usd": state.spread_cost,
                "average_internal_offset_pct": np.average(
                    group["internal_offset_pct"], weights=group["order_delta_lots"].abs()
                ),
            }
        )
    product_summary = pd.DataFrame(product_rows).sort_values(
        "turnover_lots", ascending=False
    )

    timeline_df["hour"] = pd.to_datetime(timeline_df["time"]).dt.floor("h")
    hourly_rows: list[dict[str, object]] = []
    for product, product_group in timeline_df.groupby("product"):
        previous_position = 0.0
        previous_marked_pnl = 0.0
        for hour, group in product_group.sort_values("time").groupby("hour"):
            positions = pd.concat(
                [pd.Series([previous_position]), group["actual_after_lots"]],
                ignore_index=True,
            )
            ending_marked_pnl = float(group.iloc[-1]["product_marked_pnl_after_usd"])
            turnover = float(group["order_delta_lots"].abs().sum())
            hourly_rows.append(
                {
                    "hour": hour,
                    "product": product,
                    "first_execution_time": group.iloc[0]["time"],
                    "last_execution_time": group.iloc[-1]["time"],
                    "executions": len(group),
                    "opening_lots": previous_position,
                    "highest_lots": float(positions.max()),
                    "lowest_lots": float(positions.min()),
                    "ending_lots": float(group.iloc[-1]["actual_after_lots"]),
                    "buy_lots": float(
                        group.loc[group["order_delta_lots"] > 0, "order_delta_lots"].sum()
                    ),
                    "sell_lots": float(
                        -group.loc[group["order_delta_lots"] < 0, "order_delta_lots"].sum()
                    ),
                    "turnover_lots": turnover,
                    "realized_pnl_delta_usd": float(group["realized_pnl_delta_usd"].sum()),
                    "spread_cost_delta_usd": float(group["spread_cost_delta_usd"].sum()),
                    "marked_pnl_change_at_executions_usd": (
                        ending_marked_pnl - previous_marked_pnl
                    ),
                    "ending_cumulative_realized_pnl_usd": float(
                        group.iloc[-1]["cumulative_product_realized_pnl_usd"]
                    ),
                    "ending_unrealized_pnl_usd": float(
                        group.iloc[-1]["product_unrealized_pnl_after_usd"]
                    ),
                    "ending_marked_pnl_usd": ending_marked_pnl,
                    "weighted_internal_offset_pct": (
                        float(
                            np.average(
                                group["internal_offset_pct"],
                                weights=group["order_delta_lots"].abs(),
                            )
                        )
                        if turnover > 0
                        else 0.0
                    ),
                }
            )
            previous_position = float(group.iloc[-1]["actual_after_lots"])
            previous_marked_pnl = ending_marked_pnl
    hourly_summary = pd.DataFrame(hourly_rows).sort_values(["hour", "product"])

    public_pool_columns = [
        "rank",
        "client_alias",
        "Currency",
        "mt_type_name",
        "equity_pre_usd",
        "closes_5d",
        "closes_20d",
        "net_5d_usd",
        "net_20d_usd",
        "stress_net_15x_20d_usd",
        "pf_20d",
        "dynamic_score",
        "confidence",
        "base_weight",
        "end_weight",
        "yesterday_deals",
        "intraday_source_net_usd",
        "min_intraday_source_net_usd",
        "copied_deals",
        "copied_source_lots",
        "allocated_shadow_source_pnl_usd",
        "allocated_shadow_spread_cost_usd",
        "allocated_shadow_stress_15x_pnl_usd",
        "first_reduction_time",
        "stop_time",
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    client_results[public_pool_columns].to_csv(
        output_dir / "client_pool.csv", index=False, encoding="utf-8-sig"
    )
    timeline_df.to_csv(
        output_dir / "position_timeline.csv", index=False, encoding="utf-8-sig"
    )
    product_summary.to_csv(
        output_dir / "product_summary.csv", index=False, encoding="utf-8-sig"
    )
    hourly_summary.to_csv(
        output_dir / "hourly_pnl.csv", index=False, encoding="utf-8-sig"
    )
    client_shadow_columns = [
        "rank",
        "client_alias",
        "base_weight",
        "end_weight",
        "yesterday_deals",
        "copied_deals",
        "copied_source_lots",
        "intraday_source_net_usd",
        "min_intraday_source_net_usd",
        "allocated_shadow_source_pnl_usd",
        "allocated_shadow_spread_cost_usd",
        "allocated_shadow_stress_15x_pnl_usd",
        "first_reduction_time",
        "stop_time",
    ]
    client_results[client_shadow_columns].to_csv(
        output_dir / "client_shadow_pnl.csv", index=False, encoding="utf-8-sig"
    )

    return {
        "deals": deals,
        "timeline": timeline_df,
        "client_results": client_results,
        "product_summary": product_summary,
        "hourly_summary": hourly_summary,
        "ignored_close_deals": ignored_close_deals,
        "eligible_count": int(frame_count := len(pool)),
        "active_clients": int((client_results["yesterday_deals"] > 0).sum()),
        "reduced_clients": int(
            (client_results["end_weight"] < client_results["base_weight"] - 1e-12).sum()
        ),
        "stopped_clients": int((client_results["end_weight"] < 1e-12).sum()),
        "end_weight_budget": float(client_results["end_weight"].sum()),
        "executions": int(len(timeline_df)),
        "products": int(timeline_df["product"].nunique()),
        "realized_pnl": float(sum(item.realized_pnl for item in actual.values())),
        "unrealized_pnl": float(total_unrealized_pnl),
        "total_marked_pnl": float(
            sum(item.realized_pnl for item in actual.values()) + total_unrealized_pnl
        ),
        "spread_cost": float(sum(item.spread_cost for item in actual.values())),
        "shadow_source_pnl": float(
            client_results["allocated_shadow_source_pnl_usd"].sum()
        ),
        "shadow_stress_15x_pnl": float(
            client_results["allocated_shadow_stress_15x_pnl_usd"].sum()
        ),
        "pool_count": frame_count,
    }


def draw_timeline_chart(timeline: pd.DataFrame, output_path: Path) -> None:
    top_products = (
        timeline.groupby("product")["order_delta_lots"]
        .apply(lambda value: value.abs().sum())
        .sort_values(ascending=False)
        .head(4)
        .index.tolist()
    )
    width, height = 1500, 920
    margin_left, margin_right = 110, 40
    margin_top, margin_bottom = 70, 60
    plot_height = (height - margin_top - margin_bottom) / max(1, len(top_products))
    image = Image.new("RGB", (width, height), "#F6F7F9")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.text((margin_left, 25), "Copy-trading demo: actual net lots on 2026-07-27", fill="#111827", font=font)
    day_start = pd.Timestamp("2026-07-27 00:00:00")
    day_end = pd.Timestamp("2026-07-28 00:00:00")
    total_seconds = (day_end - day_start).total_seconds()

    for panel, product in enumerate(top_products):
        y0 = margin_top + panel * plot_height
        y1 = y0 + plot_height - 26
        x0, x1 = margin_left, width - margin_right
        group = timeline.loc[timeline["product"] == product].sort_values("time")
        max_abs = max(0.01, group["actual_after_lots"].abs().max())
        draw.rectangle((x0, y0, x1, y1), fill="#FFFFFF", outline="#D1D5DB")
        zero_y = (y0 + y1) / 2
        draw.line((x0, zero_y, x1, zero_y), fill="#9CA3AF", width=1)
        draw.text((20, y0 + 8), product, fill="#111827", font=font)
        draw.text((20, y0 + 25), f"+/- {max_abs:.2f} lots", fill="#6B7280", font=font)
        points = [(x0, zero_y)]
        previous_y = zero_y
        for row in group.itertuples(index=False):
            seconds = (pd.Timestamp(row.time) - day_start).total_seconds()
            x = x0 + max(0.0, min(1.0, seconds / total_seconds)) * (x1 - x0)
            y = zero_y - (float(row.actual_after_lots) / max_abs) * (y1 - y0) * 0.44
            points.append((x, previous_y))
            points.append((x, y))
            previous_y = y
        points.append((x1, previous_y))
        draw.line(points, fill="#1565C0", width=3, joint="curve")
        if panel == len(top_products) - 1:
            for hour in (0, 6, 12, 18, 24):
                x = x0 + hour / 24 * (x1 - x0)
                draw.line((x, y1, x, y1 + 5), fill="#6B7280")
                draw.text((x - 10, y1 + 10), f"{hour:02d}", fill="#374151", font=font)
    image.save(output_path)


def draw_pnl_chart(timeline: pd.DataFrame, output_path: Path) -> None:
    width, height = 1500, 650
    left, right, top, bottom = 110, 40, 75, 70
    x0, x1 = left, width - right
    y0, y1 = top, height - bottom
    image = Image.new("RGB", (width, height), "#F6F7F9")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.rectangle((x0, y0, x1, y1), fill="#FFFFFF", outline="#D1D5DB")
    draw.text((left, 25), "Copy-trading demo: execution-time PnL on 2026-07-27", fill="#111827", font=font)

    frame = timeline.sort_values("time").copy()
    day_start = pd.Timestamp("2026-07-27 00:00:00")
    day_end = pd.Timestamp("2026-07-28 00:00:00")
    total_seconds = (day_end - day_start).total_seconds()
    series = {
        "Marked PnL": (frame["portfolio_marked_pnl_after_usd"], "#1565C0"),
        "Realized PnL": (frame["cumulative_realized_pnl_usd"], "#2E7D32"),
        "Implicit spread cost": (frame["cumulative_spread_cost_usd"], "#C62828"),
    }
    all_values = pd.concat([values for values, _color in series.values()])
    lower = min(0.0, float(all_values.min()))
    upper = max(0.0, float(all_values.max()))
    padding = max(50.0, (upper - lower) * 0.08)
    lower -= padding
    upper += padding

    def xy(time_value: object, pnl_value: float) -> tuple[float, float]:
        seconds = (pd.Timestamp(time_value) - day_start).total_seconds()
        x = x0 + max(0.0, min(1.0, seconds / total_seconds)) * (x1 - x0)
        y = y1 - (float(pnl_value) - lower) / (upper - lower) * (y1 - y0)
        return x, y

    zero_y = xy(day_start, 0.0)[1]
    draw.line((x0, zero_y, x1, zero_y), fill="#9CA3AF", width=1)
    for name, (values, color) in series.items():
        points = [xy(time_value, pnl) for time_value, pnl in zip(frame["time"], values)]
        if len(points) >= 2:
            draw.line(points, fill=color, width=3, joint="curve")
        elif points:
            x, y = points[0]
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)
    legend_x = left
    for name, (values, color) in series.items():
        draw.line((legend_x, 51, legend_x + 24, 51), fill=color, width=3)
        label = f"{name}: {float(values.iloc[-1]):,.2f} USD"
        draw.text((legend_x + 30, 44), label, fill="#374151", font=font)
        legend_x += 285
    for hour in (0, 6, 12, 18, 24):
        x = x0 + hour / 24 * (x1 - x0)
        draw.line((x, y1, x, y1 + 5), fill="#6B7280")
        draw.text((x - 10, y1 + 12), f"{hour:02d}", fill="#374151", font=font)
    draw.text((20, y0), f"{upper:,.0f}", fill="#6B7280", font=font)
    draw.text((20, y1 - 10), f"{lower:,.0f}", fill="#6B7280", font=font)
    image.save(output_path)


def write_report(output_dir: Path, pool: pd.DataFrame, result: dict[str, object]) -> None:
    products = result["product_summary"]
    hourly = result["hourly_summary"]
    clients = result["client_results"]
    top_lines = []
    for row in products.head(8).itertuples(index=False):
        top_lines.append(
            f"| {row.product} | {row.executions} | {row.turnover_lots:.2f} | "
            f"{row.max_long_lots:.2f} | {row.max_short_lots:.2f} | {row.end_lots:.2f} | "
            f"{row.average_internal_offset_pct:.1%} |"
        )
    hour_lines = []
    for row in hourly.sort_values("turnover_lots", ascending=False).head(8).itertuples(index=False):
        hour_lines.append(
            f"| {pd.Timestamp(row.hour):%H:00} | {row.executions} | {row.opening_lots:.2f} | "
            f"{row.highest_lots:.2f} | {row.lowest_lots:.2f} | {row.ending_lots:.2f} | "
            f"{row.turnover_lots:.2f} | {row.realized_pnl_delta_usd:,.2f} | "
            f"{row.ending_marked_pnl_usd:,.2f} |"
        )
    cut_lines = []
    cut_clients = clients.loc[clients["end_weight"] < clients["base_weight"] - 1e-12]
    for row in cut_clients.sort_values("end_weight").itertuples(index=False):
        reduction_time = (
            pd.Timestamp(row.first_reduction_time).strftime("%H:%M:%S")
            if pd.notna(row.first_reduction_time)
            else ""
        )
        stop_value = getattr(row, "stop_time")
        stopped_at = (
            pd.Timestamp(stop_value).strftime("%H:%M:%S") if pd.notna(stop_value) else ""
        )
        cut_lines.append(
            f"| {row.client_alias} | {row.base_weight:.2%} | {row.end_weight:.2%} | "
            f"{row.intraday_source_net_usd:,.2f} | {row.min_intraday_source_net_usd:,.2f} | "
            f"{reduction_time} | {stopped_at} |"
        )
    report = f"""# 2026-07-27 动态净头寸跟单 Demo

## 回放口径

- 数据源：DBG `crm_vn_mt5_live2`，数据库时区 UTC+8。
- 客户池只使用 2026-07-26 及以前的数据构建，2026-07-27 数据仅用于回放。
- 统一横截面完成币种/美分识别；本数据源当日账户币种均为 USD。
- 池子规模：{len(pool)} 个；昨日实际有信号：{result['active_clients']} 个。
- 模拟组合权益：USD {PORTFOLIO_EQUITY_USD:,.0f}；客户总资本预算：{TOTAL_CLIENT_BUDGET:.0%}。
- 日内风险更新后权重预算降至 {result['end_weight_budget']:.1%}；{result['reduced_clients']} 个账户被降权，其中 {result['stopped_clients']} 个降至0。
- 入池前旧仓不接管。27日没有已复制开仓记录的平仓成交被忽略，共 {result['ignored_close_deals']:,} 条。
- 客户亏损达到当日期初权益 1% 后开始快速降权，达到 2% 后停止其新增风险；当日盈利不追涨加权。
- 真实账户只执行标准化产品的净目标手数，最小订单变化 {MIN_ORDER_LOTS:.2f} 手，新增风险批处理窗口 {BATCH_WINDOW_MS}ms。

## 回放结果

- 来源成交事件：{len(result['deals']):,} 条。
- 模拟真实执行：{result['executions']:,} 次。
- 发生净头寸变化的产品：{result['products']} 个。
- 模拟已实现盈亏：USD {result['realized_pnl']:,.2f}。
- 收盘未实现盈亏：USD {result['unrealized_pnl']:,.2f}。
- 收盘盯市总盈亏：USD {result['total_marked_pnl']:,.2f}。
- 估算隐含点差成本：USD {result['spread_cost']:,.2f}，已经包含在Bid/Ask成交盈亏中，不能重复扣除。
- 未净额化客户影子收益合计：USD {result['shadow_source_pnl']:,.2f}；1.5倍点差压力后为 USD {result['shadow_stress_15x_pnl']:,.2f}。影子收益使用来源成交按分配资本缩放，不等于真实组合归因。

| 产品 | 执行次数 | 换手手数 | 最大多头 | 最大空头 | 收盘净手数 | 平均内部抵消率 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(top_lines)}

内部抵消率表示客户多空信号在进入真实账户前被净额化的比例。比例越高，越能说明逐客户直接镜像会产生无效锁仓和重复点差。

## 高换手小时明细

| 小时 | 执行次数 | 期初手数 | 最高手数 | 最低手数 | 期末手数 | 换手 | 小时已实现盈亏 | 期末盯市累计盈亏 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(hour_lines)}

## 日内动态降权

| 客户 | 初始权重 | 日终权重 | 当日来源净收益 | 日内最低累计收益 | 首次降权 | 停用时间 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(cut_lines)}

## 文件

- `client_pool.csv`：匿名客户池、建池特征、初始和日终权重。
- `position_timeline.csv`：每次真实净头寸调整及触发客户。
- `hourly_pnl.csv`：每个活跃小时的开高低收仓位、换手、已实现和盯市收益。
- `client_shadow_pnl.csv`：匿名客户的来源收益、分配资本影子收益、点差压力收益和降权时间。
- `product_summary.csv`：产品级换手、净头寸和内部抵消。
- `position_timeline.png`：主要产品的日内净头寸阶梯图。
- `pnl_timeline.png`：累计已实现、执行时盯市和隐含点差成本曲线。

## Demo限制

这是执行模块验证，不是可直接上线的收益回测。当前手数换算采用“来源手数/来源权益 × 分配资本”，生产版应进一步使用产品ATR、来源止损距离、合约规模和组合风险预算。成交使用触发时可见Bid/Ask，没有模拟网络排队、拒单和额外佣金；这些应在下一版加入压力场景。
"""
    (output_dir / "README.md").write_text(report, encoding="utf-8")


def run_checks(output_dir: Path, result: dict[str, object]) -> None:
    pool = pd.read_csv(output_dir / "client_pool.csv")
    timeline = pd.read_csv(output_dir / "position_timeline.csv")
    summary = pd.read_csv(output_dir / "product_summary.csv")
    hourly = pd.read_csv(output_dir / "hourly_pnl.csv")
    client_shadow = pd.read_csv(output_dir / "client_shadow_pnl.csv")
    forbidden = {"Login", "Deal", "PositionID", "user_id", "mt_login"}
    for name, frame in (
        ("pool", pool),
        ("timeline", timeline),
        ("summary", summary),
        ("hourly", hourly),
        ("client_shadow", client_shadow),
    ):
        leaked = forbidden.intersection(frame.columns)
        if leaked:
            raise AssertionError(f"{name} exposes identifiers: {sorted(leaked)}")
    if pool["client_alias"].nunique() != len(pool):
        raise AssertionError("Client aliases are not unique.")
    if not np.isclose(pool["base_weight"].sum(), TOTAL_CLIENT_BUDGET, atol=1e-9):
        raise AssertionError("Client weights do not sum to the configured budget.")
    if (pool["base_weight"] > MAX_CLIENT_WEIGHT + 1e-12).any():
        raise AssertionError("A client weight exceeds the configured cap.")
    last_positions = timeline.sort_values("time").groupby("product").tail(1).set_index("product")
    summary_positions = summary.set_index("product")
    aligned = last_positions.join(summary_positions, how="inner", rsuffix="_summary")
    if not np.allclose(aligned["actual_after_lots"], aligned["end_lots"], atol=1e-9):
        raise AssertionError("Product ending positions do not reconcile.")
    if int(result["executions"]) != len(timeline):
        raise AssertionError("Execution count does not reconcile.")
    if not np.isclose(
        hourly["realized_pnl_delta_usd"].sum(),
        summary["realized_pnl_usd"].sum(),
        atol=1e-6,
    ):
        raise AssertionError("Hourly realized PnL does not reconcile to product totals.")
    if not np.isclose(
        hourly["spread_cost_delta_usd"].sum(),
        summary["estimated_spread_cost_usd"].sum(),
        atol=1e-6,
    ):
        raise AssertionError("Hourly spread cost does not reconcile to product totals.")
    if not np.isclose(
        timeline.iloc[-1]["portfolio_marked_pnl_after_usd"],
        result["total_marked_pnl"],
        atol=1e-6,
    ):
        raise AssertionError("Last execution mark does not reconcile to total marked PnL.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a dynamic net-position copy-trading demo.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    pool, _universe = build_pool(args.input_dir)
    result = simulate(args.input_dir, args.output_dir, pool)
    draw_timeline_chart(result["timeline"], args.output_dir / "position_timeline.png")
    draw_pnl_chart(result["timeline"], args.output_dir / "pnl_timeline.png")
    write_report(args.output_dir, pool, result)
    run_checks(args.output_dir, result)
    print(
        f"pool={len(pool)} active={result['active_clients']} "
        f"events={len(result['deals'])} executions={result['executions']} "
        f"products={result['products']}"
    )


if __name__ == "__main__":
    main()
