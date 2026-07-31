from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kdesk.api.account_app import create_account_app
from kdesk.infrastructure.copy_pool_monitor import CopyPoolFileSnapshotRepository
from tests.test_api import make_test_settings


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def make_snapshot(root: Path) -> Path:
    output = root / "copy_pool"
    output.mkdir()
    (output / "status.json").write_text(
        json.dumps({
            "updated_at_beijing": "2026-07-28T20:43:19+08:00",
            "phase": "live",
            "server": "ACCMGlobal-Demo",
            "symbol": "XAUUSD",
            "risk_profile": "Capital10k",
            "balance_usd": 9978.35,
            "equity_usd": 10003.62,
            "position_cap_lots": 0.05,
            "hard_max_lots": 0.05,
            "cycle_loss_limit_usd": 75.0,
            "daily_loss_limit_usd": 200.0,
            "equity_floor_usd": 9500.0,
            "clients": 1,
            "active_weights": 0.02,
            "raw_target_lots": 0.10,
            "desired_target_lots": 0.05,
            "actual_strategy_lots": 0.05,
            "gross_long_lots": 0.11,
            "gross_short_lots": 0.01,
            "spread_price": 0.36,
            "quote_age_seconds": 0.08,
            "db_seconds_since_success": 0.0,
            "db_latency_p95_seconds": 1.2,
            "reconcile_streak": 12,
            "strategy_marked_pnl_usd": 3.62,
            "cycle_pnl_usd": 3.62,
            "terminal_trade_allowed": True,
            "live_execution_authorized": True,
            "logical_routes_scanned": 11,
            "logical_routes_expected": 11,
            "logical_routes_selected": 1,
            "physical_sources_scanned": 9,
            "physical_sources_selected": 1,
            "selected_source_staleness_seconds": 0.2,
            "db_poll_latency_p95_seconds": 0.4,
            "signal_latency_p95_seconds": 0.8,
            "execution_model": "independent_customer_positions_v2",
            "demo_fast_activation_requested": True,
            "demo_fast_activation_enabled": True,
            "entry_rank_qualifications_required": 1,
            "entry_shadow_minutes": 2,
            "monitor_sleeves": 1,
            "active_copy_clients": 1,
            "independent_source_positions": 1,
            "independent_demo_tickets": 1,
            "dynamic_sleeves": [
                {
                    "sleeve_key": "dbg_gb_mt5_live2:5200101|XAUUSD",
                    "tier": "active",
                    "base_weight": 0.03,
                    "effective_weight": 0.018,
                    "shadow_ends_at": "2026-07-28T20:52:00+08:00",
                    "entry_expired_count": 1,
                    "exit_expired_count": 2,
                },
                {
                    "sleeve_key": "private-unmapped-account|XAUUSD",
                    "tier": "active",
                },
            ],
            "scheduler": {
                "last_risk_at": "2026-07-28T20:43:10+08:00",
                "last_rank_at": "2026-07-28T20:30:00+08:00",
                "last_discovery_at": "2026-07-28T20:00:00+08:00",
                "last_daily_rebuild_date": "2026-07-28",
            },
            "source_health": [{
                "physical_key": "DBG:crm_vn_mt5_live2:MT5",
                "connection": "DBG",
                "platform": "MT5",
                "logical_routes": ["dbg_gb_mt5_live2"],
                "selected_clients": 1,
                "state": "ok",
                "latency_ms": 120,
                "age_seconds": 0.2,
            }],
        }),
        encoding="utf-8",
    )
    write_csv(output / "pool_public.csv", [{
        "client_alias": "C001",
        "product": "XAUUSD",
        "demo_symbol": "XAUUSD",
        "activity_eligible": True,
        "pool_status": "active_candidate",
        "pool_tier": "active",
        "factor_ready": True,
        "factor_base_score": 0.82,
        "historical_delay_enabled": False,
        "delay_factor_status": "deferred_v0_1",
        "hourly_score": 0.88,
        "recent_net_1h_usd": 4.2,
        "recent_net_4h_usd": 9.5,
        "current_comprehensive_net_20d_usd": 128.5,
        "hourly_hard_eligible": True,
        "hourly_activity_eligible": True,
        "factor_gate_reasons": "delay_stressed_profit|unsafe reason text",
        "factor_risk_adjusted_return_5d": 0.8,
        "factor_risk_adjusted_return_20d": 0.7,
        "factor_spread_stress_return": 0.6,
        "factor_pf_quality": 0.5,
        "factor_delay_score": 0.4,
        "factor_return_to_drawdown": 0.3,
        "factor_holding_quality": 0.2,
        "delay_score": 0.41,
        "entry_p95_ms": 1500,
        "exit_p95_ms": 1800,
        "entry_break_even_ms": 9200,
        "exit_break_even_ms": 7500,
        "combined_break_even_ms": 6100,
        "conservative_break_even_ms": 6100,
        "delay_profit_retention": 0.72,
        "delay_executable_ratio": 0.91,
        "mdd_20d": 0.04,
        "mdd_60d": 0.08,
        "current_drawdown": 0.02,
        "max_daily_loss": 0.03,
        "equity_coverage_20d": True,
        "equity_coverage_60d": True,
        "intraday_equity_complete": True,
        "holding_path_complete": True,
        "overnight_ratio": 0.08,
        "weekend_ratio": 0.01,
        "swap_drag": 0.04,
        "long_loss_ratio": 0.12,
        "loss_addition_ratio": 0.05,
        "hold_p25_seconds": 90,
        "hold_p90_seconds": 7200,
        "short_trade_ratio": 0.05,
        "dynamic_score": 0.91,
        "adjusted_score": 0.93,
        "is_abook": True,
        "median_hold_seconds": 180,
        "hold_multiplier": 1,
        "live_base_weight": 0.03,
        "comprehensive_net_20d_usd": 120,
        "equity_pre_usd": 1000,
        "floating_pnl_usd": -12.5,
        "floating_loss_ratio": 0.0125,
        "margin_to_equity": 0.18,
        "open_position_count": 2,
        "open_gross_lots": 0.4,
        "xau_gross_lots": 0.4,
        "xau_net_lots": 0.2,
        "xau_hedge_ratio": 0.5,
        "oldest_open_seconds": 7200,
        "quality_net_5d_usd": 45,
        "quality_net_20d_usd": 120,
        "open_risk_multiplier": 0.375,
    }])
    write_csv(output / "events_public.csv", [{
        "event_id": "E1",
        "time_beijing": "2026-07-28T20:42:42+08:00",
        "client_alias": "C001",
        "source_side": "BUY",
        "source_entry": 0,
        "source_lots": 0.2,
        "product": "XAUUSD",
        "effective_weight": 0.018,
        "raw_target_lots": 0.10,
        "desired_target_lots": 0.05,
        "actual_strategy_lots": 0.05,
        "gross_long_lots": 0.11,
        "gross_short_lots": 0.01,
        "db_latency_seconds": 0.4,
        "phase": "live",
        "reason": "private implementation detail",
    }])
    write_csv(output / "orders_public.csv", [{
        "order_event": "O1",
        "time_beijing": "2026-07-28T20:40:25+08:00",
        "action": "TARGET_RECONCILE",
        "before_lots": 0.04,
        "target_lots": 0.05,
        "after_lots": 0.05,
        "bid": 4000,
        "ask": 4000.36,
        "spread_price": 0.36,
        "quote_age_seconds": 0.1,
        "retcode": 10009,
        "comment": "Request executed",
    }])
    write_csv(output / "status_timeline_public.csv", [{
        "time_beijing": "2026-07-28T20:40:00+08:00",
        "phase": "live",
        "equity_usd": 10003.62,
        "position_cap_lots": 0.05,
        "active_weights": 0.02,
        "raw_target_lots": 0.10,
        "desired_target_lots": 0.05,
        "actual_strategy_lots": 0.05,
        "gross_long_lots": 0.11,
        "gross_short_lots": 0.01,
        "spread_price": 0.36,
        "db_latency_p95_seconds": 1.2,
        "strategy_marked_pnl_usd": 3.62,
        "cycle_pnl_usd": 3.62,
        "reconcile_streak": 12,
    }])
    (output / "client_routes_private.json").write_text(json.dumps({
        "clients": [{
            "alias": "C001",
            "login": 5200101,
            "platform": "MT5",
        "server": "DBG GB MT5 Live2",
        "account_key": "dbg_gb_mt5_live2:5200101",
        "route_key": "dbg_gb_mt5_live2",
        "physical_key": "DBG:crm_vn_mt5_live2:MT5",
        }],
    }), encoding="utf-8")
    (output / "runtime_state_private.json").write_text(json.dumps({
        "positions": [{"account_key": "dbg_gb_mt5_live2:5200101", "position_id": 7, "product": "XAUUSD", "lots": 0.2}],
        "intraday_net_usd": {"dbg_gb_mt5_live2:5200101": -8.5},
        "floating_pnl_usd": {"dbg_gb_mt5_live2:5200101": -12.5},
        "dynamic_evaluation_usd": {"dbg_gb_mt5_live2:5200101": -21.0},
        "open_risk_by_account": {"dbg_gb_mt5_live2:5200101": {
            "floating_pnl_usd": -12.5,
            "open_position_count": 2,
            "open_gross_lots": 0.4,
            "xau_gross_lots": 0.4,
            "xau_net_lots": 0.2,
            "xau_hedge_ratio": 0.5,
            "oldest_open_seconds": 7200,
            "margin_to_equity": 0.18,
            "floating_loss_ratio": 0.0125,
        }},
        "effective_weights": {"dbg_gb_mt5_live2:5200101": 0.018},
        "effective_product_weights": {"dbg_gb_mt5_live2:5200101|XAUUSD": 0.018},
        "independent_copy": {
            "clients": {"dbg_gb_mt5_live2:5200101": {
                "client_alias": "C001",
                "base_weight": 0.03,
                "effective_weight": 0.018,
                "loss_budget_usd": 4.5,
                "realized_pnl_usd": -1.0,
                "floating_pnl_usd": -0.5,
                "total_pnl_usd": -1.5,
                "loss_used_usd": 1.5,
                "loss_usage": 1 / 3,
                "loss_multiplier": 0.8666667,
                "status": "reduced",
                "reduction_reason": "客户亏损额度使用 33.3%",
            }},
            "positions": {"private-source-key": {
                "source_key": "private-source-key",
                "account_key": "dbg_gb_mt5_live2:5200101",
                "client_alias": "C001",
                "product": "XAUUSD",
                "source_position_id": 7,
                "source_lots": 0.2,
                "copied_lots": 0.01,
                "copied_signed_lots": 0.01,
                "copy_eligible": True,
                "status": "active",
                "children": [{
                    "ticket": 90001,
                    "lots": 0.01,
                    "side": 1,
                    "open_time": "2026-07-28T20:42:43+08:00",
                    "open_price": 4000.36,
                }],
            }},
        },
    }), encoding="utf-8")
    (output / "source_coverage.json").write_text(json.dumps({
        "logical_routes_expected": 11,
        "logical_routes_scanned": 11,
        "physical_sources_expected": 9,
        "physical_sources_scanned": 9,
        "monitor_accounts": 8,
        "reserve_accounts": 0,
        "active_accounts": 7,
        "selected_sleeves": 8,
        "active_sleeves": 7,
        "selected_products": ["XAUUSD"],
        "active_products": ["XAUUSD"],
        "product_weight_cap_fallback": True,
        "hourly_discovery": {
            "as_of": "2026-07-28T21:00:00+08:00",
            "build_as_of": "2026-07-28T05:15:00+08:00",
            "factor_ready_sleeves_scanned": 894,
            "monitor_accounts": 30,
            "reserve_accounts": 70,
        },
        "sources": [{
            "physical_key": "DBG:crm_vn_mt5_live2:MT5",
            "connection": "DBG",
            "platform": "MT5",
            "logical_routes": ["dbg_gb_mt5_live2"],
            "candidate_accounts": 100,
            "eligible_accounts": 20,
            "selected_clients": 1,
            "state": "ok",
        }],
    }), encoding="utf-8")
    return output


