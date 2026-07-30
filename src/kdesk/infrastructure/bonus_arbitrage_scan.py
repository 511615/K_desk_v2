from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from kdesk.domain.bonus_arbitrage import number, parse_datetime
from kdesk.infrastructure.bonus_arbitrage import (
    LegacyBonusArbitrageRepository,
    _integer,
    _money_scale,
    _source_route,
    _text,
    _time_text,
)

ENVIRONMENT_BY_CRM = {
    "int_sass_crm_ac": "ac_gb",
    "sass_crm_ac": "ac_cn",
    "crm_cn": "dbg_cn",
    "crm_vn": "dbg_vn",
}


def _batches(values: list[int], size: int = 500):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _candidate_deposit_amount(row: dict, *, mt5: bool) -> float:
    comment = _text(row.get("Comment")).upper()
    if comment.startswith("DEP-RS") or not comment.startswith(("DEP-", "CRM-DP-")):
        return 0.0
    if mt5:
        amount = sum(number(row.get(key)) for key in ("Profit", "Commission", "Storage", "Fee"))
    else:
        amount = number(row.get("Profit"))
    return max(amount, 0.0)


class LegacyBonusArbitrageScanRepository(LegacyBonusArbitrageRepository):
    """Read-only platform candidate discovery plus the account-cycle repository."""

    def __init__(self, bridge):
        super().__init__(bridge)
        self._units: dict[str, dict] = {}

    def scan_units(self, environments: list[str]) -> list[dict]:
        grouped: dict[tuple[str, str, str, str], list[dict]] = {}
        for source in self.module.MYSQL_SOURCES:
            crm_schema, _ = _source_route(source)
            environment = ENVIRONMENT_BY_CRM.get(crm_schema)
            if environment not in environments:
                continue
            key = (
                _text(source.get("host")),
                _text(source.get("schema")),
                _text(source.get("table")),
                _text(source.get("kind")),
            )
            grouped.setdefault(key, []).append(source)
        self._units = {}
        public = []
        for index, (key, sources) in enumerate(grouped.items(), start=1):
            unit_id = f"bonus-unit-{index}"
            label = " / ".join(dict.fromkeys(_text(source.get("server") or source.get("name")) for source in sources))
            self._units[unit_id] = {"representative": sources[0], "sources": sources}
            public.append({"id": unit_id, "label": label, "schema": key[1]})
        return public

    def _raw_candidates(self, source: dict, start: datetime, end: datetime) -> list[dict]:
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                if source.get("kind") == "mt5_deals":
                    cursor.execute(
                        f"""
                        select Login,count(*) as GrantCount,
                               sum(coalesce(Profit,0)+coalesce(Commission,0)+coalesce(Storage,0)+coalesce(Fee,0)) as GrantAmount,
                               sum(case when Action=6 or upper(Comment) like '%%BONUS%%'
                                            or upper(Comment) like '%%PRESENTED CREDIT%%' then 1 else 0 end) as ExplicitGrantCount,
                               max(Time) as LatestGrant
                        from `{source['schema']}`.`{source['table']}`
                        where Time >= %s and Time < %s
                          and ((Action=3 and Profit>0) or (Action=6 and Profit>0))
                        group by Login
                        """,
                        (start, end),
                    )
                else:
                    cursor.execute(
                        f"""
                        select LOGIN as Login,count(*) as GrantCount,sum(PROFIT) as GrantAmount,
                               sum(case when upper(COMMENT) like '%%BONUS%%' or upper(COMMENT) like '%%CREDIT%%'
                                        then 1 else 0 end) as ExplicitGrantCount,
                               max(OPEN_TIME) as LatestGrant
                        from `{source['schema']}`.`{source['table']}`
                        where OPEN_TIME >= %s and OPEN_TIME < %s and CMD=7 and PROFIT>0
                        group by LOGIN
                        """,
                        (start, end),
                    )
                return [dict(row) for row in cursor.fetchall()]

    def _route_mappings(self, source: dict, logins: list[int]) -> dict[int, dict]:
        crm_schema, server_code = _source_route(source)
        if not crm_schema or not server_code or not logins:
            return {}
        rows = []
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                for batch in _batches(logins):
                    placeholders = ",".join(["%s"] * len(batch))
                    cursor.execute(
                        f"""
                        select user_id,mt_login,mt_server_code,status,mt_type_name,create_time
                        from `{crm_schema}`.`mt_users_account`
                        where mt_server_code=%s and mt_login in ({placeholders})
                        """,
                        (server_code, *batch),
                    )
                    rows.extend(dict(row) for row in cursor.fetchall())
        return {int(row["mt_login"]): row for row in rows}

    def discover_candidates(self, unit_id: str, start: datetime, end: datetime) -> list[dict]:
        return self._raw_candidates(self._unit(unit_id)["representative"], start, end)

    def _unit(self, unit_id: str) -> dict:
        unit = self._units.get(unit_id)
        if not unit:
            raise ValueError("赠金候选扫描数据源不存在")
        return unit

    def route_candidates(self, unit_id: str, rows: list[dict]) -> list[dict]:
        unit = self._unit(unit_id)
        merged: dict[int, dict] = {}
        for row in rows:
            login = int(row.get("Login") or 0)
            if not login:
                continue
            if login not in merged:
                merged[login] = {
                    **row,
                    "GrantCount": 0,
                    "ExplicitGrantCount": 0,
                    "GrantAmount": 0.0,
                    "LatestGrant": None,
                }
            target = merged[login]
            target["GrantCount"] += int(number(row.get("GrantCount")))
            target["ExplicitGrantCount"] += int(number(row.get("ExplicitGrantCount")))
            target["GrantAmount"] += number(row.get("GrantAmount"))
            latest = row.get("LatestGrant")
            if latest and (not target["LatestGrant"] or latest > target["LatestGrant"]):
                target["LatestGrant"] = latest
        raw = list(merged.values())
        logins = sorted({int(row.get("Login") or 0) for row in raw if int(row.get("Login") or 0)})
        by_login = {int(row.get("Login") or 0): row for row in raw}
        candidates = []
        for source in unit["sources"]:
            crm_schema, server_code = _source_route(source)
            environment = ENVIRONMENT_BY_CRM.get(crm_schema, "")
            for login, mapping in self._route_mappings(source, logins).items():
                row = by_login[login]
                scale = _money_scale(mapping.get("mt_type_name"))
                candidates.append({
                    "account": str(login),
                    "source": _text(source.get("name")),
                    "platform": _text(source.get("platform")),
                    "server": _text(source.get("server") or source.get("name")),
                    "environment": environment,
                    "crmSchema": crm_schema,
                    "serverCode": server_code,
                    "databaseStatus": _text(mapping.get("status")),
                    "userId": _integer(mapping.get("user_id")),
                    "mtTypeName": _text(mapping.get("mt_type_name")),
                    "registration": _time_text(mapping.get("create_time")),
                    "currency": "USC" if scale == 0.01 else _text(source.get("default_currency")) or "USD",
                    "grantCount": int(number(row.get("GrantCount"))),
                    "explicitGrantCount": int(number(row.get("ExplicitGrantCount"))),
                    "grantAmount": number(row.get("GrantAmount")) * scale,
                    "latestGrant": _time_text(row.get("LatestGrant")),
                })
        return candidates

    def _candidate_deposit_totals(self, source: dict, mappings: list[dict]) -> dict[int, float]:
        now = self._analysis_now
        floor = now - timedelta(days=400)
        starts = {
            _integer(mapping.get("mt_login")): max(parse_datetime(mapping.get("create_time")) or now - timedelta(days=365), floor)
            for mapping in mappings
            if _integer(mapping.get("mt_login"))
        }
        totals: dict[int, float] = defaultdict(float)
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                for batch in _batches(sorted(starts), 100):
                    placeholders = ",".join(["%s"] * len(batch))
                    earliest = min(starts[login] for login in batch)
                    if source.get("kind") == "mt5_deals":
                        cursor.execute(
                            f"""
                            select Login,Time,Profit,Commission,Storage,Fee,Comment
                            from `{source['schema']}`.`{source['table']}`
                            where Login in ({placeholders}) and Time >= %s and Time < %s and Action=2
                              and (upper(Comment) like 'DEP-%%' or upper(Comment) like 'CRM-DP-%%')
                            """,
                            (*batch, earliest, now + timedelta(days=1)),
                        )
                    else:
                        cursor.execute(
                            f"""
                            select LOGIN as Login,OPEN_TIME as Time,PROFIT as Profit,COMMENT as Comment
                            from `{source['schema']}`.`{source['table']}`
                            where LOGIN in ({placeholders}) and OPEN_TIME >= %s and OPEN_TIME < %s and CMD=6
                              and (upper(COMMENT) like 'DEP-%%' or upper(COMMENT) like 'CRM-DP-%%')
                            """,
                            (*batch, earliest, now + timedelta(days=1)),
                        )
                    for row in cursor.fetchall():
                        item = dict(row)
                        login = _integer(item.get("Login"))
                        when = parse_datetime(item.get("Time"))
                        if login in starts and when and when >= starts[login]:
                            totals[login] += _candidate_deposit_amount(
                                item,
                                mt5=source.get("kind") == "mt5_deals",
                            )
        return dict(totals)

    def enrich_ranking_metrics(self, candidates: list[dict]) -> dict:
        grouped: dict[tuple, tuple[dict, list[tuple[dict, dict]]]] = {}
        failures = []
        for candidate in candidates:
            mapping = {
                "user_id": candidate.get("userId"),
                "mt_login": candidate.get("account"),
                "mt_server_code": candidate.get("serverCode"),
                "status": candidate.get("databaseStatus"),
                "mt_type_name": candidate.get("mtTypeName"),
                "create_time": candidate.get("registration"),
            }
            source = self._source_for_mapping(_text(candidate.get("crmSchema")), mapping)
            if not source:
                candidate["rankingEvidence"] = "route_unavailable"
                continue
            key = self._source_key(source), _source_route(source)
            if key not in grouped:
                grouped[key] = source, []
            grouped[key][1].append((candidate, mapping))

        for source, items in grouped.values():
            mappings = [mapping for _, mapping in items]
            try:
                self._prefetch_profiles(source, mappings)
                raw_deposits = self._candidate_deposit_totals(source, mappings)
                for candidate, mapping in items:
                    login = _integer(mapping.get("mt_login"))
                    profile = self._cached_profile(source, mapping, login)
                    scale = number(profile.get("moneyScale"), 1.0)
                    deposit_total = max(number(raw_deposits.get(login)) * scale, 0.0)
                    current_margin = max(number(profile.get("margin")), 0.0)
                    candidate["currentMargin"] = current_margin
                    candidate["depositTotal"] = deposit_total
                    candidate["marginToDeposit"] = current_margin / deposit_total if deposit_total > 0 else None
                    candidate["rankingEvidence"] = "current_margin_over_cumulative_deposit" if deposit_total > 0 else "deposit_unavailable"
            except Exception as exc:
                failures.append({
                    "stage": "candidate_rank",
                    "source": _text(source.get("server") or source.get("name")),
                    "platform": _text(source.get("platform")),
                    "server": _text(source.get("server") or source.get("name")),
                    "reason": str(exc),
                    "fallback": "赠金证据排序",
                })
        return {"candidates": candidates, "failures": failures}
