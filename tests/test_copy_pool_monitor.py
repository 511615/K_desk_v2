from __future__ import annotations

import csv
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
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
            "account_login": 33304642,
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
            "external_position_conflict": False,
            "external_position_count": 2,
            "pending_order_conflict": False,
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
    (output / "demo_account_public.json").write_text(json.dumps({
        "updated_at_beijing": "2026-07-28T20:43:19+08:00",
        "account": {
            "login": 33304642,
            "server": "ACCMGlobal-Demo",
            "currency": "USD",
            "balance_usd": 9978.35,
            "equity_usd": 10003.62,
            "margin_usd": 120.0,
            "free_margin_usd": 9883.62,
            "margin_level_percent": 8336.35,
        },
        "positions": [{
            "ticket": 90001,
            "position_id": 90001,
            "product": "XAUUSD",
            "side": "BUY",
            "lots": 0.01,
            "open_price": 4000.0,
            "current_price": 4003.0,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "floating_pnl_usd": 3.2,
            "swap_usd": -0.1,
            "opened_at": "2026-07-28T20:40:00+08:00",
            "strategy_owned": True,
        }],
        "deals": [{
            "deal_ticket": 80001,
            "order_ticket": 81001,
            "position_id": 89001,
            "time": "2026-07-28T19:40:00+08:00",
            "product": "XAUUSD",
            "entry": "OUT",
            "side": "SELL",
            "lots": 0.01,
            "price": 4002.0,
            "profit_usd": 2.5,
            "commission_usd": -0.4,
            "swap_usd": 0.0,
            "fee_usd": 0.0,
            "net_pnl_usd": 2.1,
            "strategy_owned": True,
        }],
    }), encoding="utf-8")
    write_csv(output / "pool_public.csv", [{
        "client_alias": "C001",
        "product": "XAUUSD",
        "demo_symbol": "XAUUSD",
        "activity_eligible": True,
        "pool_status": "active_candidate",
        "pool_tier": "active",
        "factor_ready": True,
        "factor_base_score": 0.82,
        "factor_model": "cost_profit_recent_coverage_carry_v2",
        "factor_rank_cost_profit": 0.81,
        "factor_rank_recent_strength": 0.62,
        "factor_rank_cost_coverage": 0.73,
        "factor_rank_carry_quality": 0.66,
        "carry_risk_score": 34.0,
        "carry_quality_score": 0.66,
        "carry_hard_failed": False,
        "carry_gate_reasons": "",
        "max_floating_loss_ratio_30d": 0.04,
        "max_underwater_seconds_30d": 7200,
        "max_losing_positions_30d": 2,
        "factor_copy_net_5d_usd": 20.0,
        "factor_copy_net_20d_usd": 100.0,
        "factor_estimated_copy_cost_5d_usd": 3.0,
        "factor_estimated_copy_cost_20d_usd": 9.0,
        "factor_cost_adjusted_net_5d_usd": 17.0,
        "factor_cost_adjusted_net_20d_usd": 91.0,
        "factor_cost_profit_per_trade": 9.1,
        "factor_recent_profit_per_trade": 8.5,
        "factor_cost_coverage": 11.1111,
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
        "reason": "open:active",
        "reason_code": "risk_allowed",
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
        "account_login": 33304642,
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
    assert payload["status"]["externalPositionConflict"] is False
    assert payload["status"]["externalPositionCount"] == 2
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
    assert row["factorModel"] == "cost_profit_recent_coverage_carry_v2"
    assert row["factorScores"]["costProfit"] == 0.81
    assert row["factorScores"]["recentStrength"] == 0.62
    assert row["factorScores"]["costCoverage"] == 0.73
    assert row["factorScores"]["carryQuality"] == 0.66
    assert row["carryRisk"] == {
        "riskScore": 34.0,
        "qualityScore": 0.66,
        "hardFailed": False,
        "gateReasons": [],
        "maxFloatingLossRatio30d": 0.04,
        "maxUnderwaterSeconds30d": 7200.0,
        "maxLosingPositions30d": 2,
    }
    assert row["copyCostEvidence"] == {
        "copyNet5dUsd": 20.0,
        "copyNet20dUsd": 100.0,
        "estimatedCost5dUsd": 3.0,
        "estimatedCost20dUsd": 9.0,
        "afterCost5dUsd": 17.0,
        "afterCost20dUsd": 91.0,
        "coverage": 11.1111,
        "costProfitPerTrade": 9.1,
        "recentProfitPerTrade": 8.5,
    }
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
    assert payload["events"][0]["decision"] == "active"
    assert payload["events"][0]["reasonCode"] == "risk_allowed"
    assert payload["events"][0]["dbLatencySeconds"] == pytest.approx(0.4)
    assert payload["events"][0]["signalAgeSeconds"] == pytest.approx(0.4)
    assert payload["events"][0]["queryLatencySeconds"] is None
    assert payload["events"][0]["spreadCostPerLot"] is None
    assert payload["events"][0]["spreadLimitPerLot"] is None
    assert payload["events"][0]["bid"] is None
    assert payload["events"][0]["ask"] is None
    assert "reason" not in payload["events"][0]
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
    assert payload["status"]["accountLogin"] == "33304642"
    assert payload["demoAccount"]["account"]["login"] == "33304642"
    assert payload["demoAccount"]["positions"][0]["ticket"] == 90001
    assert payload["demoAccount"]["positions"][0]["strategyOwned"] is True
    assert payload["demoAccount"]["deals"][0]["netPnlUsd"] == pytest.approx(2.1)
    assert payload["timeline"][0]["accountLogin"] == "33304642"
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


def test_event_reason_code_is_bounded_and_legacy_rows_remain_honest(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)
    event_path = output / "events_public.csv"
    write_csv(event_path, [{
        "event_id": "E2",
        "time_beijing": "2026-08-07T13:09:35+08:00",
        "client_alias": "C001",
        "source_entry": 0,
        "product": "XAUUSD",
        "phase": "live",
        "reason": "MT4:open:monitor",
        "reason_code": "private database password must not leak",
    }])

    payload = CopyPoolFileSnapshotRepository(output).dashboard(
        timeline_limit=1, event_limit=1, order_limit=1
    )

    assert payload["events"][0]["decision"] == "monitor"
    assert payload["events"][0]["reasonCode"] == ""
    assert "private database password" not in json.dumps(payload)


def test_event_projects_separate_signal_age_and_query_latency_when_available(
    tmp_path: Path,
) -> None:
    output = make_snapshot(tmp_path)
    event_path = output / "events_public.csv"
    write_csv(event_path, [{
        "event_id": "E3",
        "time_beijing": "2026-08-07T13:09:35+08:00",
        "client_alias": "C001",
        "source_entry": 0,
        "product": "XAUUSD",
        "db_latency_seconds": 0.4,
        "signal_age_seconds": 2.8,
        "query_latency_seconds": 0.08,
        "phase": "live",
        "reason": "MT4:open:active",
        "reason_code": "risk_allowed",
    }])

    payload = CopyPoolFileSnapshotRepository(output).dashboard(
        timeline_limit=1, event_limit=1, order_limit=1
    )

    event = payload["events"][0]
    assert event["dbLatencySeconds"] == pytest.approx(0.4)
    assert event["signalAgeSeconds"] == pytest.approx(2.8)
    assert event["queryLatencySeconds"] == pytest.approx(0.08)


def test_event_projects_bounded_gate_evidence_without_private_text(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)
    write_csv(output / "events_public.csv", [{
        "event_id": "E4",
        "time_beijing": "2026-08-07T13:09:35+08:00",
        "client_alias": "C001",
        "source_entry": 0,
        "product": "XAUUSD",
        "phase": "live",
        "reason_code": "execution_gate_blocked:spread",
        "spread_cost_per_lot": 80.0,
        "spread_limit_per_lot": 45.0,
        "bid": 4000.0,
        "ask": 4000.8,
        "reason": "private database password must not leak",
    }])

    event = CopyPoolFileSnapshotRepository(output).dashboard(
        timeline_limit=1, event_limit=1, order_limit=1
    )["events"][0]

    assert event["spreadCostPerLot"] == pytest.approx(80.0)
    assert event["spreadLimitPerLot"] == pytest.approx(45.0)
    assert event["bid"] == pytest.approx(4000.0)
    assert event["ask"] == pytest.approx(4000.8)
    assert "private database password" not in json.dumps(event)


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


def test_demo_account_projection_filters_external_rows_from_legacy_snapshot(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)
    path = output / "demo_account_public.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    snapshot["positions"].append({
        **snapshot["positions"][0],
        "ticket": 99002,
        "position_id": 99002,
        "floating_pnl_usd": 999.0,
        "strategy_owned": False,
    })
    external_deal = {
        **snapshot["deals"][0],
        "deal_ticket": 88002,
        "position_id": 98002,
        "net_pnl_usd": 999.0,
        "strategy_owned": False,
    }
    snapshot["deals"] = [external_deal, *snapshot["deals"]]
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    demo = CopyPoolFileSnapshotRepository(output).dashboard(
        timeline_limit=30, event_limit=10, order_limit=1
    )["demoAccount"]

    assert [row["ticket"] for row in demo["positions"]] == [90001]
    assert [row["dealTicket"] for row in demo["deals"]] == [80001]
    assert demo["account"]["balanceUsd"] == pytest.approx(9978.35)
    assert demo["account"]["equityUsd"] == pytest.approx(10003.62)


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


def test_zero_weight_dynamic_active_sleeve_is_not_projected_as_active(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)
    status_path = output / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["dynamic_sleeves"][0]["tier"] = "active"
    status["dynamic_sleeves"][0]["effective_weight"] = 0.0
    status_path.write_text(json.dumps(status), encoding="utf-8")

    payload = CopyPoolFileSnapshotRepository(output).dashboard(
        timeline_limit=30,
        event_limit=10,
        order_limit=10,
    )

    row = payload["pool"][0]
    assert row["poolTier"] == "execution_suspended"
    assert row["activityEligible"] is False
    assert row["effectiveWeight"] == 0.0


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


def test_copy_pool_manual_controls_are_local_only_and_audited(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)
    settings = replace(make_test_settings(tmp_path), copy_pool_output_dir=output)
    app = create_account_app(settings)

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.put(
            "/api/copy-pool/controls",
            json={
                "autoTradingEnabled": True,
                "equityFloorEnabled": False,
                "dailyLossEnabled": False,
                "cycleLossEnabled": True,
                "resumeRequested": True,
            },
        )
        dashboard = client.get(
            "/api/copy-pool/dashboard?timeline_limit=30&event_limit=10&order_limit=10"
        )

    assert response.status_code == 200
    assert response.json()["controls"]["equityFloorEnabled"] is False
    assert response.json()["controls"]["resumeRequested"] is True
    assert dashboard.json()["controls"]["dailyLossEnabled"] is False
    audit = (output / "manual_controls_audit.jsonl").read_text(encoding="utf-8")
    assert '"source": "8777-local-ui"' in audit

    with TestClient(app, client=("10.1.2.3", 50000)) as remote_client:
        forbidden = remote_client.put(
            "/api/copy-pool/controls",
            json={
                "autoTradingEnabled": False,
                "equityFloorEnabled": False,
                "dailyLossEnabled": False,
                "cycleLossEnabled": False,
                "resumeRequested": False,
            },
        )

    assert forbidden.status_code == 403


def test_runtime_recovery_request_is_atomic_and_concurrent_calls_reuse_revision(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)
    repository = CopyPoolFileSnapshotRepository(output)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _index: repository.request_recovery(wait_seconds=0), range(4)))

    assert {item["revision"] for item in results} == {results[0]["revision"]}
    assert {item["state"] for item in results} == {"queued"}
    request = json.loads((output / "runtime_recovery_request.json").read_text(encoding="utf-8"))
    status = json.loads((output / "runtime_recovery_status.json").read_text(encoding="utf-8"))
    assert request == {
        "action": "reconnect_and_sync",
        "revision": results[0]["revision"],
        "requested_at": results[0]["requestedAt"],
        "source": "8777-local-ui",
    }
    assert status["revision"] == results[0]["revision"]
    assert status["state"] == "queued"
    assert "path" not in json.dumps(results)
    assert "account" not in json.dumps(results)


