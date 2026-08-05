from __future__ import annotations

import csv
import json
import math
import os
import re
from collections import deque
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from uuid import uuid4

ALIAS_RE = re.compile(r"^C\d{3}$")
REASON_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
POOL_TIERS = {
    "reserve",
    "monitor",
    "entry_shadow",
    "active",
    "recovery_shadow",
    "execution_suspended",
    "hard_rejected",
}


def _float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _nullable_float(value: object) -> float | None:
    """Keep absent snapshot evidence unknown instead of inventing a numeric value."""
    if value is None or not str(value).strip():
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _nullable_int(value: object) -> int | None:
    if value is None or not str(value).strip():
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _nullable_bool(value: object) -> bool | None:
    if value is None or not str(value).strip():
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _reason_codes(value: object) -> list[str]:
    """Project bounded factor/gate identifiers without exposing arbitrary state text."""
    if isinstance(value, list):
        candidates = value
    else:
        candidates = re.split(r"[|,;]", str(value or ""))
    return [
        code
        for code in (str(item).strip() for item in candidates)
        if REASON_CODE_RE.fullmatch(code)
    ][:20]


def _timestamp(value: object) -> str:
    parsed = _iso_datetime(value)
    return parsed.astimezone(UTC).isoformat() if parsed else ""


def _nullable_timestamp(value: object) -> str | None:
    timestamp = _timestamp(value)
    return timestamp or None


def _iso_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle) if isinstance(row, dict)]
    except (OSError, UnicodeError, csv.Error):
        return []


def _read_csv_tail(path: Path, limit: int) -> list[dict[str, str]]:
    if not path.is_file() or limit <= 0:
        return []
    rows: deque[dict[str, str]] = deque(maxlen=limit)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if isinstance(row, dict):
                    rows.append(dict(row))
    except (OSError, UnicodeError, csv.Error):
        return []
    return list(rows)


