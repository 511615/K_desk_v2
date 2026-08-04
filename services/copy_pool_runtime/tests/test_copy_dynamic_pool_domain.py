from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta, timezone

from copy_dynamic_pool_domain import (
    PoolTier, RankingCandidate, SchedulerState, SleeveDynamicState,
    acknowledge_accepted_pool_build, advance_expiry_recovery, advance_shadow_state, allowed_signal_delay_seconds,
    build_rank_universe, consume_redistribution, daily_rebuild, is_signal_expired,
    mark_scheduler_run, record_expired_signal, redistribution_available, scheduler_due,
    update_rank_state,
)


NOW = datetime(2026, 7, 29, 0, 0, tzinfo=timezone.utc)


def candidate(account: str, product: str, score: float, **changes: object) -> RankingCandidate:
    defaults: dict[str, object] = dict(
        sleeve_key=f"{account}|{product}", account_key=account, product=product, score=score,
        hard_eligible=True, activity_eligible=True, min_lot_feasible=True,
    )
    defaults.update(changes)
    return RankingCandidate(**defaults)  # type: ignore[arg-type]


class RankUniverseTests(unittest.TestCase):
    def test_unique_accounts_30_70_and_all_selected_sleeves(self) -> None:
        rows = [candidate(f"A{i:03}", "XAUUSD", 500 - i) for i in range(105)]
        rows += [candidate("A000", "NAS100", 1), candidate("A001", "USOIL", 2)]
        universe = build_rank_universe(rows)
        self.assertEqual(len(universe.monitor_accounts), 30)
        self.assertEqual(len(set(universe.monitor_accounts)), 30)
        self.assertEqual(len(universe.reserve_accounts), 70)
        self.assertIn("A000|NAS100", [item.sleeve_key for item in universe.monitor_sleeves])
        self.assertNotIn("A000", universe.reserve_accounts)

    def test_product_floor_cap_and_explicit_fallback(self) -> None:
        balanced = [candidate(f"G{i}", "GOLD", 100 - i) for i in range(20)]
        balanced += [candidate(f"N{i}", "NAS", 80 - i) for i in range(10)]
        balanced += [candidate(f"O{i}", "OIL", 70 - i) for i in range(10)]
        universe = build_rank_universe(balanced)
        self.assertEqual(set(universe.coverage_products), {"GOLD", "NAS", "OIL"})
        selected_products = [item.product for item in universe.primary_sleeves if item.account_key in universe.monitor_accounts]
        self.assertLessEqual(selected_products.count("GOLD"), 12)
        self.assertGreaterEqual(selected_products.count("GOLD"), 3)
        self.assertGreaterEqual(selected_products.count("NAS"), 3)
        self.assertGreaterEqual(selected_products.count("OIL"), 3)

        only_gold = build_rank_universe([candidate(f"G{i}", "GOLD", 100 - i) for i in range(20)])
        self.assertEqual(len(only_gold.monitor_accounts), 20)
        self.assertTrue(only_gold.cap_fallback_accounts)

    def test_product_floor_uses_secondary_product_sleeves(self) -> None:
        rows = [candidate(f"A{i}", "XAUUSD", 100 - i) for i in range(30)]
        rows += [candidate(f"A{i}", "NAS100", 10 - i) for i in range(3)]
        universe = build_rank_universe(rows)
        nas_accounts = {
            item.account_key for item in universe.monitor_sleeves if item.product == "NAS100"
        }
        self.assertEqual(nas_accounts, {"A0", "A1", "A2"})
        self.assertTrue({"A0", "A1", "A2"}.issubset(set(universe.monitor_accounts)))


class DynamicStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.row = candidate("A", "XAUUSD", 1.0)
        self.state = SleeveDynamicState(day_start_base_weight=0.10, frozen_daily_loss_budget=15.0)

    def test_two_qualifications_then_ten_minute_shadow(self) -> None:
        first = update_rank_state(self.state, self.row, NOW, active_zone=True, qualified_zone=True)
        self.assertEqual(first.tier, PoolTier.MONITOR)
        shadow = update_rank_state(first, self.row, NOW + timedelta(minutes=15), active_zone=True, qualified_zone=True)
        self.assertEqual(shadow.tier, PoolTier.ENTRY_SHADOW)
        active = advance_shadow_state(shadow, NOW + timedelta(minutes=25), shadow_health_ok=True)
        self.assertEqual(active.tier, PoolTier.ACTIVE)
        self.assertGreater(active.effective_weight, 0)

    def test_demo_fast_activation_uses_one_qualification_and_two_minute_shadow(self) -> None:
        shadow = update_rank_state(
            self.state,
            self.row,
            NOW,
            active_zone=True,
            qualified_zone=True,
            required_active_qualifications=1,
            entry_shadow_duration=timedelta(minutes=2),
        )
        self.assertEqual(shadow.tier, PoolTier.ENTRY_SHADOW)
        self.assertEqual(shadow.consecutive_active_qualifications, 1)
        self.assertEqual(shadow.shadow_ends_at, NOW + timedelta(minutes=2))
        self.assertEqual(
            advance_shadow_state(
                shadow,
                NOW + timedelta(minutes=1),
                shadow_health_ok=True,
                entry_shadow_duration=timedelta(minutes=2),
            ).tier,
            PoolTier.ENTRY_SHADOW,
        )
        self.assertEqual(
            advance_shadow_state(
                shadow,
                NOW + timedelta(minutes=2),
                shadow_health_ok=True,
                entry_shadow_duration=timedelta(minutes=2),
            ).tier,
            PoolTier.ACTIVE,
        )

    def test_demo_fast_activation_promotes_fresh_active_zone_without_shadow(self) -> None:
        active = update_rank_state(
            self.state,
            self.row,
            NOW,
            active_zone=True,
            qualified_zone=True,
            target_weight=0.07,
            required_active_qualifications=1,
            entry_shadow_duration=timedelta(minutes=2),
            fast_activation=True,
        )
        self.assertEqual(active.tier, PoolTier.ACTIVE)
        self.assertEqual(active.effective_weight, 0.07)
        self.assertEqual(active.consecutive_active_qualifications, 1)
        self.assertIsNone(active.shadow_started_at)

        blocked = update_rank_state(
            active,
            candidate("A", "XAUUSD", 1.0, activity_eligible=False),
            NOW + timedelta(minutes=15),
            active_zone=True,
            qualified_zone=True,
            target_weight=0.07,
            fast_activation=True,
        )
        self.assertEqual(blocked.tier, PoolTier.MONITOR)
        self.assertEqual(blocked.effective_weight, 0.0)

    def test_two_qualified_falls_hard_fail_weight_limit_release_and_frozen_budget(self) -> None:
        active = SleeveDynamicState(day_start_base_weight=.10, effective_weight=.10, tier=PoolTier.ACTIVE, frozen_daily_loss_budget=15)
        once = update_rank_state(active, self.row, NOW, active_zone=True, qualified_zone=False)
        self.assertEqual(once.tier, PoolTier.ACTIVE)
        self.assertLess(once.effective_weight, .10)
        gone = update_rank_state(once, self.row, NOW + timedelta(minutes=15), active_zone=False, qualified_zone=False)
        self.assertEqual(gone.effective_weight, 0)
        self.assertEqual(gone.tier, PoolTier.MONITOR)
        self.assertAlmostEqual(redistribution_available(gone, NOW + timedelta(minutes=44)), .03)
        self.assertAlmostEqual(redistribution_available(gone, NOW + timedelta(minutes=45)), .10)
        self.assertEqual(gone.frozen_daily_loss_budget, 15)
        rebuilt = daily_rebuild(gone, .2, 30, hard_eligible=True)
        self.assertEqual(rebuilt.frozen_daily_loss_budget, 30)

        hard = update_rank_state(active, candidate("A", "XAUUSD", 1, hard_eligible=False), NOW, active_zone=True, qualified_zone=True)
        self.assertEqual(hard.tier, PoolTier.HARD_REJECTED)
        self.assertEqual(hard.effective_weight, 0)
        rising = SleeveDynamicState(day_start_base_weight=.10, tier=PoolTier.ACTIVE)
        rising = update_rank_state(rising, self.row, NOW, active_zone=True, qualified_zone=True, target_weight=.12)
        self.assertAlmostEqual(rising.effective_weight, .005)
        rising = update_rank_state(rising, self.row, NOW + timedelta(minutes=1), active_zone=True, qualified_zone=True, target_weight=.12)
        self.assertAlmostEqual(rising.effective_weight, .005)
        rising = update_rank_state(rising, self.row, NOW + timedelta(minutes=15), active_zone=True, qualified_zone=True, target_weight=.12)
        self.assertAlmostEqual(rising.effective_weight, .01)
        rising = update_rank_state(rising, self.row, NOW + timedelta(minutes=30), active_zone=True, qualified_zone=True, target_weight=.12)
        self.assertAlmostEqual(rising.effective_weight, .01)

    def test_active_requires_executable_and_rank_cycle_is_idempotent(self) -> None:
        active = SleeveDynamicState(day_start_base_weight=.10, effective_weight=.10, tier=PoolTier.ACTIVE)
        blocked = update_rank_state(
            active, candidate("A", "XAUUSD", 1, min_lot_feasible=False), NOW,
            active_zone=True, qualified_zone=True,
        )
        self.assertEqual(blocked.tier, PoolTier.MONITOR)
        self.assertEqual(blocked.effective_weight, 0)

        first = update_rank_state(self.state, self.row, NOW, active_zone=True, qualified_zone=True)
        duplicate = update_rank_state(first, self.row, NOW, active_zone=True, qualified_zone=True)
        late = update_rank_state(first, self.row, NOW - timedelta(minutes=15), active_zone=True, qualified_zone=True)
        self.assertEqual(duplicate, first)
        self.assertEqual(late, first)
        self.assertEqual(first.consecutive_active_qualifications, 1)

    def test_shadow_requires_explicit_healthy_observation(self) -> None:
        first = update_rank_state(self.state, self.row, NOW, active_zone=True, qualified_zone=True)
        shadow = update_rank_state(first, self.row, NOW + timedelta(minutes=15), active_zone=True, qualified_zone=True)
        with self.assertRaises(TypeError):
            advance_shadow_state(shadow, NOW + timedelta(minutes=25))  # type: ignore[call-arg]
        unhealthy_at = NOW + timedelta(minutes=16)
        unhealthy = advance_shadow_state(
            shadow, unhealthy_at, shadow_health_ok=False,
        )
        self.assertEqual(unhealthy.tier, PoolTier.ENTRY_SHADOW)
        self.assertEqual(unhealthy.consecutive_active_qualifications, 2)
        self.assertEqual(unhealthy.shadow_started_at, unhealthy_at)
        self.assertEqual(unhealthy.shadow_ends_at, unhealthy_at + timedelta(minutes=10))
        self.assertEqual(unhealthy.effective_weight, 0)
        premature = advance_shadow_state(
            unhealthy, unhealthy_at + timedelta(minutes=9), shadow_health_ok=True,
        )
        self.assertEqual(premature.tier, PoolTier.ENTRY_SHADOW)
        promoted = advance_shadow_state(
            premature, unhealthy_at + timedelta(minutes=10), shadow_health_ok=True,
        )
        self.assertEqual(promoted.tier, PoolTier.ACTIVE)

        disqualified = advance_shadow_state(
            shadow, unhealthy_at, still_qualified=False, shadow_health_ok=True,
        )
        self.assertEqual(disqualified.tier, PoolTier.MONITOR)
        self.assertEqual(disqualified.consecutive_active_qualifications, 0)
        self.assertIsNone(disqualified.shadow_started_at)
        self.assertIsNone(disqualified.shadow_ends_at)

    def test_entry_exit_expiry_are_separate_and_suspend_after_three(self) -> None:
        state = self.state
        state = record_expired_signal(state, "entry", NOW)
        state = record_expired_signal(state, "entry", NOW + timedelta(minutes=1))
        self.assertEqual(state.tier, PoolTier.MONITOR)
        state = record_expired_signal(state, "exit", NOW + timedelta(minutes=2))
        self.assertEqual(state.tier, PoolTier.MONITOR)
        state = record_expired_signal(state, "entry", NOW + timedelta(minutes=3))
        self.assertEqual(state.tier, PoolTier.EXECUTION_SUSPENDED)
        self.assertEqual(allowed_signal_delay_seconds(20, 30), 10)
        self.assertFalse(is_signal_expired(10, 10))
        self.assertTrue(is_signal_expired(10.001, 10))
        with self.assertRaises(ValueError):
            is_signal_expired(math.nan, 10)
        recovery = advance_expiry_recovery(state, NOW + timedelta(minutes=13))
        self.assertEqual(recovery.tier, PoolTier.RECOVERY_SHADOW)
        self.assertEqual(
            advance_shadow_state(recovery, NOW + timedelta(minutes=23), shadow_health_ok=True).tier,
            PoolTier.MONITOR,
        )

    def test_roundtrip_naive_rejection_daily_hard_reset_and_single_consumption(self) -> None:
        state = SleeveDynamicState(
            day_start_base_weight=.1, effective_weight=.05, tier=PoolTier.HARD_REJECTED,
            frozen_daily_loss_budget=15, released_weight=.03,
            released_weight_events=((NOW, .01), (NOW + timedelta(minutes=5), .02)),
        )
        restored = SleeveDynamicState.from_dict(state.to_dict())
        self.assertEqual(restored, state)
        payload = state.to_dict()
        payload["last_ranked_at"] = "2026-07-29T00:00:00"
        with self.assertRaises(ValueError):
            SleeveDynamicState.from_dict(payload)
        reset = daily_rebuild(state, .2, 30, hard_eligible=True)
        self.assertEqual(reset.tier, PoolTier.MONITOR)
        self.assertEqual(reset.effective_weight, 0)
        self.assertEqual(daily_rebuild(state, .2, 30).tier, PoolTier.HARD_REJECTED)
        self.assertEqual(daily_rebuild(state, .2, 30, hard_eligible=False).tier, PoolTier.HARD_REJECTED)
        suspended = SleeveDynamicState(day_start_base_weight=.1, tier=PoolTier.EXECUTION_SUSPENDED)
        self.assertEqual(daily_rebuild(suspended, .2, 30).tier, PoolTier.EXECUTION_SUSPENDED)
        entry_shadow = SleeveDynamicState(
            day_start_base_weight=.1, tier=PoolTier.ENTRY_SHADOW,
            consecutive_active_qualifications=2, shadow_started_at=NOW,
            shadow_ends_at=NOW + timedelta(minutes=10),
        )
        reset_shadow = daily_rebuild(entry_shadow, .2, 30, hard_eligible=True)
        self.assertEqual(reset_shadow.tier, PoolTier.MONITOR)
        self.assertEqual(reset_shadow.consecutive_active_qualifications, 0)
        self.assertIsNone(reset_shadow.shadow_started_at)
        self.assertIsNone(reset_shadow.shadow_ends_at)
        available = redistribution_available(state, NOW + timedelta(minutes=31))
        self.assertEqual(available, .01)
        consumed_state, consumed = consume_redistribution(state, NOW + timedelta(minutes=31))
        self.assertEqual(consumed, .01)
        self.assertEqual(redistribution_available(consumed_state, NOW + timedelta(minutes=31)), 0)
        self.assertEqual(redistribution_available(consumed_state, NOW + timedelta(minutes=36)), .02)
        partially_consumed, consumed = consume_redistribution(state, NOW + timedelta(minutes=36), .015)
        self.assertAlmostEqual(consumed, .015)
        self.assertAlmostEqual(redistribution_available(partially_consumed, NOW + timedelta(minutes=36)), .015)
        consumed_twice, consumed = consume_redistribution(partially_consumed, NOW + timedelta(minutes=36))
        self.assertAlmostEqual(consumed, .015)
        self.assertEqual(redistribution_available(consumed_twice, NOW + timedelta(minutes=36)), 0)
        with self.assertRaises(ValueError):
            candidate("A", "X", math.nan)