def test_runtime_recovery_returns_sanitized_matching_completion(tmp_path: Path, monkeypatch) -> None:
    output = make_snapshot(tmp_path)
    repository = CopyPoolFileSnapshotRepository(output)

    def complete(_seconds: float) -> None:
        request = json.loads(repository.recovery_request_path.read_text(encoding="utf-8"))
        repository._atomic_write_json(repository.recovery_status_path, {
            "revision": request["revision"],
            "state": "synchronized",
            "completed_at": "2026-08-10T01:02:03+00:00",
            "successful_sources": 8,
            "cursor_sources": 8,
            "position_count": 3,
            "heartbeat_at": "2026-08-10T01:02:02+00:00",
            "raw_error": "password=secret",
            "account_login": "33304642",
        })

    monkeypatch.setattr("kdesk.infrastructure.copy_pool_monitor.time.sleep", complete)
    result = repository.request_recovery(wait_seconds=0.1)

    assert result == {
        "revision": result["revision"],
        "state": "synchronized",
        "requestedAt": result["requestedAt"],
        "completedAt": "2026-08-10T01:02:03+00:00",
        "successfulSources": 8,
        "cursorSources": 8,
        "positionCount": 3,
        "heartbeatAt": "2026-08-10T01:02:02+00:00",
        "producerUnavailable": True,
    }
    serialized = json.dumps(result)
    assert "password" not in serialized
    assert "33304642" not in serialized


