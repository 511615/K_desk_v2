from __future__ import annotations

from datetime import datetime

from kdesk.domain.position_risk import number
from kdesk.infrastructure.bonus_arbitrage import _integer, _money_scale, _source_route, _text, _time_text
from kdesk.infrastructure.position_risk import LegacyPositionRiskRepository, _batches

ENVIRONMENT_BY_CRM = {
    "int_sass_crm_ac": "ac_gb",
    "sass_crm_ac": "ac_cn",
    "crm_cn": "dbg_cn",
    "crm_vn": "dbg_vn",
}


def _fallback_contract(symbol: str) -> float:
    value = "".join(character for character in str(symbol or "").upper() if character.isalnum())
    if value.startswith("XAU"):
        return 100.0
    if value.startswith("XAG"):
        return 5_000.0
    if any(token in value for token in ("OIL", "WTI", "BRENT", "XTI", "XBR")):
        return 1_000.0
    if len(value) >= 6 and value[:6].isalpha():
        return 100_000.0
    return 1.0


class LegacyPositionRiskScanRepository(LegacyPositionRiskRepository):
    def __init__(self, bridge):
        super().__init__(bridge)
        self._units: dict[str, dict] = {}

    def scan_units(self, environments: list[str]) -> list[dict]:
        grouped: dict[tuple[str, str, str, str], list[dict]] = {}
        for source in self.module.MYSQL_SOURCES:
            crm_schema, _ = _source_route(source)
            if ENVIRONMENT_BY_CRM.get(crm_schema) not in environments:
                continue
            key = (_text(source.get("host")), _text(source.get("schema")), _text(source.get("table")), _text(source.get("kind")))
            grouped.setdefault(key, []).append(source)
        self._units = {}
        public = []
        for index, (key, sources) in enumerate(grouped.items(), start=1):
            unit_id = f"position-unit-{index}"
            label = " / ".join(dict.fromkeys(_text(source.get("server") or source.get("name")) for source in sources))
            self._units[unit_id] = {"representative": sources[0], "sources": sources, "key": key}
            public.append({"id": unit_id, "label": label, "schema": key[1]})
        return public

    def _unit(self, unit_id: str) -> dict:
        unit = self._units.get(unit_id)
        if not unit:
            raise ValueError("重仓时点候选扫描数据源不存在")
        return unit

    def discover_candidates(self, unit_id: str, start: datetime, end: datetime) -> list[dict]:
        source = self._unit(unit_id)["representative"]
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                if source.get("kind") == "mt5_deals":
                    cursor.execute(
                        f"""
                        select Login,Symbol,Action,
                               case when weekday(Time)=4 and hour(Time)>=18 then 'weekend' else 'open' end as EventKind,
                               floor(unix_timestamp(Time)/300) as Bucket,
                               count(*) as OrderCount,min(Time) as FirstEvent,max(Time) as LatestEvent,
                               sum(case when VolumeExt>0 then VolumeExt/100000000.0 else Volume/10000.0 end) as EventLots,
                               sum((case when VolumeExt>0 then VolumeExt/100000000.0 else Volume/10000.0 end)
                                   * greatest(ContractSize,1) * greatest(Price,1)) as EventNotional
                        from `{source['schema']}`.`{source['table']}`
                        where Time >= %s and Time < %s and Entry=0 and Action in (0,1)
                          and ((weekday(Time)=4 and hour(Time)>=18) or time(Time) between '21:45:00' and '22:30:59')
                        group by Login,Symbol,Action,EventKind,Bucket
                        """,
                        (start, end),
                    )
                else:
                    cursor.execute(
                        f"""
                        select LOGIN as Login,SYMBOL as Symbol,CMD as Action,
                               case when weekday(OPEN_TIME)=4 and hour(OPEN_TIME)>=18 then 'weekend' else 'open' end as EventKind,
                               floor(unix_timestamp(OPEN_TIME)/300) as Bucket,
                               count(*) as OrderCount,min(OPEN_TIME) as FirstEvent,max(OPEN_TIME) as LatestEvent,
                               sum(VOLUME/100.0) as EventLots,
                               sum(VOLUME/100.0 * greatest(OPEN_PRICE,1)) as BaseExposure
                        from `{source['schema']}`.`{source['table']}`
                        where OPEN_TIME >= %s and OPEN_TIME < %s and CMD in (0,1)
                          and ((weekday(OPEN_TIME)=4 and hour(OPEN_TIME)>=18)
                               or time(OPEN_TIME) between '21:45:00' and '22:30:59')
                        group by LOGIN,SYMBOL,CMD,EventKind,Bucket
                        """,
                        (start, end),
                    )
                rows = [dict(row) for row in cursor.fetchall()]
        for row in rows:
            if source.get("kind") != "mt5_deals":
                row["EventNotional"] = number(row.get("BaseExposure")) * _fallback_contract(str(row.get("Symbol") or ""))
        return rows

    def _route_mappings(self, source: dict, logins: list[int]) -> dict[int, dict]:
        crm_schema, server_code = _source_route(source)
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
        return {_integer(row.get("mt_login")): row for row in rows}

    def _profiles(self, source: dict, logins: list[int]) -> dict[int, dict]:
        rows = []
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                for batch in _batches(logins):
                    placeholders = ",".join(["%s"] * len(batch))
                    if source.get("kind") == "mt5_deals":
                        cursor.execute(
                            f"""
                            select u.Login,u.`Group`,u.Balance,u.Credit,u.Leverage,a.Equity
                            from `{source['schema']}`.`mt5_users_view` u
                            left join `{source['schema']}`.`mt5_accounts` a on a.Login=u.Login
                            where u.Login in ({placeholders})
                            """,
                            tuple(batch),
                        )
                    else:
                        cursor.execute(
                            f"""
                            select LOGIN as Login,`GROUP` as `Group`,BALANCE as Balance,CREDIT as Credit,
                                   LEVERAGE as Leverage,EQUITY as Equity,CURRENCY
                            from `{source['schema']}`.`mt4_users_view` where LOGIN in ({placeholders})
                            """,
                            tuple(batch),
                        )
                    rows.extend(dict(row) for row in cursor.fetchall())
        return {_integer(row.get("Login")): row for row in rows}

    def route_candidates(self, unit_id: str, rows: list[dict]) -> list[dict]:
        unit = self._unit(unit_id)
        logins = sorted({_integer(row.get("Login")) for row in rows if _integer(row.get("Login"))})
        by_login: dict[int, list[dict]] = {}
        for row in rows:
            by_login.setdefault(_integer(row.get("Login")), []).append(row)
        candidates = []
        representative = unit["representative"]
        profiles = self._profiles(representative, logins)
        physical_source = "|".join(unit["key"])
        for source in unit["sources"]:
            crm_schema, server_code = _source_route(source)
            environment = ENVIRONMENT_BY_CRM.get(crm_schema, "")
            for login, mapping in self._route_mappings(source, logins).items():
                profile = profiles.get(login, {})
                scale = _money_scale(mapping.get("mt_type_name"), profile.get("Group"), profile.get("CURRENCY"))
                for row in by_login.get(login, []):
                    candidates.append({
                        "account": str(login), "source": _text(source.get("name")),
                        "platform": _text(source.get("platform")), "server": _text(source.get("server") or source.get("name")),
                        "environment": environment, "crmSchema": crm_schema, "serverCode": server_code,
                        "databaseStatus": _text(mapping.get("status")), "currency": "USC" if scale == 0.01 else _text(profile.get("CURRENCY")) or source.get("default_currency") or "USD",
                        "balance": number(profile.get("Balance")) * scale, "equity": number(profile.get("Equity")) * scale,
                        "leverage": number(profile.get("Leverage")), "eventKind": _text(row.get("EventKind")),
                        "bucket": str(row.get("Bucket") or ""), "symbol": _text(row.get("Symbol")),
                        "direction": "buy" if _integer(row.get("Action")) == 0 else "sell",
                        "orderCount": _integer(row.get("OrderCount")), "eventLots": number(row.get("EventLots")),
                        "eventNotional": number(row.get("EventNotional")), "firstEvent": _time_text(row.get("FirstEvent")),
                        "latestEvent": _time_text(row.get("LatestEvent")), "physicalSource": physical_source,
                        "_candidateMapping": {
                            **mapping, "crmSchema": crm_schema, "serverCode": server_code,
                        },
                    })
        return candidates