class SchedulerTests(unittest.TestCase):
    def test_accepted_pool_build_satisfies_daily_scheduler_without_regressing(self) -> None:
        state = SchedulerState(last_daily_rebuild_date="2026-07-29")
        accepted = acknowledge_accepted_pool_build(state, "2026-07-30")
        self.assertEqual(accepted.last_daily_rebuild_date, "2026-07-30")
        after_0515 = datetime(2026, 7, 29, 22, 0, tzinfo=timezone.utc)
        self.assertFalse(scheduler_due(accepted, after_0515).daily_rebuild)
        self.assertIs(acknowledge_accepted_pool_build(accepted, "2026-07-29"), accepted)

    def test_beijing_0515_and_restart_guard(self) -> None:
        before = datetime(2026, 7, 28, 21, 14, tzinfo=timezone.utc)  # 05:14 Beijing
        after = before + timedelta(minutes=1)
        self.assertFalse(scheduler_due(SchedulerState(), before).daily_rebuild)
        state = SchedulerState.from_dict(SchedulerState().to_dict())
        self.assertTrue(scheduler_due(state, after).daily_rebuild)
        marked = mark_scheduler_run(state, after, daily_rebuild_run=True, risk=True, rank=True, discovery=True)
        restored = SchedulerState.from_dict(marked.to_dict())
        due = scheduler_due(restored, after + timedelta(seconds=9))
        self.assertFalse(due.daily_rebuild)
        self.assertFalse(due.risk)
        self.assertFalse(due.rank)
        self.assertFalse(due.discovery)
        self.assertTrue(scheduler_due(restored, after + timedelta(seconds=10)).risk)

    def test_scheduler_rejects_naive_and_invalid_dates_and_skips_weekends(self) -> None:
        with self.assertRaises(ValueError):
            SchedulerState(last_rank_at=datetime(2026, 7, 29, 0, 0))
        with self.assertRaises(ValueError):
            SchedulerState(last_daily_rebuild_date="2026-7-29")
        with self.assertRaises(ValueError):
            SchedulerState.from_dict({"last_daily_rebuild_date": "not-a-date"})

        saturday_after_0515 = datetime(2026, 7, 31, 21, 16, tzinfo=timezone.utc)
        self.assertFalse(scheduler_due(SchedulerState(), saturday_after_0515).daily_rebuild)
        self.assertFalse(
            scheduler_due(SchedulerState(), NOW, is_trading_day=lambda _day: False).daily_rebuild
        )


if __name__ == "__main__":
    unittest.main()