def test_copy_pool_recovery_api_is_loopback_same_origin_and_strict(tmp_path: Path, monkeypatch) -> None:
    output = make_snapshot(tmp_path)
    settings = replace(make_test_settings(tmp_path), copy_pool_output_dir=output)
    monkeypatch.setattr(
        CopyPoolFileSnapshotRepository,
        "request_recovery",
        lambda self, *, wait_seconds=10.0: {
            "revision": "safe-revision",
            "state": "queued",
            "requestedAt": "2026-08-10T01:02:03+00:00",
            "completedAt": None,
            "successfulSources": 0,
            "cursorSources": 0,
            "positionCount": 0,
            "heartbeatAt": None,
            "producerUnavailable": True,
        },
    )
    app = create_account_app(settings)

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        accepted = client.post(
            "/api/copy-pool/runtime/recovery",
            headers={"Origin": "http://testserver", "Host": "testserver"},
            json={"action": "reconnect_and_sync"},
        )
        extra = client.post(
            "/api/copy-pool/runtime/recovery",
            headers={"Origin": "http://testserver", "Host": "testserver"},
            json={"action": "reconnect_and_sync", "command": "restart"},
        )
        cross_origin = client.post(
            "/api/copy-pool/runtime/recovery",
            headers={"Origin": "http://evil.invalid", "Host": "testserver"},
            json={"action": "reconnect_and_sync"},
        )
        ipv6_loopback = client.post(
            "/api/copy-pool/runtime/recovery",
            headers={"Origin": "http://[::1]:8777", "Host": "[::1]:8777"},
            json={"action": "reconnect_and_sync"},
        )

    assert accepted.status_code == 202
    assert accepted.json()["recovery"]["producerUnavailable"] is True
    assert extra.status_code == 422
    assert cross_origin.status_code == 403
    assert ipv6_loopback.status_code == 202

    with TestClient(app, client=("10.1.2.3", 50000)) as remote_client:
        remote = remote_client.post(
            "/api/copy-pool/runtime/recovery",
            headers={"Origin": "http://testserver", "Host": "testserver"},
            json={"action": "reconnect_and_sync"},
        )
    assert remote.status_code == 403