def test_copy_pool_reader_projects_detailed_account_identity(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)
    payload = CopyPoolFileSnapshotRepository(output).dashboard(
        timeline_limit=30,
        event_limit=10,
        order_limit=10,
    )

    assert payload["available"] is True
    assert payload["routeCoverage"] == {"linked": 1, "total": 1}
    row = payload["pool"][0]
    assert row["clientAlias"] == "C001"
    assert row["clientProductKey"] == "C001|XAUUSD"
    assert row["product"] == "XAUUSD"
    assert row["accountLogin"] == "5200101"
    assert row["accountPlatform"] == "MT5"
    assert row["accountServer"] == "DBG GB MT5 Live2"
    assert row["routeKey"] == "dbg_gb_mt5_live2"
    assert row["physicalSource"] == "DBG:crm_vn_mt5_live2:MT5"
    assert row["poolTier"] == "active"
    assert row["factorReady"] is True
    assert row["factorBaseScore"] == 0.82
    assert row["historicalDelayFactorEnabled"] is False
    assert row["delayFactorStatus"] == "deferred_v0_1"
    assert row["hourlyScore"] == 0.88
    assert row["recentNet1hUsd"] == 4.2
    assert row["recentNet4hUsd"] == 9.5
    assert row["currentComprehensiveNet20dUsd"] == 128.5
    assert row["hourlyHardEligible"] is True
    assert row["factorGateReasons"] == ["delay_stressed_profit"]
    assert row["factorScores"]["delay"] == 0.4
    assert row["delay"] == {
        "score": 0.41,
        "entryP95Ms": 1500,
        "exitP95Ms": 1800,
        "entryBreakEvenMs": 9200.0,
        "exitBreakEvenMs": 7500.0,
        "combinedBreakEvenMs": 6100.0,
        "conservativeBreakEvenMs": 6100.0,
        "profitRetention": 0.72,
        "executableRatio": 0.91,
    }
    assert row["drawdown"]["mdd60d"] == 0.08
    assert row["holdingQuality"]["overnightRatio"] == 0.08
    assert row["dynamicState"]["tier"] == "active"
    assert row["dynamicState"]["entryExpiredCount"] == 1
    assert row["effectiveWeight"] == pytest.approx(0.0108)
    assert row["weightState"] == "reduced"
    assert row["intradayNetUsd"] == -8.5
    assert row["intradayRealizedUsd"] == -8.5
    assert row["floatingPnlUsd"] == -12.5
    assert row["dynamicEvaluationUsd"] == -21.0
    assert row["openPositionCount"] == 2
    assert row["openGrossLots"] == 0.4
    assert row["xauGrossLots"] == 0.4
    assert row["xauNetLots"] == 0.2
    assert row["xauHedgeRatio"] == 0.5
    assert row["oldestOpenSeconds"] == 7200
    assert row["openRiskMultiplier"] == 0.375
    assert row["virtualPositionLots"] == 0.2
    assert row["detailPath"] == "/copy-pool/accounts/C001"
    assert payload["events"][0]["accountLogin"] == "5200101"
    assert payload["clientRisks"][0]["accountLogin"] == "5200101"
    assert payload["copyPositions"][0]["accountLogin"] == "5200101"
    assert payload["ticketMappings"][0]["accountLogin"] == "5200101"
    assert "login" not in row
    assert "clients" not in row
    assert "runtime_state_private" not in json.dumps(payload).lower()
    assert payload["sourceCoverage"]["logicalScanned"] == 11
    assert payload["sourceCoverage"]["physicalScanned"] == 9
    assert payload["sourceCoverage"]["monitorAccounts"] == 8
    assert payload["sourceCoverage"]["activeAccounts"] == 7
    assert payload["sourceCoverage"]["activeProducts"] == ["XAUUSD"]
    assert payload["sourceCoverage"]["productWeightCapFallback"] is True
    assert payload["sourceCoverage"]["sources"][0]["candidateAccounts"] == 100
    assert payload["sourceCoverage"]["hourlyDiscovery"]["factorReadySleevesScanned"] == 894
    assert payload["sourceCoverage"]["hourlyDiscovery"]["monitorAccounts"] == 30
    assert payload["status"]["executionModel"] == "independent_customer_positions_v2"
    assert payload["status"]["demoFastActivationRequested"] is True
    assert payload["status"]["demoFastActivationEnabled"] is True
    assert payload["status"]["entryRankQualificationsRequired"] == 1
    assert payload["status"]["entryShadowMinutes"] == 2
    assert payload["clientRisks"][0]["lossBudgetUsd"] == 4.5
    assert payload["copyPositions"][0]["demoTickets"] == [90001]
    assert payload["ticketMappings"][0]["demoTicket"] == 90001
    assert payload["exposures"][0]["grossLots"] == 0.01
    assert payload["dynamicSleeves"] == [row["dynamicState"]]
    assert payload["scheduler"] == {
        "lastRiskAt": "2026-07-28T12:43:10+00:00",
        "lastRankAt": "2026-07-28T12:30:00+00:00",
        "lastDiscoveryAt": "2026-07-28T12:00:00+00:00",
        "lastDailyRebuildDate": "2026-07-28",
    }
    assert "private-source-key" not in json.dumps(payload)
    assert "private-unmapped-account" not in json.dumps(payload)


