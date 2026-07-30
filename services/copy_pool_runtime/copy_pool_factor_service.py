"""Application service combining history and versioned factor gates."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import nullcontext
from datetime import datetime, time, timedelta, timezone
from typing import Any, Mapping

import pandas as pd

from copy_delay_replay_domain import (
    DelayEvaluation,
    evaluate_delay_portfolio,
    prepare_validated_quote_array,
)
from copy_pool_factor_domain import (
    DrawdownMetrics,
    FactorInputs,
    HoldingQualityMetrics,
    calculate_adjusted_equity_metrics,
    calculate_factor_result,
    calculate_holding_quality_metrics,
)
from copy_pool_history_repository import (
    AccountHistoryBundle,
    ReadOnlyPoolHistoryRepository,
    SleeveHistoryBundle,
)
from copy_product_catalog import default_roundtrip_spread_usd_per_lot
from copy_quote_replay_cache import QuoteReplayCache


SERVER_TIMEZONE = timezone(timedelta(hours=3))
DELAY_GRID_MS = (500, 1_000, 2_000, 3_000, 5_000)


@dataclass(frozen=True)
class RawSleeveFactor:
    account: AccountHistoryBundle | None
    sleeve: SleeveHistoryBundle | None
    drawdown: DrawdownMetrics | None
    holding: HoldingQualityMetrics | None
    delay: DelayEvaluation | None
    quote_complete: bool
    reasons: tuple[str, ...]
    risk_return_5d: float
    risk_return_20d: float
    stress_return: float
    pf_quality: float
    return_to_drawdown: float


def _rank(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.rank(pct=True, method="average").fillna(0.0).clip(0.0, 1.0)


class CopyPoolFactorService:
    def __init__(
        self,
        quote_cache: QuoteReplayCache,
        *,
        quote_provider_name: str = "ACCMGlobal-Demo",
        actual_entry_p95_ms: int = 1_500,
        actual_exit_p95_ms: int = 1_500,
        warm_missing_quote_partitions: bool = False,
        historical_delay_enabled: bool = False,
        history_repository: ReadOnlyPoolHistoryRepository | None = None,
    ) -> None:
        self.quote_cache = quote_cache
        self.quote_provider_name = quote_provider_name
        self.actual_entry_p95_ms = int(actual_entry_p95_ms)
        self.actual_exit_p95_ms = int(actual_exit_p95_ms)
        self.warm_missing_quote_partitions = bool(warm_missing_quote_partitions)
        self.historical_delay_enabled = bool(historical_delay_enabled)
        self.history_repository = history_repository or ReadOnlyPoolHistoryRepository()

    def evaluate(
        self,
        sources: Mapping[str, Any],
        frame: pd.DataFrame,
        as_of: datetime,
    ) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame()
        accounts: dict[str, AccountHistoryBundle] = {}
        sleeves: dict[str, SleeveHistoryBundle] = {}
        for source_key, group in frame.groupby("physical_key"):
            bundle = self.history_repository.load_source(
                sources[str(source_key)], group, as_of
            )
            accounts.update(bundle.accounts)
            sleeves.update(bundle.sleeves)

        quote_ranges: dict[str, Any] = {}
        try:
            if self.historical_delay_enabled:
                provider_session = getattr(
                    getattr(self.quote_cache, "provider", None), "session", None
                )
                session_context = (
                    provider_session()
                    if self.warm_missing_quote_partitions and callable(provider_session)
                    else nullcontext()
                )
                with session_context:
                    for product, group in frame.groupby("product"):
                        lifecycle_rows = [
                            lifecycle
                            for row in group.itertuples()
                            for lifecycle in (
                                sleeves.get(str(row.sleeve_key)).lifecycles
                                if sleeves.get(str(row.sleeve_key)) is not None else ()
                            )
                        ]
                        events = [event for lifecycle in lifecycle_rows for event in lifecycle.events]
                        if not events:
                            continue
                        start = datetime.fromtimestamp(
                            (min(event.time_msc for event in events) - 2_000) / 1000.0,
                            tz=timezone.utc,
                        )
                        end = datetime.fromtimestamp(
                            (max(event.time_msc for event in events) + max(DELAY_GRID_MS) + 2_001) / 1000.0,
                            tz=timezone.utc,
                        )
                        quote_range = self.quote_cache.load_range(
                            self.quote_provider_name, str(product), start, end, mmap=True
                        )
                        if self.warm_missing_quote_partitions and quote_range.missing_dates:
                            missing = quote_range.missing_dates
                            quote_range.close()
                            for day in missing:
                                with self.quote_cache.load_day(
                                    self.quote_provider_name, str(product), day, mmap=False
                                ):
                                    pass
                            quote_range = self.quote_cache.load_range(
                                self.quote_provider_name, str(product), start, end, mmap=True
                            )
                        quote_ranges[str(product)] = quote_range
            raw_rows: list[dict[str, Any]] = []
            for row in frame.itertuples():
                key = str(row.sleeve_key)
                raw = self._evaluate_one(
                    row, accounts.get(str(row.account_key)), sleeves.get(key),
                    quote_ranges.get(str(row.product)), as_of,
                )
                raw_rows.append({"sleeve_key": key, "raw": raw})
            raw_frame = pd.DataFrame(raw_rows)
            metrics = pd.DataFrame([
                {
                    "risk_return_5d": item.risk_return_5d,
                    "risk_return_20d": item.risk_return_20d,
                    "stress_return": item.stress_return,
                    "pf_quality": item.pf_quality,
                    "return_to_drawdown": item.return_to_drawdown,
                }
                for item in raw_frame["raw"]
            ])
            ranked = metrics.apply(_rank)
            output: list[dict[str, Any]] = []
            for index, item in raw_frame.iterrows():
                raw: RawSleeveFactor = item["raw"]
                drawdown = raw.drawdown
                holding = raw.holding
                delay = raw.delay
                extra = list(raw.reasons)
                if holding is not None:
                    extra.extend(holding.gate_reasons)
                if delay is not None:
                    extra.extend(delay.hard_gate_reasons)
                factor = calculate_factor_result(FactorInputs(
                    risk_adjusted_return_5d=float(ranked.at[index, "risk_return_5d"]),
                    risk_adjusted_return_20d=float(ranked.at[index, "risk_return_20d"]),
                    spread_stress_return=float(ranked.at[index, "stress_return"]),
                    pf_quality=float(ranked.at[index, "pf_quality"]),
                    delay_score=delay.delay_score if delay is not None else 0.0,
                    return_to_drawdown=float(ranked.at[index, "return_to_drawdown"]),
                    holding_quality=(
                        holding.quality_multiplier
                        if holding is not None and raw.sleeve is not None
                        and raw.sleeve.holding_path_complete
                        else max(
                            0.0,
                            holding.quality_multiplier
                            - 0.10 * holding.long_loss_multiplier
                            - 0.10 * holding.loss_addition_multiplier,
                        ) if holding is not None else 0.0
                    ),
                    mdd_20d=drawdown.mdd_20d if drawdown is not None else 1.0,
                    mdd_60d=drawdown.mdd_60d if drawdown is not None else 1.0,
                    current_drawdown=drawdown.current_drawdown if drawdown is not None else 1.0,
                    max_daily_loss=drawdown.max_daily_loss if drawdown is not None else 1.0,
                    delay_gates_passed=bool(delay and delay.hard_gate_passed and raw.quote_complete),
                    delay_factor_enabled=self.historical_delay_enabled,
                    negative_equity=bool(drawdown and any("nonpositive_adjusted_equity" in reason for reason in drawdown.gate_reasons)),
                    nonpositive_balance_baseline=bool(drawdown and "nonpositive_adjusted_balance_baseline" in drawdown.gate_reasons),
                    stop_out_compensation=bool(raw.account and raw.account.stop_out_compensation),
                    holding_hard_failed=bool(
                        holding is None or holding.hard_failed
                        or raw.sleeve is None
                    ),
                    coverage_20d=bool(drawdown and drawdown.coverage_20d),
                    coverage_60d=bool(drawdown and drawdown.coverage_60d),
                    daily_drawdown_coverage=bool(
                        drawdown and drawdown.daily_coverage_complete
                    ),
                    extra_gate_reasons=tuple(dict.fromkeys(extra)),
                ))
                output.append(self._public_row(str(item["sleeve_key"]), factor, raw))
            return pd.DataFrame(output)
        finally:
            for quote_range in quote_ranges.values():
                quote_range.close()

    def _evaluate_one(
        self,
        row: Any,
        account: AccountHistoryBundle | None,
        sleeve: SleeveHistoryBundle | None,
        quote_range: Any | None,
        as_of: datetime,
    ) -> RawSleeveFactor:
        reasons: list[str] = []
        drawdown = None
        if account is None:
            reasons.append("missing_account_history")
        else:
            drawdown = calculate_adjusted_equity_metrics(
                account.equity.points, as_of,
                day_timezone=SERVER_TIMEZONE, rollover_time=time(0, 0),
                max_staleness=timedelta(hours=36),
            )
        holding = None
        if sleeve is None or not sleeve.lifecycles:
            reasons.append("missing_completed_position_lifecycles")
        else:
            holding = calculate_holding_quality_metrics(
                sleeve.holdings, server_utc_offset=SERVER_TIMEZONE,
                rollover_time=time(0, 0), as_of=as_of, window_days=60,
            )
        delay = None
        quote_complete = bool(quote_range is not None and quote_range.complete and len(quote_range.ticks))
        if self.historical_delay_enabled and not quote_complete:
            reasons.append("missing_or_incomplete_quote_range")
        elif self.historical_delay_enabled and sleeve is not None and sleeve.lifecycles:
            entry_lots = [
                event.lots for lifecycle in sleeve.lifecycles for event in lifecycle.events
                if event.entry in (0, 2)
            ]
            average_lots = sum(entry_lots) / len(entry_lots) if entry_lots else 0.0
            expected_cost = default_roundtrip_spread_usd_per_lot(str(row.product)) * average_lots
            delay = evaluate_delay_portfolio(
                sleeve.lifecycles,
                prepare_validated_quote_array(quote_range.ticks),
                DELAY_GRID_MS,
                hold_p25_ms=max(0, int(float(row.hold_p25_seconds) * 1000)),
                actual_entry_p95_ms=self.actual_entry_p95_ms,
                actual_exit_p95_ms=self.actual_exit_p95_ms,
                max_quote_wait_ms=2_000,
                expected_copy_cost=expected_cost,
            )
        mdd = drawdown.mdd_20d if drawdown is not None else 1.0
        return RawSleeveFactor(
            account=account, sleeve=sleeve, drawdown=drawdown, holding=holding,
            delay=delay, quote_complete=quote_complete, reasons=tuple(reasons),
            risk_return_5d=float(row.ret_5d) / max(1.0 + mdd, 1e-9),
            risk_return_20d=float(row.ret_20d) / max(1.0 + mdd, 1e-9),
            stress_return=float(row.stress_ret_20d),
            pf_quality=min(max(float(row.pf_20d) / 3.0, 0.0), 1.0),
            return_to_drawdown=max(float(row.ret_20d), 0.0) / max(mdd, 0.001),
        )

    def _public_row(self, sleeve_key: str, factor: Any, raw: RawSleeveFactor) -> dict[str, Any]:
        drawdown, holding, delay = raw.drawdown, raw.holding, raw.delay
        return {
            "sleeve_key": sleeve_key,
            "factor_ready": factor.eligible,
            "factor_base_score": factor.base_score,
            "factor_gate_reasons": "|".join(factor.gate_reasons),
            "historical_delay_enabled": self.historical_delay_enabled,
            "delay_factor_status": (
                "enabled" if self.historical_delay_enabled else "deferred_v0_1"
            ),
            **{f"factor_{name}": value for name, value in factor.factor_scores.items()},
            "mdd_20d": drawdown.mdd_20d if drawdown else 1.0,
            "mdd_60d": drawdown.mdd_60d if drawdown else 1.0,
            "current_drawdown": drawdown.current_drawdown if drawdown else 1.0,
            "max_daily_loss": drawdown.max_daily_loss if drawdown else 1.0,
            "equity_coverage_20d": bool(drawdown and drawdown.coverage_20d),
            "equity_coverage_60d": bool(drawdown and drawdown.coverage_60d),
            "intraday_equity_complete": bool(raw.account and raw.account.equity.intraday_complete),
            "delay_score": delay.delay_score if delay else 0.0,
            "entry_p95_ms": delay.actual_entry_p95_ms if delay else 0,
            "exit_p95_ms": delay.actual_exit_p95_ms if delay else 0,
            "entry_break_even_ms": delay.entry_break_even.delay_ms if delay else 0.0,
            "exit_break_even_ms": delay.exit_break_even.delay_ms if delay else 0.0,
            "combined_break_even_ms": delay.combined_break_even.delay_ms if delay else 0.0,
            "conservative_break_even_ms": delay.conservative_break_even.delay_ms if delay else 0.0,
            "delay_profit_retention": (
                delay.actual_combined.net_profit / delay.baseline.net_profit
                if delay and delay.baseline.net_profit > 0 else 0.0
            ),
            "delay_executable_ratio": delay.actual_combined.combined_executable_ratio if delay else 0.0,
            "holding_path_complete": bool(raw.sleeve and raw.sleeve.holding_path_complete),
            "overnight_ratio": holding.overnight_ratio if holding else 1.0,
            "weekend_ratio": holding.weekend_ratio if holding else 1.0,
            "swap_drag": holding.swap_drag if holding else 1.0,
            "long_loss_ratio": holding.long_loss_ratio if holding else 1.0,
            "loss_addition_ratio": holding.loss_addition_ratio if holding else 1.0,
        }