def _latest_effective_weights(rows: Iterable[dict[str, str]]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for row in rows:
        alias = str(row.get("client_alias", ""))
        if ALIAS_RE.fullmatch(alias):
            product = str(row.get("product") or "").upper()
            weights[f"{alias}|{product}"] = _float(row.get("effective_weight"))
    return weights


class CopyPoolFileSnapshotRepository:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir.resolve()
        self.status_path = self.output_dir / "status.json"
        self.demo_account_path = self.output_dir / "demo_account_public.json"
        self.pool_path = self.output_dir / "pool_public.csv"
        self.events_path = self.output_dir / "events_public.csv"
        self.orders_path = self.output_dir / "orders_public.csv"
        self.timeline_path = self.output_dir / "status_timeline_public.csv"
        self.routes_path = self.output_dir / "client_routes_private.json"
        self.private_state_path = self.output_dir / "runtime_state_private.json"
        self.coverage_path = self.output_dir / "source_coverage.json"
        self.controls_path = self.output_dir / "manual_controls.json"
        self.controls_audit_path = self.output_dir / "manual_controls_audit.jsonl"

    @staticmethod
    def _control_defaults() -> dict[str, bool]:
        return {
            "auto_trading_enabled": True,
            "equity_floor_enabled": True,
            "daily_loss_enabled": True,
            "cycle_loss_enabled": True,
            "resume_requested": False,
        }

    def controls(self) -> dict[str, Any]:
        raw = _read_json(self.controls_path)
        values = {
            key: raw.get(key) if isinstance(raw.get(key), bool) else default
            for key, default in self._control_defaults().items()
        }
        return {
            "autoTradingEnabled": values["auto_trading_enabled"],
            "equityFloorEnabled": values["equity_floor_enabled"],
            "dailyLossEnabled": values["daily_loss_enabled"],
            "cycleLossEnabled": values["cycle_loss_enabled"],
            "resumeRequested": values["resume_requested"],
            "revision": str(raw.get("revision") or ""),
            "updatedAt": raw.get("updated_at"),
            "source": str(raw.get("source") or "default"),
        }

    def update_controls(self, values: dict[str, bool]) -> dict[str, Any]:
        payload = {
            "auto_trading_enabled": values["auto_trading_enabled"],
            "equity_floor_enabled": values["equity_floor_enabled"],
            "daily_loss_enabled": values["daily_loss_enabled"],
            "cycle_loss_enabled": values["cycle_loss_enabled"],
            "resume_requested": values["resume_requested"],
            "revision": uuid4().hex,
            "updated_at": datetime.now(UTC).isoformat(),
            "source": "8777-local-ui",
        }
        self.output_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.controls_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.controls_path)
        with self.controls_audit_path.open("a", encoding="utf-8") as audit:
            audit.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return self.controls()

    def _routes(self) -> dict[str, dict[str, str]]:
        payload = _read_json(self.routes_path)
        routes: dict[str, dict[str, str]] = {}
        for item in payload.get("clients", []):
            if not isinstance(item, dict):
                continue
            alias = str(item.get("alias", "")).strip().upper()
            login = str(item.get("login", "")).strip()
            if not ALIAS_RE.fullmatch(alias) or not login or len(login) > 64:
                continue
            routes[alias] = {
                "login": login,
                "platform": str(item.get("platform") or "MT5"),
                "server": str(item.get("server") or "DBG GB MT5 Live2"),
                "account_key": str(item.get("account_key") or login),
                "route_key": str(item.get("route_key") or ""),
                "physical_key": str(item.get("physical_key") or ""),
            }
        return routes

    def account_target(self, alias: str) -> str | None:
        normalized = str(alias or "").strip().upper()
        if not ALIAS_RE.fullmatch(normalized):
            return None
        route = self._routes().get(normalized)
        if not route:
            return None
        query = urlencode({"platform": route["platform"], "server": route["server"]})
        return f"/account/{quote(route['login'], safe='')}?{query}"

    def dashboard(self, *, timeline_limit: int, event_limit: int, order_limit: int) -> dict[str, Any]:
        status = _read_json(self.status_path)
        if not status:
            return {
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
                "controls": self.controls(),
            }

        all_events = _read_csv(self.events_path)
        latest_weights = _latest_effective_weights(all_events)
        public_pool = _read_csv(self.pool_path)
        routes = self._routes()
        dynamic_sleeves, dynamic_by_public_sleeve = self._dynamic_sleeves(
            status.get("dynamic_sleeves"), routes, public_pool
        )
        coverage = _read_json(self.coverage_path)
        private_state = _read_json(self.private_state_path)
        intraday_by_login = private_state.get("intraday_net_usd", {})
        if not isinstance(intraday_by_login, dict):
            intraday_by_login = {}
        floating_by_identity = private_state.get("floating_pnl_usd", {})
        if not isinstance(floating_by_identity, dict):
            floating_by_identity = {}
        dynamic_by_identity = private_state.get("dynamic_evaluation_usd", {})
        if not isinstance(dynamic_by_identity, dict):
            dynamic_by_identity = {}
        open_risk_by_identity = private_state.get("open_risk_by_account", {})
        if not isinstance(open_risk_by_identity, dict):
            open_risk_by_identity = {}
        effective_by_identity = private_state.get("effective_weights", {})
        if not isinstance(effective_by_identity, dict):
            effective_by_identity = {}
        effective_by_sleeve = private_state.get("effective_product_weights", {})
        if not isinstance(effective_by_sleeve, dict):
            effective_by_sleeve = {}
        independent = private_state.get("independent_copy", {})
        if not isinstance(independent, dict):
            independent = {}
        independent_clients = independent.get("clients", {})
        if not isinstance(independent_clients, dict):
            independent_clients = {}
        independent_positions = independent.get("positions", {})
        if not isinstance(independent_positions, dict):
            independent_positions = {}
        positions = private_state.get("positions", [])
        if not isinstance(positions, list):
            positions = []

        alias_by_identity = {
            identity: alias
            for alias, item in routes.items()
            for identity in {item["login"], item["account_key"]}
        }
        position_by_sleeve: dict[tuple[str, str], float] = {}
        for item in positions:
            if not isinstance(item, dict):
                continue
            identity = str(item.get("account_key") or item.get("login") or "")
            alias = alias_by_identity.get(identity)
            if alias:
                product = str(item.get("product") or "").upper()
                sleeve = (alias, product)
                position_by_sleeve[sleeve] = position_by_sleeve.get(sleeve, 0.0) + _float(item.get("lots"))

        demo_equity = _float(status.get("equity_usd"))
        pool: list[dict[str, Any]] = []
        for row in public_pool:
            alias = str(row.get("client_alias", "")).strip().upper()
            if not ALIAS_RE.fullmatch(alias):
                continue
            base_weight = _float(row.get("live_base_weight"))
            product = str(row.get("product") or "").upper()
            source_equity = max(_float(row.get("equity_pre_usd")), 1.0)
            source_position = position_by_sleeve.get((alias, product), 0.0)
            route = routes.get(alias)
            dynamic_state = dynamic_by_public_sleeve.get(f"{alias}|{product}", {})
            private_weight = None
            client_weight_multiplier = 1.0
            if route:
                identity = route["account_key"]
                private_weight = effective_by_sleeve.get(
                    f"{identity}|{product}"
                )
                client_risk = independent_clients.get(identity, {})
                if isinstance(client_risk, dict):
                    client_base = _float(client_risk.get("base_weight"))
                    if client_base > 0:
                        client_weight_multiplier = max(
                            0.0,
                            min(1.0, _float(client_risk.get("effective_weight")) / client_base),
                        )
            source_weight = _float(
                private_weight,
                latest_weights.get(f"{alias}|{product}", base_weight),
            )
            source_weight = min(base_weight, max(0.0, source_weight))
            if dynamic_state:
                source_weight = min(
                    source_weight,
                    max(0.0, _float(dynamic_state.get("effectiveWeight"))),
                )
            effective_weight = source_weight * client_weight_multiplier
            intraday = _float(
                intraday_by_login.get(route["account_key"], intraday_by_login.get(route["login"]))
            ) if route else 0.0
            runtime_risk = open_risk_by_identity.get(route["account_key"], {}) if route else {}
            if not isinstance(runtime_risk, dict):
                runtime_risk = {}
            floating = _float(
                floating_by_identity.get(route["account_key"], floating_by_identity.get(route["login"])),
                _float(runtime_risk.get("floating_pnl_usd"), _float(row.get("floating_pnl_usd"))),
            ) if route else _float(row.get("floating_pnl_usd"))
            dynamic_evaluation = _float(
                dynamic_by_identity.get(route["account_key"], dynamic_by_identity.get(route["login"])),
                intraday + min(floating, 0.0),
            ) if route else intraday + min(floating, 0.0)
            adjustment = 0.0 if base_weight <= 0 else effective_weight / base_weight - 1.0
            pool.append({
                "clientAlias": alias,
                "clientProductKey": f"{alias}|{product}",
                "product": product,
                "demoSymbol": str(row.get("demo_symbol") or product),
                "accountLogin": route["login"] if route else "",
                "accountPlatform": route["platform"] if route else "",
                "accountServer": route["server"] if route else "",
                "routeKey": route["route_key"] if route else str(row.get("route_key") or ""),
                "physicalSource": route["physical_key"] if route else str(row.get("physical_key") or ""),
                "isABook": _bool(row.get("is_abook")),
                "dynamicScore": _float(row.get("dynamic_score")),
                "adjustedScore": _float(row.get("adjusted_score")),
                "medianHoldSeconds": _float(row.get("median_hold_seconds")),
                "holdP25Seconds": _float(row.get("hold_p25_seconds")),
                "holdP90Seconds": _float(row.get("hold_p90_seconds")),
                "shortTradeRatio": _float(row.get("short_trade_ratio")),
                "activityEligible": _bool(row.get("activity_eligible")),
                "poolStatus": str(row.get("pool_status") or "monitor_only"),
                "poolTier": self._pool_tier(row.get("pool_tier"), row.get("pool_status")),
                "factorReady": _bool(row.get("factor_ready")),
                "factorBaseScore": _float(row.get("factor_base_score")),
                "factorModel": str(row.get("factor_model") or "legacy"),
                "historicalDelayFactorEnabled": _bool(
                    row.get("historical_delay_enabled")
                ),
                "delayFactorStatus": str(
                    row.get("delay_factor_status") or "legacy_unknown"
                ),
                "hourlyScore": _nullable_float(row.get("hourly_score")),
                "recentNet1hUsd": _float(row.get("recent_net_1h_usd")),
                "recentNet4hUsd": _float(row.get("recent_net_4h_usd")),
                # These fields are populated by the bounded hourly refresh.  On restart an
                # accepted daily cache can legitimately lack them, which is unknown rather
                # than a zero P/L or a failed hard gate.
                "currentComprehensiveNet20dUsd": _nullable_float(
                    row.get("current_comprehensive_net_20d_usd")
                ),
                "hourlyHardEligible": _nullable_bool(row.get("hourly_hard_eligible")),
                "hourlyActivityEligible": _nullable_bool(
                    row.get("hourly_activity_eligible")
                ),
                "factorGateReasons": _reason_codes(row.get("factor_gate_reasons")),
                "factorScores": {
                    "costProfit": _float(row.get("factor_rank_cost_profit")),
                    "recentStrength": _float(row.get("factor_rank_recent_strength")),
                    "costCoverage": _float(row.get("factor_rank_cost_coverage")),
                    "carryQuality": _float(row.get("factor_rank_carry_quality")),
                    "riskAdjustedReturn5d": _float(row.get("factor_risk_adjusted_return_5d")),
                    "riskAdjustedReturn20d": _float(row.get("factor_risk_adjusted_return_20d")),
                    "spreadStressReturn": _float(row.get("factor_spread_stress_return")),
                    "pfQuality": _float(row.get("factor_pf_quality")),
                    "delay": _float(row.get("factor_delay_score")),
                    "returnToDrawdown": _float(row.get("factor_return_to_drawdown")),
                    "holdingQuality": _float(row.get("factor_holding_quality")),
                },
                "copyCostEvidence": {
                    "copyNet5dUsd": _float(row.get("factor_copy_net_5d_usd")),
                    "copyNet20dUsd": _float(row.get("factor_copy_net_20d_usd")),
                    "estimatedCost5dUsd": _float(
                        row.get("factor_estimated_copy_cost_5d_usd")
                    ),
                    "estimatedCost20dUsd": _float(
                        row.get("factor_estimated_copy_cost_20d_usd")
                    ),
                    "afterCost5dUsd": _float(
                        row.get("factor_cost_adjusted_net_5d_usd")
                    ),
                    "afterCost20dUsd": _float(
                        row.get("factor_cost_adjusted_net_20d_usd")
                    ),
                    "coverage": _float(row.get("factor_cost_coverage")),
                    "costProfitPerTrade": _float(
                        row.get("factor_cost_profit_per_trade")
                    ),
                    "recentProfitPerTrade": _float(
                        row.get("factor_recent_profit_per_trade")
                    ),
                },
                "delay": {
                    "score": _float(row.get("delay_score")),
                    "entryP95Ms": _int(row.get("entry_p95_ms")),
                    "exitP95Ms": _int(row.get("exit_p95_ms")),
                    "entryBreakEvenMs": _float(row.get("entry_break_even_ms")),
                    "exitBreakEvenMs": _float(row.get("exit_break_even_ms")),
                    "combinedBreakEvenMs": _float(row.get("combined_break_even_ms")),
                    "conservativeBreakEvenMs": _float(row.get("conservative_break_even_ms")),
                    "profitRetention": _float(row.get("delay_profit_retention")),
                    "executableRatio": _float(row.get("delay_executable_ratio")),
                },
                "drawdown": {
                    "mdd20d": _float(row.get("mdd_20d")),
                    "mdd60d": _float(row.get("mdd_60d")),
                    "current": _float(row.get("current_drawdown")),
                    "maxDailyLoss": _float(row.get("max_daily_loss")),
                    "equityCoverage20d": _bool(row.get("equity_coverage_20d")),
                    "equityCoverage60d": _bool(row.get("equity_coverage_60d")),
                    "intradayComplete": _bool(row.get("intraday_equity_complete")),
                },
                "holdingQuality": {
                    "pathComplete": _bool(row.get("holding_path_complete")),
                    "overnightRatio": _float(row.get("overnight_ratio")),
                    "weekendRatio": _float(row.get("weekend_ratio")),
                    "swapDrag": _float(row.get("swap_drag")),
                    "longLossRatio": _float(row.get("long_loss_ratio")),
                    "lossAdditionRatio": _float(row.get("loss_addition_ratio")),
                },
                "carryRisk": {
                    "riskScore": _float(row.get("carry_risk_score")),
                    "qualityScore": _float(row.get("carry_quality_score")),
                    "hardFailed": _bool(row.get("carry_hard_failed")),
                    "gateReasons": _reason_codes(row.get("carry_gate_reasons")),
                    "maxFloatingLossRatio30d": _float(
                        row.get("max_floating_loss_ratio_30d")
                    ),
                    "maxUnderwaterSeconds30d": _float(
                        row.get("max_underwater_seconds_30d")
                    ),
                    "maxLosingPositions30d": _int(
                        row.get("max_losing_positions_30d")
                    ),
                },
                "holdMultiplier": _float(row.get("hold_multiplier"), 1.0),
                "baseWeight": base_weight,
                "customerBaseWeight": _float(row.get("customer_base_weight")),
                "productBudgetWeight": _float(row.get("product_budget_weight")),
                "effectiveWeight": effective_weight,
                "weightAdjustment": adjustment,
                "sourceEquityUsd": source_equity,
                "virtualPositionLots": source_position,
                "targetContributionLots": source_position * demo_equity * effective_weight / source_equity,
                "comprehensiveNet20dUsd": _float(row.get("comprehensive_net_20d_usd")),
                "productFloatingPnlUsd": _float(row.get("product_floating_pnl_usd")),
                "intradayNetUsd": intraday,
                "intradayRealizedUsd": intraday,
                "floatingPnlUsd": floating,
                "dynamicEvaluationUsd": dynamic_evaluation,
                "openPositionCount": int(_float(runtime_risk.get("open_position_count"), _float(row.get("open_position_count")))),
                "openGrossLots": _float(runtime_risk.get("open_gross_lots"), _float(row.get("open_gross_lots"))),
                "xauGrossLots": _float(runtime_risk.get("xau_gross_lots"), _float(row.get("xau_gross_lots"))),
                "xauNetLots": _float(runtime_risk.get("xau_net_lots"), _float(row.get("xau_net_lots"), source_position)),
                "xauHedgeRatio": _float(runtime_risk.get("xau_hedge_ratio"), _float(row.get("xau_hedge_ratio"))),
                "oldestOpenSeconds": _float(runtime_risk.get("oldest_open_seconds"), _float(row.get("oldest_open_seconds"))),
                "marginToEquity": _float(runtime_risk.get("margin_to_equity"), _float(row.get("margin_to_equity"))),
                "floatingLossRatio": _float(runtime_risk.get("floating_loss_ratio"), _float(row.get("floating_loss_ratio"))),
                "buildFloatingPnlUsd": _float(row.get("floating_pnl_usd")),
                "qualityNet5dUsd": _float(row.get("quality_net_5d_usd")),
                "qualityNet20dUsd": _float(row.get("quality_net_20d_usd")),
                "openRiskMultiplier": _float(row.get("open_risk_multiplier"), 1.0),
                "dynamicState": dynamic_state,
                "weightState": "removed" if effective_weight <= 0 else "reduced" if adjustment < -0.001 else "full",
                "detailPath": f"/copy-pool/accounts/{alias}" if alias in routes else "",
            })

        timeline_rows = _read_csv_tail(self.timeline_path, timeline_limit)
        event_rows = all_events[-event_limit:]
        order_rows = _read_csv_tail(self.orders_path, order_limit)
        updated_at = _iso_datetime(status.get("updated_at_beijing"))
        age_seconds = max(0.0, (datetime.now(UTC) - updated_at.astimezone(UTC)).total_seconds()) if updated_at else None
        first_time = _iso_datetime(timeline_rows[0].get("time_beijing")) if timeline_rows else None
        last_source = _iso_datetime(event_rows[-1].get("time_beijing")) if event_rows else None

        client_risks = self._client_risks(independent_clients, routes)
        copy_positions, ticket_mappings, exposures = self._independent_positions(
            independent_positions, routes
        )
        current_copies = self._current_copies(independent_positions, routes)
        demo_account = self._demo_account(
            _read_json(self.demo_account_path), status, limit=order_limit
        )

        return {
            "ok": True,
            "available": True,
            "stale": age_seconds is None or age_seconds > 5.0,
            "sourceAgeSeconds": age_seconds,
            "updatedAt": str(status.get("updated_at_beijing") or ""),
            "uptimeSeconds": max(0.0, (updated_at - first_time).total_seconds()) if updated_at and first_time else 0.0,
            "lastSourceEventAt": last_source.isoformat() if last_source else "",
            "routeCoverage": {"linked": sum(bool(row["detailPath"]) for row in pool), "total": len(pool)},
            "sourceCoverage": self._source_coverage(status, coverage),
            "status": self._public_status(status),
            "demoAccount": demo_account,
            "pool": pool,
            "timeline": [self._timeline_row(row) for row in timeline_rows if row.get("time_beijing")],
            "events": [
                self._event_row(row, routes)
                for row in event_rows
                if row.get("time_beijing")
            ],
            "orders": [
                self._order_row(row, routes)
                for row in order_rows
                if row.get("time_beijing")
            ],
            "clientRisks": client_risks,
            "copyPositions": copy_positions,
            "ticketMappings": ticket_mappings,
            "currentCopies": current_copies,
            "exposures": exposures,
            "dynamicSleeves": dynamic_sleeves,
            "scheduler": self._scheduler(status.get("scheduler")),
            "controls": self.controls(),
        }

    @staticmethod
    def _demo_account(
        row: dict[str, Any], status: dict[str, Any], *, limit: int
    ) -> dict[str, Any]:
        account = row.get("account") if isinstance(row.get("account"), dict) else {}
        login = str(account.get("login") or "")
        server = str(account.get("server") or "")
        if (
            not login
            or login != str(status.get("account_login") or "")
            or server != str(status.get("server") or "")
        ):
            return {"updatedAt": "", "account": {}, "positions": [], "deals": []}

        positions = []
        for item in row.get("positions") or []:
            if not isinstance(item, dict):
                continue
            positions.append({
                "ticket": _int(item.get("ticket")),
                "positionId": _int(item.get("position_id")),
                "product": str(item.get("product") or ""),
                "side": str(item.get("side") or ""),
                "lots": _float(item.get("lots")),
                "openPrice": _float(item.get("open_price")),
                "currentPrice": _float(item.get("current_price")),
                "stopLoss": _float(item.get("stop_loss")),
                "takeProfit": _float(item.get("take_profit")),
                "floatingPnlUsd": _float(item.get("floating_pnl_usd")),
                "swapUsd": _float(item.get("swap_usd")),
                "openedAt": str(item.get("opened_at") or ""),
                "strategyOwned": _bool(item.get("strategy_owned")),
            })

        deals = []
        for item in (row.get("deals") or [])[:max(0, limit)]:
            if not isinstance(item, dict):
                continue
            deals.append({
                "dealTicket": _int(item.get("deal_ticket")),
                "orderTicket": _int(item.get("order_ticket")),
                "positionId": _int(item.get("position_id")),
                "time": str(item.get("time") or ""),
                "product": str(item.get("product") or ""),
                "entry": str(item.get("entry") or ""),
                "side": str(item.get("side") or ""),
                "lots": _float(item.get("lots")),
                "price": _float(item.get("price")),
                "profitUsd": _float(item.get("profit_usd")),
                "commissionUsd": _float(item.get("commission_usd")),
                "swapUsd": _float(item.get("swap_usd")),
                "feeUsd": _float(item.get("fee_usd")),
                "netPnlUsd": _float(item.get("net_pnl_usd")),
                "strategyOwned": _bool(item.get("strategy_owned")),
            })

        return {
            "updatedAt": str(row.get("updated_at_beijing") or ""),
            "account": {
                "login": login,
                "server": server,
                "currency": str(account.get("currency") or "USD"),
                "balanceUsd": _float(account.get("balance_usd")),
                "equityUsd": _float(account.get("equity_usd")),
                "marginUsd": _float(account.get("margin_usd")),
                "freeMarginUsd": _float(account.get("free_margin_usd")),
                "marginLevelPercent": _float(account.get("margin_level_percent")),
            },
            "positions": positions,
            "deals": deals,
        }

    @staticmethod
    def _pool_tier(value: object, legacy_status: object) -> str:
        tier = str(value or "").strip().lower()
        if tier in POOL_TIERS:
            return tier
        if str(legacy_status or "").strip().lower() in {"active", "active_candidate"}:
            return "monitor"
        return "monitor"

    @staticmethod
    def _dynamic_sleeves(
        raw_rows: object,
        routes: dict[str, dict[str, str]],
        pool_rows: Iterable[dict[str, str]],
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """Translate producer sleeve keys only when a public pool row proves the alias mapping."""
        private_to_public: dict[str, tuple[str, str]] = {}
        for row in pool_rows:
            alias = str(row.get("client_alias") or "").strip().upper()
            product = str(row.get("product") or "").strip().upper()
            route = routes.get(alias)
            if route and product:
                private_to_public[f"{route['account_key']}|{product}"] = (alias, product)

        projected: list[dict[str, Any]] = []
        by_public_sleeve: dict[str, dict[str, Any]] = {}
        if not isinstance(raw_rows, list):
            return projected, by_public_sleeve
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            public = private_to_public.get(str(raw.get("sleeve_key") or ""))
            if not public:
                continue
            alias, product = public
            route = routes[alias]
            row = {
                "clientAlias": alias,
                "accountLogin": route["login"],
                "accountPlatform": route["platform"],
                "accountServer": route["server"],
                "product": product,
                "tier": CopyPoolFileSnapshotRepository._pool_tier(raw.get("tier"), ""),
                "baseWeight": _float(raw.get("base_weight")),
                "effectiveWeight": _float(raw.get("effective_weight")),
                "shadowEndsAt": _timestamp(raw.get("shadow_ends_at")),
                "entryExpiredCount": _int(raw.get("entry_expired_count")),
                "exitExpiredCount": _int(raw.get("exit_expired_count")),
                "detailPath": f"/copy-pool/accounts/{alias}",
            }
            projected.append(row)
            by_public_sleeve[f"{alias}|{product}"] = row
        return (
            sorted(projected, key=lambda item: (item["clientAlias"], item["product"])),
            by_public_sleeve,
        )

    @staticmethod
    def _scheduler(raw: object) -> dict[str, str]:
        if not isinstance(raw, dict):
            return {}
        date_value = str(raw.get("last_daily_rebuild_date") or "")
        try:
            datetime.fromisoformat(date_value)
        except ValueError:
            date_value = ""
        return {
            "lastRiskAt": _timestamp(raw.get("last_risk_at")),
            "lastRankAt": _timestamp(raw.get("last_rank_at")),
            "lastDiscoveryAt": _timestamp(raw.get("last_discovery_at")),
            "lastDailyRebuildDate": date_value,
        }

    @staticmethod
    def _client_risks(
        rows: dict[str, Any], routes: dict[str, dict[str, str]]
    ) -> list[dict[str, Any]]:
        alias_by_identity = {
            item["account_key"]: alias for alias, item in routes.items()
        }
        output: list[dict[str, Any]] = []
        for identity, raw in rows.items():
            if not isinstance(raw, dict):
                continue
            alias = alias_by_identity.get(str(identity))
            if not alias:
                continue
            output.append({
                "clientAlias": alias,
                "accountLogin": routes[alias]["login"],
                "accountPlatform": routes[alias]["platform"],
                "accountServer": routes[alias]["server"],
                "baseWeight": _float(raw.get("base_weight")),
                "effectiveWeight": _float(raw.get("effective_weight")),
                "lossBudgetUsd": _float(raw.get("loss_budget_usd")),
                "realizedPnlUsd": _float(raw.get("realized_pnl_usd")),
                "floatingPnlUsd": _float(raw.get("floating_pnl_usd")),
                "totalPnlUsd": _float(raw.get("total_pnl_usd")),
                "lossUsedUsd": _float(raw.get("loss_used_usd")),
                "lossUsage": _float(raw.get("loss_usage")),
                "lossMultiplier": _float(raw.get("loss_multiplier"), 1.0),
                "status": str(raw.get("status") or "monitor"),
                "reductionReason": str(raw.get("reduction_reason") or ""),
                "pauseUntil": raw.get("pause_until"),
                "recoveryShadowUntil": raw.get("recovery_shadow_until"),
                "detailPath": f"/copy-pool/accounts/{alias}",
            })
        return sorted(output, key=lambda item: item["clientAlias"])

    @staticmethod
    def _independent_positions(
        rows: dict[str, Any], routes: dict[str, dict[str, str]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        alias_by_identity = {
            item["account_key"]: alias for alias, item in routes.items()
        }
        positions: list[dict[str, Any]] = []
        mappings: list[dict[str, Any]] = []
        exposure: dict[str, dict[str, float]] = {}
        for raw in rows.values():
            if not isinstance(raw, dict):
                continue
            alias = alias_by_identity.get(str(raw.get("account_key") or ""))
            if not alias:
                continue
            product = str(raw.get("product") or "")
            children = raw.get("children", [])
            if not isinstance(children, list):
                children = []
            row = {
                "clientAlias": alias,
                "accountLogin": routes[alias]["login"],
                "accountPlatform": routes[alias]["platform"],
                "accountServer": routes[alias]["server"],
                "product": product,
                "sourcePositionId": _int(raw.get("source_position_id")),
                "sourceLots": _float(raw.get("source_lots")),
                "copiedLots": _float(raw.get("copied_lots")),
                "copiedSignedLots": _float(raw.get("copied_signed_lots")),
                "copyEligible": _bool(raw.get("copy_eligible")),
                "status": str(raw.get("status") or "monitor"),
                "rejectReason": str(raw.get("reject_reason") or ""),
                "sourceOpenedAt": str(raw.get("source_opened_at") or ""),
                "firstSignalAt": str(raw.get("first_signal_at") or ""),
                "lastSignalAt": str(raw.get("last_signal_at") or ""),
                "lastAction": str(raw.get("last_action") or "monitor"),
                "demoTickets": [_int(child.get("ticket")) for child in children if isinstance(child, dict)],
                "detailPath": f"/copy-pool/accounts/{alias}",
            }
            positions.append(row)
            for child in children:
                if not isinstance(child, dict):
                    continue
                side = 1 if _int(child.get("side")) >= 0 else -1
                lots = _float(child.get("lots"))
                mappings.append({
                    "clientAlias": alias,
                    "accountLogin": routes[alias]["login"],
                    "accountPlatform": routes[alias]["platform"],
                    "accountServer": routes[alias]["server"],
                    "product": product,
                    "sourcePositionId": row["sourcePositionId"],
                    "demoTicket": _int(child.get("ticket")),
                    "side": side,
                    "lots": lots,
                    "openTime": str(child.get("open_time") or ""),
                    "openPrice": _float(child.get("open_price")),
                    "detailPath": row["detailPath"],
                })
                product_exposure = exposure.setdefault(
                    product, {"longLots": 0.0, "shortLots": 0.0}
                )
                if side > 0:
                    product_exposure["longLots"] += lots
                else:
                    product_exposure["shortLots"] += lots
        exposures = []
        for product, values in sorted(exposure.items()):
            long_lots = values["longLots"]
            short_lots = values["shortLots"]
            exposures.append({
                "product": product,
                "longLots": long_lots,
                "shortLots": short_lots,
                "netLots": long_lots - short_lots,
                "grossLots": long_lots + short_lots,
                "lockedLots": min(long_lots, short_lots),
            })
        return (
            sorted(positions, key=lambda item: (item["clientAlias"], item["product"], item["sourcePositionId"])),
            sorted(mappings, key=lambda item: item["demoTicket"]),
            exposures,
        )

    @staticmethod
    def _current_copies(
        rows: dict[str, Any], routes: dict[str, dict[str, str]]
    ) -> list[dict[str, Any]]:
        """Project only owned, currently persisted Demo child Tickets.

        The local monitor cannot safely apportion account-level source or Demo P/L to an
        individual Position.  It therefore reads only optional Position/Ticket-level values
        when the producer persists them, and returns null while that evidence is unavailable.
        """
        alias_by_identity = {
            item["account_key"]: alias for alias, item in routes.items()
        }
        output: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        for raw in rows.values():
            if not isinstance(raw, dict):
                continue
            alias = alias_by_identity.get(str(raw.get("account_key") or ""))
            if not alias:
                continue
            source_lots = _nullable_float(raw.get("source_lots"))
            source_opened_at = _nullable_timestamp(raw.get("source_opened_at"))
            source_opened = _iso_datetime(source_opened_at)
            source_holding_seconds = (
                max(0.0, (now - source_opened.astimezone(UTC)).total_seconds())
                if source_opened
                else None
            )
            source_pnl = CopyPoolFileSnapshotRepository._position_pnl(raw, "source")
            children = raw.get("children", [])
            if not isinstance(children, list):
                continue
            for child in children:
                if not isinstance(child, dict):
                    continue
                ticket = _nullable_int(child.get("ticket"))
                if ticket is None or ticket <= 0:
                    continue
                child_lots = _nullable_float(child.get("lots"))
                child_side = _nullable_int(child.get("side"))
                demo_opened_at = _nullable_timestamp(child.get("open_time"))
                demo_opened = _iso_datetime(demo_opened_at)
                demo_holding_seconds = (
                    max(0.0, (now - demo_opened.astimezone(UTC)).total_seconds())
                    if demo_opened
                    else None
                )
                # The Demo executor's comment identifies one source Position.  Its P/L is
                # therefore Position-level evidence even when a source Position owns more
                # than one current child Ticket.
                demo_pnl = CopyPoolFileSnapshotRepository._position_pnl(raw, "demo")
                output.append({
                    "accountLogin": routes[alias]["login"],
                    "accountPlatform": routes[alias]["platform"],
                    "accountServer": routes[alias]["server"],
                    "product": str(raw.get("product") or "") or None,
                    "sourceDirection": CopyPoolFileSnapshotRepository._side_label(source_lots),
                    "sourcePositionId": _nullable_int(raw.get("source_position_id")),
                    "sourceLots": abs(source_lots) if source_lots is not None else None,
                    "sourceOpenPrice": _nullable_float(raw.get("source_open_price")),
                    "sourceOpenedAt": source_opened_at,
                    "sourceHoldingSeconds": source_holding_seconds,
                    "demoTicket": ticket,
                    "demoDirection": CopyPoolFileSnapshotRepository._side_label(child_side),
                    "demoLots": abs(child_lots) if child_lots is not None else None,
                    "demoOpenPrice": _nullable_float(child.get("open_price")),
                    "demoOpenedAt": demo_opened_at,
                    "demoHoldingSeconds": demo_holding_seconds,
                    "sourceRealizedPnlUsd": source_pnl["realizedUsd"],
                    "sourceFloatingPnlUsd": source_pnl["floatingUsd"],
                    "sourceTotalPnlUsd": source_pnl["totalUsd"],
                    "sourcePnlBasis": source_pnl["basis"],
                    "demoRealizedPnlUsd": demo_pnl["realizedUsd"],
                    "demoFloatingPnlUsd": demo_pnl["floatingUsd"],
                    "demoTotalPnlUsd": demo_pnl["totalUsd"],
                    "demoPnlBasis": demo_pnl["basis"],
                    "copyStatus": str(raw.get("status") or "") or None,
                    "detailPath": f"/copy-pool/accounts/{alias}",
                })
        return sorted(
            output,
            key=lambda item: (
                item["accountLogin"],
                item["product"] or "",
                item["sourcePositionId"] if item["sourcePositionId"] is not None else -1,
                item["demoTicket"],
            ),
        )

    @staticmethod
    def _position_pnl(raw: dict[str, Any], prefix: str) -> dict[str, Any]:
        """Return only exact Position/Ticket P/L evidence, never a client aggregate."""
        nested = raw.get(f"{prefix}_pnl")
        values = nested if isinstance(nested, dict) else raw

        def value(*names: str) -> float | None:
            for name in names:
                parsed = _nullable_float(values.get(name))
                if parsed is not None:
                    return parsed
            return None

        realized = value(
            "realized_usd", "realized_pnl_usd", "realized",
            f"{prefix}_realized_pnl_usd",
        )
        floating = value(
            "floating_usd", "floating_pnl_usd", "floating",
            f"{prefix}_floating_pnl_usd",
        )
        total = value(
            "total_usd", "total_pnl_usd", "total",
            f"{prefix}_total_pnl_usd",
        )
        if total is None and realized is not None and floating is not None:
            total = realized + floating
        complete = total is not None and (
            (realized is not None and floating is not None)
            or value("total_usd", "total_pnl_usd", "total", f"{prefix}_total_pnl_usd") is not None
        )
        return {
            "realizedUsd": realized,
            "floatingUsd": floating,
            "totalUsd": total,
            "basis": (
                (
                    "demo_source_position_comment_realized_plus_floating"
                    if prefix == "demo" else "source_position_realized_plus_floating"
                )
                if complete else (
                    "demo_source_position_comment_partial"
                    if prefix == "demo" else "source_position_partial"
                )
                if realized is not None or floating is not None or total is not None
                else "unavailable"
            ),
        }

    @staticmethod
    def _side_label(value: float | int | None) -> str | None:
        if value is None:
            return None
        return "BUY" if value > 0 else "SELL" if value < 0 else None

    @staticmethod
    def _public_status(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "phase": str(row.get("phase") or "unknown"),
            "server": str(row.get("server") or ""),
            "accountLogin": str(row.get("account_login") or ""),
            "symbol": str(row.get("symbol") or ""),
            "riskProfile": str(row.get("risk_profile") or ""),
            "balanceUsd": _float(row.get("balance_usd")),
            "equityUsd": _float(row.get("equity_usd")),
            "positionCapLots": _float(row.get("position_cap_lots")),
            "hardMaxLots": _float(row.get("hard_max_lots")),
            "cycleLossLimitUsd": _float(row.get("cycle_loss_limit_usd")),
            "dailyLossLimitUsd": _float(row.get("daily_loss_limit_usd")),
            "equityFloorUsd": _float(row.get("equity_floor_usd")),
            "clients": _int(row.get("clients")),
            "activeWeights": _float(row.get("active_weights")),
            "rawTargetLots": _float(row.get("raw_target_lots")),
            "desiredTargetLots": _float(row.get("desired_target_lots")),
            "actualStrategyLots": _float(row.get("actual_strategy_lots")),
            "grossLongLots": _float(row.get("gross_long_lots")),
            "grossShortLots": _float(row.get("gross_short_lots")),
            "bid": _float(row.get("bid")),
            "ask": _float(row.get("ask")),
            "spreadPrice": _float(row.get("spread_price")),
            "quoteAgeSeconds": _float(row.get("quote_age_seconds")),
            "dbSecondsSinceSuccess": _float(row.get("db_seconds_since_success")),
            "dbLatencyWindowEvents": _int(row.get("db_latency_window_events")),
            "dbLatencyP95Seconds": _float(row.get("db_latency_p95_seconds")),
            "reconcileStreak": _int(row.get("reconcile_streak")),
            "pendingSourceSnapshotCount": _int(row.get("pending_source_snapshot_count")),
            "duplicateEvents": _int(row.get("duplicate_events")),
            "strategyMarkedPnlUsd": _float(row.get("strategy_marked_pnl_usd")),
            "cyclePnlUsd": _float(row.get("cycle_pnl_usd")),
            "cooldownUntil": row.get("cooldown_until"),
            "dailyHardStop": _bool(row.get("daily_hard_stop")),
            "terminalTradeAllowed": _bool(row.get("terminal_trade_allowed")),
            "liveExecutionAuthorized": _bool(row.get("live_execution_authorized")),
            "externalPositionConflict": _bool(row.get("external_position_conflict")),
            "pendingOrderConflict": _bool(row.get("pending_order_conflict")),
            "lastError": str(row.get("last_error") or ""),
            "logicalRoutesScanned": _int(row.get("logical_routes_scanned")),
            "logicalRoutesExpected": _int(row.get("logical_routes_expected")),
            "logicalRoutesSelected": _int(row.get("logical_routes_selected")),
            "physicalSourcesScanned": _int(row.get("physical_sources_scanned")),
            "physicalSourcesSelected": _int(row.get("physical_sources_selected")),
            "selectedSourceStalenessSeconds": _float(row.get("selected_source_staleness_seconds")),
            "dbPollLatencyP95Seconds": _float(row.get("db_poll_latency_p95_seconds")),
            "signalLatencyP95Seconds": _float(row.get("signal_latency_p95_seconds")),
            "executionModel": str(row.get("execution_model") or "legacy_net_target"),
            "demoFastActivationRequested": _bool(row.get("demo_fast_activation_requested")),
            "demoFastActivationEnabled": _bool(row.get("demo_fast_activation_enabled")),
            "entryRankQualificationsRequired": _int(row.get("entry_rank_qualifications_required"), 2),
            "entryShadowMinutes": _float(row.get("entry_shadow_minutes"), 10.0),
            "monitorSleeves": _int(row.get("monitor_sleeves")),
            "activeCopyClients": _int(row.get("active_copy_clients")),
            "riskManagedClients": _int(row.get("risk_managed_clients")),
            "independentSourcePositions": _int(row.get("independent_source_positions")),
            "independentDemoTickets": _int(row.get("independent_demo_tickets")),
            "manualControls": {
                "autoTradingEnabled": bool(item.get("auto_trading_enabled", True)),
                "equityFloorEnabled": bool(item.get("equity_floor_enabled", True)),
                "dailyLossEnabled": bool(item.get("daily_loss_enabled", True)),
                "cycleLossEnabled": bool(item.get("cycle_loss_enabled", True)),
            } if isinstance((item := row.get("manual_controls")), dict) else {},
            "portfolioMarginBudgetUsd": _float(row.get("portfolio_margin_budget_usd")),
            "portfolioStressBudgetUsd": _float(row.get("portfolio_stress_budget_usd")),
            "products": [
                {
                    "product": str(item.get("product") or ""),
                    "bid": _float(item.get("bid")),
                    "ask": _float(item.get("ask")),
                    "spreadPrice": _float(item.get("spread_price")),
                    "quoteAgeSeconds": _float(item.get("quote_age_seconds")),
                    "spreadAllowsOpen": _bool(item.get("spread_allows_open")),
                    "actualStrategyLots": _float(item.get("actual_strategy_lots")),
                    "grossLongLots": _float(item.get("gross_long_lots")),
                    "grossShortLots": _float(item.get("gross_short_lots")),
                    "activeWeight": _float(item.get("active_weight")),
                }
                for item in row.get("products", [])
                if isinstance(item, dict)
            ],
        }

    @staticmethod
    def _source_coverage(status: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
        build_sources = {
            str(item.get("physical_key") or ""): item
            for item in coverage.get("sources", [])
            if isinstance(item, dict) and item.get("physical_key")
        }
        runtime_sources = {
            str(item.get("physical_key") or ""): item
            for item in status.get("source_health", [])
            if isinstance(item, dict) and item.get("physical_key")
        }
        source_rows: list[dict[str, Any]] = []
        for key in sorted(set(build_sources) | set(runtime_sources)):
            build = build_sources.get(key, {})
            runtime = runtime_sources.get(key, {})
            selected_clients = _int(
                runtime.get("selected_clients", build.get("selected_clients"))
            )
            build_state = str(build.get("state") or "").strip().lower()
            runtime_state = str(runtime.get("state") or "").strip().lower()
            state = runtime_state or build_state or "unknown"
            # A source without selected customers is deliberately not polled at runtime.
            # It remains a successfully scanned source when the complete build proved it
            # available; a transient producer "starting" state must not look like an outage.
            if selected_clients == 0 and build_state == "ok" and runtime_state != "error":
                state = "idle"
            source_rows.append({
                "physicalKey": key,
                "connection": str(runtime.get("connection") or build.get("connection") or ""),
                "platform": str(runtime.get("platform") or build.get("platform") or ""),
                "logicalRoutes": list(runtime.get("logical_routes") or build.get("logical_routes") or []),
                "candidateAccounts": _int(build.get("candidate_accounts")),
                "eligibleAccounts": _int(build.get("eligible_accounts")),
                "selectedClients": selected_clients,
                "state": state,
                "subscriptionState": "unsubscribed" if state == "idle" else "subscribed",
                "latencyMs": _float(runtime.get("latency_ms", build.get("latency_ms"))),
                "ageSeconds": _float(runtime.get("age_seconds")),
                "lastSuccessAt": str(runtime.get("last_success_at") or build.get("last_success_at") or ""),
                "lastError": str(runtime.get("last_error") or build.get("last_error") or ""),
            })
        return {
            "logicalExpected": _int(status.get("logical_routes_expected"), _int(coverage.get("logical_routes_expected"))),
            "logicalScanned": _int(status.get("logical_routes_scanned"), _int(coverage.get("logical_routes_scanned"))),
            "logicalSelected": _int(status.get("logical_routes_selected")),
            "physicalExpected": _int(coverage.get("physical_sources_expected")),
            "physicalScanned": _int(status.get("physical_sources_scanned"), _int(coverage.get("physical_sources_scanned"))),
            "physicalSelected": _int(status.get("physical_sources_selected")),
            "healthy": sum(row["state"] in {"ok", "idle"} for row in source_rows),
            "monitorAccounts": _int(coverage.get("monitor_accounts")),
            "reserveAccounts": _int(coverage.get("reserve_accounts")),
            "activeAccounts": _int(coverage.get("active_accounts")),
            "selectedSleeves": _int(coverage.get("selected_sleeves")),
            "activeSleeves": _int(coverage.get("active_sleeves")),
            "selectedProducts": [str(value) for value in coverage.get("selected_products", [])],
            "activeProducts": [str(value) for value in coverage.get("active_products", [])],
            "productWeightCapFallback": _bool(coverage.get("product_weight_cap_fallback")),
            "sources": source_rows,
            "hourlyDiscovery": {
                "asOf": str((coverage.get("hourly_discovery") or {}).get("as_of") or ""),
                "buildAsOf": str((coverage.get("hourly_discovery") or {}).get("build_as_of") or ""),
                "factorReadySleevesScanned": _int(
                    (coverage.get("hourly_discovery") or {}).get("factor_ready_sleeves_scanned")
                ),
                "monitorAccounts": _int(
                    (coverage.get("hourly_discovery") or {}).get("monitor_accounts")
                ),
                "reserveAccounts": _int(
                    (coverage.get("hourly_discovery") or {}).get("reserve_accounts")
                ),
            },
        }

    @staticmethod
    def _timeline_row(row: dict[str, str]) -> dict[str, Any]:
        return {
            "time": row.get("time_beijing", ""),
            "phase": row.get("phase", ""),
            "decision": row.get("reason", ""),
            "accountLogin": str(row.get("account_login") or ""),
            "equityUsd": _float(row.get("equity_usd")),
            "positionCapLots": _float(row.get("position_cap_lots")),
            "activeWeights": _float(row.get("active_weights")),
            "rawTargetLots": _float(row.get("raw_target_lots")),
            "desiredTargetLots": _float(row.get("desired_target_lots")),
            "actualStrategyLots": _float(row.get("actual_strategy_lots")),
            "grossLongLots": _float(row.get("gross_long_lots")),
            "grossShortLots": _float(row.get("gross_short_lots")),
            "spreadPrice": _float(row.get("spread_price")),
            "dbLatencyP95Seconds": _float(row.get("db_latency_p95_seconds")),
            "strategyMarkedPnlUsd": _float(row.get("strategy_marked_pnl_usd")),
            "cyclePnlUsd": _float(row.get("cycle_pnl_usd")),
            "reconcileStreak": _int(row.get("reconcile_streak")),
        }

    @staticmethod
    def _event_row(
        row: dict[str, str], routes: dict[str, dict[str, str]]
    ) -> dict[str, Any]:
        alias = str(row.get("client_alias") or "").strip().upper()
        route = routes.get(alias, {})
        return {
            "eventId": row.get("event_id", ""),
            "time": row.get("time_beijing", ""),
            "clientAlias": alias,
            "accountLogin": route.get("login", ""),
            "accountPlatform": route.get("platform", ""),
            "accountServer": route.get("server", ""),
            "detailPath": f"/copy-pool/accounts/{alias}" if alias in routes else "",
            "sourceRoute": row.get("source_route", ""),
            "sourceServer": row.get("source_server", ""),
            "sourcePlatform": row.get("source_platform", ""),
            "sourceSide": row.get("source_side", ""),
            "sourceEntry": _int(row.get("source_entry")),
            "sourceLots": _float(row.get("source_lots")),
            "product": row.get("product", ""),
            "effectiveWeight": _float(row.get("effective_weight")),
            "rawTargetLots": _float(row.get("raw_target_lots")),
            "desiredTargetLots": _float(row.get("desired_target_lots")),
            "actualStrategyLots": _float(row.get("actual_strategy_lots")),
            "grossLongLots": _float(row.get("gross_long_lots")),
            "grossShortLots": _float(row.get("gross_short_lots")),
            "dbLatencySeconds": _float(row.get("db_latency_seconds")),
            "phase": row.get("phase", ""),
        }

    @staticmethod
    def _order_row(
        row: dict[str, str], routes: dict[str, dict[str, str]]
    ) -> dict[str, Any]:
        alias = str(row.get("client_alias") or "").strip().upper()
        route = routes.get(alias, {})
        return {
            "orderEvent": row.get("order_event", ""),
            "time": row.get("time_beijing", ""),
            "action": row.get("action", ""),
            "clientAlias": alias,
            "accountLogin": route.get("login", ""),
            "accountPlatform": route.get("platform", ""),
            "accountServer": route.get("server", ""),
            "detailPath": f"/copy-pool/accounts/{alias}" if alias in routes else "",
            "sourcePositionId": _int(row.get("source_position_id")),
            "product": row.get("product", ""),
            "demoTickets": [
                _int(value)
                for value in str(row.get("demo_tickets") or "").split("|")
                if value
            ],
            "beforeLots": _float(row.get("before_lots")),
            "targetLots": _float(row.get("target_lots")),
            "afterLots": _float(row.get("after_lots")),
            "bid": _float(row.get("bid")),
            "ask": _float(row.get("ask")),
            "spreadPrice": _float(row.get("spread_price")),
            "quoteAgeSeconds": _float(row.get("quote_age_seconds")),
            "retcode": _int(row.get("retcode")),
            "comment": row.get("comment", ""),
        }