def test_copy_pool_projects_only_current_child_tickets_with_exact_pnl_evidence(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)
    state_path = output / "runtime_state_private.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    position = state["independent_copy"]["positions"]["private-source-key"]
    position.update({
        "source_open_price": 4000.1,
        "source_opened_at": "2026-07-28T20:42:42+08:00",
        "source_realized_pnl_usd": 1.25,
        "source_floating_pnl_usd": -0.75,
        "source_total_pnl_usd": 0.5,
        "demo_realized_pnl_usd": 0.1,
        "demo_floating_pnl_usd": 0.2,
        "demo_total_pnl_usd": 0.3,
        "comment": "CPV2:C001:SECRET",
        "source_key": "must-not-leak",
    })
    state["independent_copy"]["positions"]["closed-private-position"] = {
        "account_key": "dbg_gb_mt5_live2:5200101",
        "product": "XAUUSD",
        "source_position_id": 8,
        "source_lots": 0.1,
        "status": "closed",
        "children": [],
        "comment": "CPV2:C001:CLOSED",
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")

    payload = CopyPoolFileSnapshotRepository(output).dashboard(
        timeline_limit=30,
        event_limit=10,
        order_limit=10,
    )

    assert len(payload["currentCopies"]) == 1
    row = payload["currentCopies"][0]
    assert row["accountLogin"] == "5200101"
    assert row["accountPlatform"] == "MT5"
    assert row["accountServer"] == "DBG GB MT5 Live2"
    assert row["product"] == "XAUUSD"
    assert row["sourceDirection"] == "BUY"
    assert row["sourcePositionId"] == 7
    assert row["sourceLots"] == 0.2
    assert row["sourceOpenPrice"] == 4000.1
    assert row["sourceOpenedAt"] == "2026-07-28T12:42:42+00:00"
    assert row["sourceHoldingSeconds"] is not None
    assert row["demoTicket"] == 90001
    assert row["demoDirection"] == "BUY"
    assert row["demoLots"] == 0.01
    assert row["demoOpenPrice"] == 4000.36
    assert row["demoOpenedAt"] == "2026-07-28T12:42:43+00:00"
    assert row["demoHoldingSeconds"] is not None
    assert row["sourceRealizedPnlUsd"] == 1.25
    assert row["sourceFloatingPnlUsd"] == -0.75
    assert row["sourceTotalPnlUsd"] == 0.5
    assert row["sourcePnlBasis"] == "source_position_realized_plus_floating"
    assert row["demoRealizedPnlUsd"] == 0.1
    assert row["demoFloatingPnlUsd"] == 0.2
    assert row["demoTotalPnlUsd"] == pytest.approx(0.3)
    assert row["demoPnlBasis"] == "demo_source_position_comment_realized_plus_floating"
    assert row["copyStatus"] == "active"
    assert row["detailPath"] == "/copy-pool/accounts/C001"
    assert "clientAlias" not in row
    serialized = json.dumps(payload["currentCopies"])
    assert "CPV2" not in serialized
    assert "must-not-leak" not in serialized


def test_copy_pool_current_copies_keep_legacy_snapshot_values_unknown(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)

    payload = CopyPoolFileSnapshotRepository(output).dashboard(
        timeline_limit=30,
        event_limit=10,
        order_limit=10,
    )

    row = payload["currentCopies"][0]
    assert row["sourceOpenPrice"] is None
    assert row["sourceRealizedPnlUsd"] is None
    assert row["sourceFloatingPnlUsd"] is None
    assert row["sourceTotalPnlUsd"] is None
    assert row["sourcePnlBasis"] == "unavailable"
    assert row["demoRealizedPnlUsd"] is None
    assert row["demoFloatingPnlUsd"] is None
    assert row["demoTotalPnlUsd"] is None
    assert row["demoPnlBasis"] == "unavailable"


def test_copy_pool_keeps_missing_hourly_evidence_unknown_and_uses_daily_value(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)
    pool_path = output / "pool_public.csv"
    rows = list(csv.DictReader(pool_path.open(encoding="utf-8", newline="")))
    rows[0]["current_comprehensive_net_20d_usd"] = ""
    rows[0]["hourly_hard_eligible"] = ""
    rows[0]["hourly_activity_eligible"] = ""
    write_csv(pool_path, rows)

    payload = CopyPoolFileSnapshotRepository(output).dashboard(
        timeline_limit=30,
        event_limit=10,
        order_limit=10,
    )

    row = payload["pool"][0]
    assert row["currentComprehensiveNet20dUsd"] is None
    assert row["comprehensiveNet20dUsd"] == 120.0
    assert row["hourlyHardEligible"] is None
    assert row["hourlyActivityEligible"] is None


def test_copy_pool_projects_unselected_built_source_as_idle_and_healthy(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)
    coverage_path = output / "source_coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["sources"].append({
        "physical_key": "DBG:crm_cn_mt4_live1:MT4",
        "connection": "DBG",
        "platform": "MT4",
        "logical_routes": ["dbg_cn_mt4_live1"],
        "candidate_accounts": 80,
        "eligible_accounts": 9,
        "selected_clients": 0,
        "state": "ok",
        "last_success_at": "2026-07-28T20:42:00+08:00",
    })
    coverage_path.write_text(json.dumps(coverage), encoding="utf-8")
    status_path = output / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["source_health"].append({
        "physical_key": "DBG:crm_cn_mt4_live1:MT4",
        "selected_clients": 0,
        "state": "starting",
    })
    status_path.write_text(json.dumps(status), encoding="utf-8")

    payload = CopyPoolFileSnapshotRepository(output).dashboard(
        timeline_limit=30,
        event_limit=10,
        order_limit=10,
    )

    source = next(
        row for row in payload["sourceCoverage"]["sources"]
        if row["physicalKey"] == "DBG:crm_cn_mt4_live1:MT4"
    )
    assert source["state"] == "idle"
    assert source["subscriptionState"] == "unsubscribed"
    assert source["lastSuccessAt"] == "2026-07-28T20:42:00+08:00"
    assert payload["sourceCoverage"]["healthy"] == 2