@pytest.mark.parametrize(
    ("runtime_snapshot_stale", "data_fresh"),
    [(True, True), (False, False)],
)
def test_dashboard_marks_declared_runtime_snapshot_stale_and_projects_recovery(
    tmp_path: Path,
    runtime_snapshot_stale: bool,
    data_fresh: bool,
) -> None:
    output = make_snapshot(tmp_path)
    repository = CopyPoolFileSnapshotRepository(output)
    status = json.loads(repository.status_path.read_text(encoding="utf-8"))
    status["updated_at_beijing"] = datetime.now().astimezone().isoformat()
    status["runtime_snapshot_stale"] = runtime_snapshot_stale
    status["data_fresh"] = data_fresh
    repository.status_path.write_text(json.dumps(status), encoding="utf-8")
    repository.recovery_request_path.write_text(json.dumps({
        "action": "reconnect_and_sync",
        "revision": "recovery-1",
        "requested_at": "2026-08-10T01:01:00+00:00",
        "source": "8777-local-ui",
    }), encoding="utf-8")
    repository.recovery_status_path.write_text(json.dumps({
        "revision": "recovery-1",
        "state": "reconnecting",
        "heartbeat_at": "2026-08-10T01:02:00+00:00",
    }), encoding="utf-8")

    payload = repository.dashboard(timeline_limit=30, event_limit=10, order_limit=10)

    assert payload["stale"] is True
    assert payload["sourceAgeSeconds"] < 5.0
    assert payload["recovery"]["state"] == "running"
    assert payload["recovery"]["revision"] == "recovery-1"


def test_dashboard_recovery_maps_legacy_completion_to_contract_state(tmp_path: Path) -> None:
    output = make_snapshot(tmp_path)
    repository = CopyPoolFileSnapshotRepository(output)
    repository.recovery_request_path.write_text(json.dumps({
        "action": "reconnect_and_sync",
        "revision": "recovery-2",
        "requested_at": "2026-08-10T01:01:00+00:00",
        "source": "8777-local-ui",
    }), encoding="utf-8")
    repository.recovery_status_path.write_text(json.dumps({
        "revision": "recovery-2",
        "state": "reconciled",
        "completed_at": "2026-08-10T01:02:00+00:00",
    }), encoding="utf-8")

    recovery = repository.dashboard(
        timeline_limit=30, event_limit=10, order_limit=10
    )["recovery"]

    assert recovery["state"] == "synchronized"


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
            "demoAccount": {"account": {}, "positions": [], "deals": []},
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
        "controls": {
            "autoTradingEnabled": True,
            "equityFloorEnabled": True,
            "dailyLossEnabled": True,
            "cycleLossEnabled": True,
            "resumeRequested": False,
            "revision": "",
            "updatedAt": None,
            "source": "default",
        },
        "recovery": None,
    }
