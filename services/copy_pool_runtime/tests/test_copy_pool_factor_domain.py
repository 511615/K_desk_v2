from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import unittest

from copy_pool_factor_domain import (
    AdjustedEquityPoint,
    FactorInputs,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    TradeHoldingObservation,
    calculate_adjusted_equity_metrics,
    calculate_factor_result,
    calculate_holding_quality_metrics,
)


UTC = timezone.utc


def point(day: int, equity: float, cashflow: float = 0.0) -> AdjustedEquityPoint:
    return AdjustedEquityPoint(datetime(2026, 1, day, tzinfo=UTC), equity, cashflow)


def holding(
    opened: datetime,
    closed: datetime,
    *,
    swap: float = 0.0,
    profit: float = 10.0,
    long_loss_seconds: float = 0.0,
    additions_while_loss: bool = False,
) -> TradeHoldingObservation:
    return TradeHoldingObservation(
        opened, closed, swap, profit, long_loss_seconds, additions_while_loss
    )


def valid_inputs(**overrides: object) -> FactorInputs:
    values: dict[str, object] = {
        "risk_adjusted_return_5d": 1.0,
        "risk_adjusted_return_20d": 1.0,
        "spread_stress_return": 1.0,
        "pf_quality": 1.0,
        "delay_score": 1.0,
        "return_to_drawdown": 1.0,
        "holding_quality": 1.0,
        "mdd_20d": 0.10,
        "mdd_60d": 0.20,
        "current_drawdown": 0.10,
        "max_daily_loss": 0.08,
        "delay_gates_passed": True,
        "delay_factor_enabled": True,
    }
    values.update(overrides)
    return FactorInputs(**values)  # type: ignore[arg-type]