def test_private_effective_weight_cannot_exceed_base_or_dynamic_sleeve(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)
    state_path = output / "runtime_state_private.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["effective_weights"]["dbg_gb_mt5_live2:5200101"] = 0.05
    state["effective_product_weights"]["dbg_gb_mt5_live2:5200101|XAUUSD"] = 0.05
    state["independent_copy"]["clients"]["dbg_gb_mt5_live2:5200101"]["effective_weight"] = 0.03
    state_path.write_text(json.dumps(state), encoding="utf-8")

    payload = CopyPoolFileSnapshotRepository(output).dashboard(
        timeline_limit=30,
        event_limit=10,
        order_limit=10,
    )

    row = payload["pool"][0]
    assert row["effectiveWeight"] == 0.018
    assert row["weightAdjustment"] == pytest.approx(-0.4)
    assert row["weightState"] == "reduced"


def test_dynamic_monitor_weight_caps_private_source_weight_at_zero(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)
    status_path = output / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["dynamic_sleeves"][0]["tier"] = "monitor"
    status["dynamic_sleeves"][0]["effective_weight"] = 0.0
    status_path.write_text(json.dumps(status), encoding="utf-8")

    payload = CopyPoolFileSnapshotRepository(output).dashboard(
        timeline_limit=30,
        event_limit=10,
        order_limit=10,
    )

    row = payload["pool"][0]
    assert row["dynamicState"]["tier"] == "monitor"
    assert row["effectiveWeight"] == 0.0
    assert row["weightState"] == "removed"