class AdjustedEquityMetricsTests(unittest.TestCase):
    def test_first_funded_anchor_ignores_prefunding_zero_and_its_own_cashflow(self) -> None:
        as_of = datetime(2026, 3, 2, tzinfo=UTC)

        metrics = calculate_adjusted_equity_metrics([
            AdjustedEquityPoint(as_of - timedelta(days=62), 0.0),
            AdjustedEquityPoint(as_of - timedelta(days=61), 1_000.0, 1_000.0),
            AdjustedEquityPoint(as_of - timedelta(days=20), 1_050.0),
            AdjustedEquityPoint(as_of, 1_050.0),
        ], as_of)

        self.assertNotIn("nonpositive_adjusted_balance_baseline", metrics.gate_reasons)
        self.assertNotIn("nonpositive_adjusted_equity", metrics.gate_reasons)
        self.assertEqual(metrics.mdd_60d, 0.0)

    def test_raw_negative_equity_remains_a_negative_equity_hard_failure(self) -> None:
        as_of = datetime(2026, 3, 2, tzinfo=UTC)

        metrics = calculate_adjusted_equity_metrics([
            AdjustedEquityPoint(as_of - timedelta(days=61), 100.0),
            # The withdrawal makes cashflow-adjusted capital positive, but the
            # platform still recorded an actual negative equity state.
            AdjustedEquityPoint(as_of - timedelta(days=2), -1.0, -100.0),
            AdjustedEquityPoint(as_of, 100.0),
        ], as_of)

        self.assertIn("negative_equity", metrics.gate_reasons)

    def test_post_loss_refunding_is_cashflow_adjusted_capital_exhaustion_not_negative_equity(self) -> None:
        as_of = datetime(2026, 3, 2, tzinfo=UTC)

        metrics = calculate_adjusted_equity_metrics([
            AdjustedEquityPoint(as_of - timedelta(days=61), 1_000.0, 1_000.0),
            AdjustedEquityPoint(as_of - timedelta(days=30), 0.0),
            AdjustedEquityPoint(as_of - timedelta(days=29), 1_000.0, 1_000.0),
            AdjustedEquityPoint(as_of, 1_000.0),
        ], as_of)

        self.assertIn("cashflow_adjusted_capital_exhaustion", metrics.gate_reasons)
        self.assertNotIn("negative_equity", metrics.gate_reasons)
        self.assertTrue(metrics.daily_coverage_complete)

    def test_external_cashflow_does_not_create_drawdown(self) -> None:
        as_of = datetime(2026, 3, 2, tzinfo=UTC)
        metrics = calculate_adjusted_equity_metrics([
            AdjustedEquityPoint(as_of - timedelta(days=60), 100.0),
            AdjustedEquityPoint(as_of - timedelta(days=30), 200.0, 100.0),
            AdjustedEquityPoint(as_of, 200.0),
        ], as_of)
        self.assertEqual(metrics.mdd_20d, 0.0)
        self.assertEqual(metrics.mdd_60d, 0.0)
        self.assertTrue(metrics.coverage_20d)
        self.assertTrue(metrics.coverage_60d)

    def test_real_trading_loss_creates_drawdown_and_recovery(self) -> None:
        as_of = datetime(2026, 3, 2, tzinfo=UTC)
        metrics = calculate_adjusted_equity_metrics([
            AdjustedEquityPoint(as_of - timedelta(days=60), 100.0),
            AdjustedEquityPoint(as_of - timedelta(days=2), 80.0),
            AdjustedEquityPoint(as_of, 100.0),
        ], as_of)
        self.assertAlmostEqual(metrics.mdd_60d, 0.20)
        self.assertEqual(metrics.current_drawdown, 0.0)
        self.assertEqual(metrics.max_recovery_seconds, 60 * SECONDS_PER_DAY)
        self.assertAlmostEqual(metrics.max_consecutive_loss_usd, 20.0)
        self.assertEqual(metrics.max_consecutive_losses, 1)

    def test_prefunding_zero_is_ignored_but_short_coverage_still_fails(self) -> None:
        as_of = datetime(2026, 3, 2, tzinfo=UTC)
        metrics = calculate_adjusted_equity_metrics([
            AdjustedEquityPoint(as_of - timedelta(days=19), 0.0),
            AdjustedEquityPoint(as_of, 20.0),
        ], as_of)
        self.assertFalse(metrics.coverage_20d)
        self.assertFalse(metrics.coverage_60d)
        self.assertNotIn("nonpositive_adjusted_balance_baseline", metrics.gate_reasons)
        self.assertIn("insufficient_equity_coverage_20d", metrics.gate_reasons)

    def test_daily_loss_uses_start_of_utc_day_to_low(self) -> None:
        as_of = datetime(2026, 3, 2, tzinfo=UTC)
        start = datetime(2026, 1, 1, 0, tzinfo=UTC)
        metrics = calculate_adjusted_equity_metrics([
            AdjustedEquityPoint(start - timedelta(minutes=1), 100.0),
            AdjustedEquityPoint(start, 100.0),
            AdjustedEquityPoint(start + timedelta(hours=12), 92.0),
        ], as_of)
        self.assertAlmostEqual(metrics.max_daily_loss, 0.08)
        self.assertTrue(metrics.daily_coverage_complete)

    def test_window_mdd_uses_pre_cutoff_peak_and_nonpositive_is_full_drawdown(self) -> None:
        as_of = datetime(2026, 3, 2, tzinfo=UTC)
        metrics = calculate_adjusted_equity_metrics([
            AdjustedEquityPoint(as_of - timedelta(days=61), 100.0),
            AdjustedEquityPoint(as_of - timedelta(days=21), 160.0),
            AdjustedEquityPoint(as_of - timedelta(days=19), 80.0),
            AdjustedEquityPoint(as_of, 80.0),
        ], as_of)
        self.assertAlmostEqual(metrics.mdd_20d, 0.50)

        nonpositive = calculate_adjusted_equity_metrics([
            AdjustedEquityPoint(as_of - timedelta(days=61), 100.0),
            AdjustedEquityPoint(as_of - timedelta(days=21), 100.0),
            AdjustedEquityPoint(as_of - timedelta(days=1), -1.0),
            AdjustedEquityPoint(as_of, 10.0),
        ], as_of)
        self.assertEqual(nonpositive.mdd_20d, 1.0)
        self.assertIn("negative_equity", nonpositive.gate_reasons)
        self.assertIn("cashflow_adjusted_capital_exhaustion", nonpositive.gate_reasons)

    def test_stale_history_fails_but_first_funded_day_supplies_its_baseline(self) -> None:
        as_of = datetime(2026, 3, 2, tzinfo=UTC)
        stale = calculate_adjusted_equity_metrics([
            AdjustedEquityPoint(as_of - timedelta(days=61), 100.0),
            AdjustedEquityPoint(as_of - timedelta(days=2), 101.0),
        ], as_of)
        self.assertFalse(stale.coverage_20d)
        self.assertIn("stale_equity_coverage_20d", stale.gate_reasons)

        first_funded_day = calculate_adjusted_equity_metrics([
            AdjustedEquityPoint(datetime(2026, 1, 1, 17, 1, tzinfo=UTC), 100.0),
            AdjustedEquityPoint(datetime(2026, 1, 1, 18, tzinfo=UTC), 92.0),
            AdjustedEquityPoint(as_of, 92.0),
        ], as_of, rollover_time=time(17, 0))
        self.assertTrue(first_funded_day.daily_coverage_complete)
        self.assertAlmostEqual(first_funded_day.max_daily_loss, 0.08)

    def test_unrecovered_drawdown_and_flat_change_keep_equity_downward_chain(self) -> None:
        as_of = datetime(2026, 3, 2, tzinfo=UTC)
        metrics = calculate_adjusted_equity_metrics([
            AdjustedEquityPoint(as_of - timedelta(days=60), 100.0),
            AdjustedEquityPoint(as_of - timedelta(days=3), 90.0),
            AdjustedEquityPoint(as_of - timedelta(days=2), 90.0),
            AdjustedEquityPoint(as_of, 80.0),
        ], as_of)
        self.assertEqual(metrics.max_consecutive_losses, 2)
        self.assertAlmostEqual(metrics.max_consecutive_loss_usd, 20.0)
        self.assertEqual(metrics.max_recovery_seconds, 60 * SECONDS_PER_DAY)

    def test_rollover_daily_boundary_uses_prior_trading_day_equity(self) -> None:
        as_of = datetime(2026, 3, 2, tzinfo=UTC)
        metrics = calculate_adjusted_equity_metrics([
            AdjustedEquityPoint(datetime(2025, 12, 31, 16, tzinfo=UTC), 100.0),
            AdjustedEquityPoint(datetime(2026, 1, 1, 17, 1, tzinfo=UTC), 100.0),
            AdjustedEquityPoint(datetime(2026, 1, 1, 18, tzinfo=UTC), 92.0),
            AdjustedEquityPoint(as_of, 92.0),
        ], as_of, rollover_time=time(17, 0))
        self.assertTrue(metrics.daily_coverage_complete)
        self.assertAlmostEqual(metrics.max_daily_loss, 0.08)

    def test_daily_coverage_ignores_partial_first_trading_day_at_60_day_cutoff(self) -> None:
        as_of = datetime(2026, 3, 2, 12, tzinfo=UTC)
        metrics = calculate_adjusted_equity_metrics([
            # The 60-day cutoff is 2026-01-01 12:00. This observation belongs
            # to the trading day that began on 2025-12-31 at 17:00, so there is
            # intentionally no pre-boundary point for that partial first day.
            AdjustedEquityPoint(datetime(2026, 1, 1, 12, tzinfo=UTC), 100.0),
            AdjustedEquityPoint(datetime(2026, 1, 1, 17, tzinfo=UTC), 100.0),
            AdjustedEquityPoint(datetime(2026, 1, 1, 18, tzinfo=UTC), 92.0),
            AdjustedEquityPoint(as_of, 92.0),
        ], as_of, rollover_time=time(17, 0))

        self.assertTrue(metrics.daily_coverage_complete)
        self.assertNotIn("missing_daily_baseline_2025-12-31", metrics.gate_reasons)

    def test_rollover_timestamp_anchor_is_a_daily_start_baseline(self) -> None:
        as_of = datetime(2026, 3, 2, 19, tzinfo=UTC)
        metrics = calculate_adjusted_equity_metrics([
            AdjustedEquityPoint(datetime(2026, 1, 1, 12, tzinfo=UTC), 100.0),
            AdjustedEquityPoint(datetime(2026, 1, 2, 17, tzinfo=UTC), 100.0),
            AdjustedEquityPoint(datetime(2026, 1, 2, 20, tzinfo=UTC), 92.0),
            AdjustedEquityPoint(as_of, 92.0),
        ], as_of, rollover_time=time(17, 0))

        self.assertTrue(metrics.daily_coverage_complete)
        self.assertAlmostEqual(metrics.max_daily_loss, 0.08)


class HoldingQualityMetricsTests(unittest.TestCase):
    def test_overnight_boundaries_and_p90_penalty(self) -> None:
        monday = datetime(2026, 1, 5, 20, tzinfo=UTC)
        same_day = [holding(monday, monday + timedelta(minutes=30)) for _ in range(9)]
        overnight = holding(monday, monday + timedelta(hours=6))
        at_ten = calculate_holding_quality_metrics(same_day + [overnight])
        self.assertAlmostEqual(at_ten.overnight_ratio, 0.10)
        self.assertEqual(at_ten.overnight_multiplier, 1.0)

        at_thirty = calculate_holding_quality_metrics(
            [holding(monday, monday + timedelta(minutes=30)) for _ in range(7)]
            + [overnight] * 3
        )
        self.assertAlmostEqual(at_thirty.overnight_ratio, 0.30)
        self.assertAlmostEqual(at_thirty.overnight_multiplier, 0.70)

        at_sixty = calculate_holding_quality_metrics(
            [holding(monday, monday + timedelta(minutes=30)) for _ in range(4)]
            + [overnight] * 6
        )
        self.assertFalse(at_sixty.hard_failed)
        self.assertAlmostEqual(at_sixty.overnight_ratio, 0.60)

        over_sixty = calculate_holding_quality_metrics([overnight] * 10)
        self.assertTrue(over_sixty.hard_failed)
        self.assertIn("overnight_ratio_over_60pct", over_sixty.gate_reasons)

        long_hold = calculate_holding_quality_metrics([
            holding(monday, monday + timedelta(hours=24))
        ])
        self.assertNotIn("hold_p90_over_24h", long_hold.gate_reasons)
        self.assertAlmostEqual(long_hold.hold_p90_multiplier, 0.70)

        too_long = calculate_holding_quality_metrics([
            holding(monday, monday + timedelta(hours=24, seconds=1))
        ])
        self.assertIn("hold_p90_over_24h", too_long.gate_reasons)

    def test_weekend_count_ratio_swap_and_long_loss(self) -> None:
        friday = datetime(2026, 1, 2, 20, tzinfo=UTC)
        monday = datetime(2026, 1, 5, 2, tzinfo=UTC)
        one_weekend = holding(friday, monday, swap=-3.0, profit=10.0, long_loss_seconds=SECONDS_PER_HOUR)
        ratio_failure = calculate_holding_quality_metrics(
            [one_weekend] + [holding(friday, friday + timedelta(minutes=10)) for _ in range(32)]
        )
        self.assertIn("weekend_ratio_over_3pct", ratio_failure.gate_reasons)
        self.assertAlmostEqual(ratio_failure.swap_drag, 3.0 / 330.0)
        self.assertGreater(ratio_failure.long_loss_ratio, 0.0)

        second_weekend = calculate_holding_quality_metrics([
            one_weekend,
            holding(datetime(2026, 1, 9, 20, tzinfo=UTC), datetime(2026, 1, 12, 2, tzinfo=UTC)),
            holding(friday, friday + timedelta(minutes=10)),
        ])
        self.assertIn("weekend_count_at_least_2", second_weekend.gate_reasons)

        exact_ratio = calculate_holding_quality_metrics(
            [one_weekend] * 3 + [holding(friday, friday + timedelta(minutes=10)) for _ in range(97)]
        )
        self.assertAlmostEqual(exact_ratio.weekend_ratio, 0.03)
        self.assertNotIn("weekend_ratio_over_3pct", exact_ratio.gate_reasons)

    def test_server_offset_and_rollover_control_overnight_classification(self) -> None:
        opened = datetime(2026, 1, 6, 20, 30, tzinfo=UTC)
        closed = datetime(2026, 1, 6, 22, 30, tzinfo=UTC)
        observation = holding(opened, closed)
        midnight_rollover = calculate_holding_quality_metrics(
            [observation], server_utc_offset=3, rollover_time=time(0, 0)
        )
        two_am_rollover = calculate_holding_quality_metrics(
            [observation], server_utc_offset=3, rollover_time=time(2, 0)
        )
        self.assertEqual(midnight_rollover.overnight_ratio, 1.0)
        self.assertEqual(two_am_rollover.overnight_ratio, 0.0)
        self.assertEqual(two_am_rollover.natural_day_ratio, 1.0)

    def test_window_excludes_old_weekends_and_quality_penalties_include_all_components(self) -> None:
        as_of = datetime(2026, 3, 2, tzinfo=UTC)
        old_weekend = holding(
            datetime(2025, 12, 26, 20, tzinfo=UTC),
            datetime(2025, 12, 29, 2, tzinfo=UTC),
        )
        recent = holding(
            as_of - timedelta(days=3, hours=2),
            as_of - timedelta(days=3, hours=1),
            swap=1.0,
            profit=10.0,
        )
        windowed = calculate_holding_quality_metrics([old_weekend, recent], as_of=as_of)
        self.assertEqual(windowed.observation_count, 1)
        self.assertEqual(windowed.weekend_count, 0)
        self.assertEqual(windowed.swap_drag, 0.0)
        self.assertEqual(windowed.swap_multiplier, 1.0)

        base = datetime(2026, 1, 5, 10, tzinfo=UTC)
        swap_at_five = calculate_holding_quality_metrics([
            holding(base, base + timedelta(minutes=10), swap=-0.5, profit=10.0)
        ])
        swap_at_twenty = calculate_holding_quality_metrics([
            holding(base, base + timedelta(minutes=10), swap=-2.0, profit=10.0)
        ])
        swap_at_fifty = calculate_holding_quality_metrics([
            holding(base, base + timedelta(minutes=10), swap=-5.0, profit=10.0)
        ])
        swap_without_positive_gross_profit = calculate_holding_quality_metrics([
            holding(base, base + timedelta(minutes=10), swap=-1.0, profit=-10.0)
        ])
        self.assertEqual(swap_at_five.swap_multiplier, 1.0)
        self.assertAlmostEqual(swap_at_twenty.swap_multiplier, 0.70)
        self.assertAlmostEqual(swap_at_fifty.swap_multiplier, 0.20)
        self.assertEqual(swap_without_positive_gross_profit.swap_drag, 1.0)
        self.assertEqual(swap_without_positive_gross_profit.swap_multiplier, 0.20)

        long_rows = [holding(base, base + timedelta(hours=2), long_loss_seconds=SECONDS_PER_HOUR)]
        long_rows.extend(holding(base, base + timedelta(hours=2)) for _ in range(9))
        long_at_ten = calculate_holding_quality_metrics(long_rows)
        self.assertEqual(long_at_ten.long_loss_multiplier, 1.0)
        additions = [holding(base, base + timedelta(minutes=10), additions_while_loss=True)]
        additions.extend(holding(base, base + timedelta(minutes=10)) for _ in range(19))
        additions_at_five = calculate_holding_quality_metrics(additions)
        self.assertEqual(additions_at_five.loss_addition_multiplier, 1.0)
        expected = (
            0.30 * additions_at_five.hold_p90_multiplier
            + 0.25 * additions_at_five.overnight_multiplier
            + 0.15 * additions_at_five.weekend_multiplier
            + 0.10 * additions_at_five.swap_multiplier
            + 0.10 * additions_at_five.long_loss_multiplier
            + 0.10 * additions_at_five.loss_addition_multiplier
        )
        self.assertAlmostEqual(additions_at_five.quality_multiplier, expected)