def test_copy_pool_api_and_anonymous_account_redirect(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)
    settings = replace(make_test_settings(tmp_path), copy_pool_output_dir=output)
    app = create_account_app(settings)

    with TestClient(app) as client:
        response = client.get("/api/copy-pool/dashboard?timeline_limit=30&event_limit=10&order_limit=10")
        redirect = client.get("/copy-pool/accounts/C001", follow_redirects=False)

    assert response.status_code == 200
    assert response.json()["pool"][0]["accountLogin"] == "5200101"
    assert response.json()["pool"][0]["detailPath"] == "/copy-pool/accounts/C001"
    assert redirect.status_code == 307
    assert redirect.headers["location"].startswith("/account/5200101?")
    assert "server=DBG+GB+MT5+Live2" in redirect.headers["location"]


def test_copy_pool_reader_has_explicit_empty_state(tmp_path: Path) -> None:
    payload = CopyPoolFileSnapshotRepository(tmp_path / "missing").dashboard(
        timeline_limit=30,
        event_limit=10,
        order_limit=10,
    )
    assert payload == {
        "ok": True,
        "available": False,
        "stale": True,
        "message": "尚未发现实时跟单状态文件",
        "status": {},
        "pool": [],
        "timeline": [],
        "events": [],
        "orders": [],
        "clientRisks": [],
        "copyPositions": [],
        "ticketMappings": [],
        "currentCopies": [],
        "exposures": [],
        "dynamicSleeves": [],
        "scheduler": {},
    }