class FactorResultTests(unittest.TestCase):
    def test_cost_profit_recent_coverage_model_is_primary_when_provided(self) -> None:
        result = calculate_factor_result(valid_inputs(
            cost_profit_score=1.0,
            recent_strength_score=0.0,
            cost_coverage_score=0.0,
        ))
        self.assertAlmostEqual(result.base_score, 0.50)

    def test_cost_model_still_honors_noncompensable_hard_gates(self) -> None:
        result = calculate_factor_result(valid_inputs(
            cost_profit_score=1.0,
            recent_strength_score=1.0,
            cost_coverage_score=1.0,
            mdd_20d=0.100001,
        ))
        self.assertFalse(result.eligible)
        self.assertIn("mdd_20d_over_10pct", result.gate_reasons)

    def test_fixed_weights_sum_to_one_and_inputs_clamp(self) -> None:
        result = calculate_factor_result(valid_inputs(
            risk_adjusted_return_5d=2.0,
            risk_adjusted_return_20d=-1.0,
            spread_stress_return=0.5,
        ))
        self.assertTrue(result.eligible)
        self.assertAlmostEqual(sum(result.factor_scores.values()), 5.5)
        self.assertAlmostEqual(result.base_score, 0.775)

    def test_equal_thresholds_pass_and_hard_gates_cannot_be_compensated(self) -> None:
        passing = calculate_factor_result(valid_inputs())
        self.assertTrue(passing.eligible)
        self.assertEqual(passing.base_score, 1.0)

        rejected = calculate_factor_result(valid_inputs(mdd_20d=0.100001))
        self.assertFalse(rejected.eligible)
        self.assertEqual(rejected.base_score, 1.0)
        self.assertIn("mdd_20d_over_10pct", rejected.gate_reasons)

        delay_rejected = calculate_factor_result(valid_inputs(delay_gates_passed=False))
        self.assertFalse(delay_rejected.eligible)
        self.assertIn("delay_hard_gate_failed", delay_rejected.gate_reasons)

    def test_deferred_delay_factor_is_normalized_out_and_not_a_hard_gate(self) -> None:
        result = calculate_factor_result(valid_inputs(
            delay_score=0.0,
            delay_gates_passed=False,
            delay_factor_enabled=False,
        ))
        self.assertTrue(result.eligible)
        self.assertAlmostEqual(result.base_score, 1.0)
        self.assertNotIn("delay_hard_gate_failed", result.gate_reasons)

    def test_coverage_and_holding_failures_are_hard_gates(self) -> None:
        result = calculate_factor_result(valid_inputs(
            coverage_20d=False,
            holding_hard_failed=True,
            stop_out_compensation=True,
            negative_equity=True,
            nonpositive_balance_baseline=True,
            daily_drawdown_coverage=False,
        ))
        self.assertFalse(result.eligible)
        self.assertIn("insufficient_equity_coverage_20d", result.gate_reasons)
        self.assertIn("holding_quality_hard_gate_failed", result.gate_reasons)
        self.assertIn("stop_out_compensation", result.gate_reasons)
        self.assertIn("negative_equity", result.gate_reasons)
        self.assertIn("nonpositive_balance_baseline", result.gate_reasons)
        self.assertIn("incomplete_daily_drawdown_coverage", result.gate_reasons)

    def test_cashflow_adjusted_capital_exhaustion_is_a_hard_gate(self) -> None:
        result = calculate_factor_result(valid_inputs(
            cashflow_adjusted_capital_exhaustion=True,
        ))

        self.assertFalse(result.eligible)
        self.assertIn("cashflow_adjusted_capital_exhaustion", result.gate_reasons)


if __name__ == "__main__":
    unittest.main()
