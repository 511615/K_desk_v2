from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime, timedelta
from threading import Lock
from typing import TypeVar

from kdesk.domain.bonus_arbitrage import number, parse_datetime
from kdesk.infrastructure.legacy_bridge import LegacyBridge

CENT_RE = re.compile(r"(?:^|[\\/_-])(?:CENT|USC)(?:$|[\\/_-])", re.IGNORECASE)
COUNTERPART_RE = re.compile(r"#(?:FM|TO)(\d+)", re.IGNORECASE)
T = TypeVar("T")
RAW_HISTORY_CACHE_LIMIT = 64
PREFETCH_BATCH_SIZE = 200


def _text(value: object) -> str:
    return str(value or "").strip()


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _time_text(value: object) -> str:
    parsed = parse_datetime(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else ""


def _source_route(source: dict) -> tuple[str, str]:
    route = source.get("account_route") or {}
    return _text(route.get("schema") or source.get("crm_schema")), _text(route.get("mt_server_code") or source.get("mt_server_code"))


def _money_scale(*values: object) -> float:
    return 0.01 if any(CENT_RE.search(_text(value)) for value in values) else 1.0


class LegacyBonusArbitrageRepository:
    """Read-only account, ledger and trade queries behind the legacy bridge."""

    def __init__(self, bridge: LegacyBridge):
        self.module = bridge.module()
        self._analysis_now = datetime.now().replace(microsecond=0)
        self._cache_lock = Lock()
        self._mapping_cache: dict[tuple, Future] = {}
        self._profile_cache: dict[tuple, Future] = {}
        self._raw_rows_cache: dict[tuple, Future] = {}
        self._peer_family_cache: dict[tuple, Future] = {}

    def _cached(self, cache: dict[tuple, Future], key: tuple, load: Callable[[], T]) -> T:
        with self._cache_lock:
            future = cache.get(key)
            owner = future is None
            if future is None:
                future = Future()
                cache[key] = future
        if owner:
            try:
                future.set_result(load())
            except BaseException as exc:
                future.set_exception(exc)
                with self._cache_lock:
                    if cache.get(key) is future:
                        cache.pop(key, None)
                raise
        return future.result()

    def _seed_cache(self, cache: dict[tuple, Future], key: tuple, value: T) -> None:
        with self._cache_lock:
            if key in cache:
                return
            future = Future()
            future.set_result(value)
            cache[key] = future

    @staticmethod
    def _source_key(source: dict) -> tuple[str, str, str, str]:
        return (
            _text(source.get("host")),
            _text(source.get("schema")),
            _text(source.get("table")),
            _text(source.get("kind")),
        )

    def _load_mapping(self, source: dict, login: int) -> dict | None:
        crm_schema, server_code = _source_route(source)
        if not crm_schema or not server_code:
            return None
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select id,user_id,mt_login,mt_server_code,status,mt_type_name,create_time
                    from `{crm_schema}`.`mt_users_account`
                    where mt_login=%s and mt_server_code=%s
                    order by id desc limit 1
                    """,
                    (login, server_code),
                )
                row = cursor.fetchone()
        return dict(row) if row else None

    def _mapping(self, source: dict, login: int) -> dict | None:
        crm_schema, server_code = _source_route(source)
        key = (self._source_key(source), crm_schema, server_code, login)
        return self._cached(self._mapping_cache, key, lambda: self._load_mapping(source, login))

    def _sources(self, login: int, filters: dict) -> list[tuple[dict, dict]]:
        platform = _text(filters.get("platform"))
        server = _text(filters.get("server"))
        candidates = [
            source for source in self.module.MYSQL_SOURCES
            if self.module.source_allowed(source, platform=platform, server=server)
        ]
        located = []
        for source in candidates:
            mapping = self._mapping(source, login)
            if mapping:
                located.append((source, mapping))
        return located

    def _profile(self, source: dict, mapping: dict, login: int) -> dict:
        current = {}
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                if source.get("kind") == "mt5_deals":
                    cursor.execute(
                        f"""
                        select u.Login,u.`Group`,u.Registration,u.LastAccess,u.Balance,u.Credit,u.Leverage,
                               a.Equity,a.Profit,a.Margin,a.MarginFree,a.MarginLevel
                        from `{source['schema']}`.`mt5_users_view` u
                        left join `{source['schema']}`.`mt5_accounts` a on a.Login=u.Login
                        where u.Login=%s limit 1
                        """,
                        (login,),
                    )
                else:
                    cursor.execute(
                        f"""
                        select LOGIN,`GROUP`,REGDATE,LASTDATE,BALANCE,CREDIT,LEVERAGE,EQUITY,MARGIN,
                               MARGIN_LEVEL,MARGIN_FREE,CURRENCY
                        from `{source['schema']}`.`mt4_users_view`
                        where LOGIN=%s limit 1
                        """,
                        (login,),
                    )
                current = dict(cursor.fetchone() or {})
        return self._profile_from_current(source, mapping, login, current)

    def _profile_from_current(self, source: dict, mapping: dict, login: int, current: dict) -> dict:
        group = _text(mapping.get("mt_type_name"))
        group = _text(current.get("Group") or current.get("GROUP") or group)
        currency = _text(current.get("CURRENCY")) or ("USC" if _money_scale(group, mapping.get("mt_type_name")) == 0.01 else source.get("default_currency") or "USD")
        scale = _money_scale(group, mapping.get("mt_type_name"), currency)
        return {
            "account": str(login),
            "platform": _text(source.get("platform")),
            "server": _text(source.get("server") or source.get("name")),
            "currency": currency,
            "moneyScale": scale,
            "group": group,
            "registration": _time_text(current.get("Registration") or current.get("REGDATE") or mapping.get("create_time")),
            "lastAccess": _time_text(current.get("LastAccess") or current.get("LASTDATE")),
            "balance": number(current.get("Balance") if "Balance" in current else current.get("BALANCE")) * scale,
            "credit": number(current.get("Credit") if "Credit" in current else current.get("CREDIT")) * scale,
            "equity": number(current.get("Equity") if "Equity" in current else current.get("EQUITY")) * scale,
            "margin": number(current.get("Margin") if "Margin" in current else current.get("MARGIN")) * scale,
            "marginLevel": number(current.get("MarginLevel") if "MarginLevel" in current else current.get("MARGIN_LEVEL")),
            "leverage": number(current.get("Leverage") if "Leverage" in current else current.get("LEVERAGE"), 1.0),
            "userId": _integer(mapping.get("user_id")),
            "crmSchema": _source_route(source)[0],
            "serverCode": _source_route(source)[1],
        }

    def _profile_key(self, source: dict, login: int) -> tuple:
        crm_schema, server_code = _source_route(source)
        return self._source_key(source), crm_schema, server_code, login

    def _cached_profile(self, source: dict, mapping: dict, login: int) -> dict:
        key = self._profile_key(source, login)
        return self._cached(self._profile_cache, key, lambda: self._profile(source, mapping, login))

    @staticmethod
    def _chunks(values: list, size: int = PREFETCH_BATCH_SIZE):
        for index in range(0, len(values), size):
            yield values[index:index + size]

    def _prefetch_profiles(self, source: dict, mappings: list[dict]) -> None:
        by_login = {_integer(mapping.get("mt_login")): mapping for mapping in mappings if _integer(mapping.get("mt_login"))}
        missing = [login for login in by_login if self._profile_key(source, login) not in self._profile_cache]
        if not missing:
            return
        current_by_login: dict[int, dict] = {}
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                for batch in self._chunks(missing):
                    placeholders = ",".join(["%s"] * len(batch))
                    if source.get("kind") == "mt5_deals":
                        cursor.execute(
                            f"""
                            select u.Login,u.`Group`,u.Registration,u.LastAccess,u.Balance,u.Credit,u.Leverage,
                                   a.Equity,a.Profit,a.Margin,a.MarginFree,a.MarginLevel
                            from `{source['schema']}`.`mt5_users_view` u
                            left join `{source['schema']}`.`mt5_accounts` a on a.Login=u.Login
                            where u.Login in ({placeholders})
                            """,
                            tuple(batch),
                        )
                    else:
                        cursor.execute(
                            f"""
                            select LOGIN,`GROUP`,REGDATE,LASTDATE,BALANCE,CREDIT,LEVERAGE,EQUITY,MARGIN,
                                   MARGIN_LEVEL,MARGIN_FREE,CURRENCY
                            from `{source['schema']}`.`mt4_users_view`
                            where LOGIN in ({placeholders})
                            """,
                            tuple(batch),
                        )
                    for row in cursor.fetchall():
                        current = dict(row)
                        current_by_login[_integer(current.get("Login") or current.get("LOGIN"))] = current
        for login in missing:
            profile = self._profile_from_current(source, by_login[login], login, current_by_login.get(login, {}))
            self._seed_cache(self._profile_cache, self._profile_key(source, login), profile)

    def _prefetch_peer_families(self, source: dict, mappings: list[dict]) -> None:
        crm_schema, _ = _source_route(source)
        user_ids = sorted({_integer(mapping.get("user_id")) for mapping in mappings if _integer(mapping.get("user_id"))})
        missing = [
            user_id
            for user_id in user_ids
            if (self._source_key(source), crm_schema, user_id) not in self._peer_family_cache
        ]
        if not crm_schema or not missing:
            return
        rows_by_user: dict[int, list[dict]] = defaultdict(list)
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                for batch in self._chunks(missing):
                    placeholders = ",".join(["%s"] * len(batch))
                    cursor.execute(
                        f"""
                        select id,user_id,mt_login,mt_server_code,status,mt_type_name,create_time
                        from `{crm_schema}`.`mt_users_account`
                        where user_id in ({placeholders})
                        order by user_id,id desc
                        """,
                        tuple(batch),
                    )
                    for row in cursor.fetchall():
                        mapping = dict(row)
                        family = rows_by_user[_integer(mapping.get("user_id"))]
                        if len(family) < 21:
                            family.append(mapping)
        for user_id in missing:
            key = self._source_key(source), crm_schema, user_id
            self._seed_cache(self._peer_family_cache, key, rows_by_user.get(user_id, []))

    def prepare_deep_candidates(self, candidates: list[dict]) -> None:
        grouped: dict[tuple, tuple[dict, list[dict]]] = {}
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
                continue
            key = self._source_key(source), _source_route(source)
            if key not in grouped:
                grouped[key] = source, []
            grouped[key][1].append(mapping)
        for source, mappings in grouped.values():
            try:
                self._prefetch_profiles(source, mappings)
                self._prefetch_peer_families(source, mappings)
            except Exception:
                # Prefetch is an optimization; uncached account reads retain the authoritative fallback.
                continue

    def _window(self, profile: dict, filters: dict) -> tuple[datetime, datetime]:
        now = self._analysis_now
        requested_start = parse_datetime(filters.get("start"))
        requested_end = parse_datetime(filters.get("end"))
        registration = parse_datetime(profile.get("registration"))
        start = requested_start - timedelta(days=7) if requested_start else max(registration or now - timedelta(days=365), now - timedelta(days=400))
        end = requested_end + timedelta(days=7) if requested_end else now + timedelta(days=1)
        if end <= start:
            raise ValueError("赠金套利检测结束时间必须晚于开始时间")
        if end - start > timedelta(days=414):
            start = end - timedelta(days=414)
        return start, end

    def _mt5_rows(self, source: dict, login: int, start: datetime, end: datetime) -> tuple[list[dict], list[dict]]:
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select Deal,Login,`Order`,PositionID,Action,Entry,Time,TimeMsc,Symbol,Price,
                           Volume,VolumeExt,Profit,Commission,Storage,Fee,ContractSize,Comment
                    from `{source['schema']}`.`{source['table']}`
                    where Login=%s and Time >= %s and Time < %s
                    order by Time,Deal
                    """,
                    (login, start, end),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        return [row for row in rows if _integer(row.get("Action"), -1) >= 2], [row for row in rows if _integer(row.get("Action"), -1) in (0, 1)]

    def _mt4_rows(self, source: dict, login: int, start: datetime, end: datetime) -> tuple[list[dict], list[dict]]:
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select TICKET,LOGIN,CMD,SYMBOL,VOLUME,OPEN_TIME,OPEN_PRICE,CLOSE_TIME,CLOSE_PRICE,
                           COMMISSION,SWAPS,PROFIT,TAXES,COMMENT
                    from `{source['schema']}`.`{source['table']}`
                    where LOGIN=%s and OPEN_TIME >= %s and OPEN_TIME < %s and CMD in (0,1,6,7)
                    order by OPEN_TIME,TICKET
                    """,
                    (login, start, end),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        return [row for row in rows if _integer(row.get("CMD"), -1) in (6, 7)], [row for row in rows if _integer(row.get("CMD"), -1) in (0, 1)]

    def _raw_rows(self, source: dict, login: int, start: datetime, end: datetime) -> tuple[list[dict], list[dict]]:
        if source.get("kind") == "mt5_deals":
            return self._mt5_rows(source, login, start, end)
        return self._mt4_rows(source, login, start, end)

    def _cached_raw_rows(
        self,
        source: dict,
        login: int,
        start: datetime,
        end: datetime,
    ) -> tuple[list[dict], list[dict]]:
        key = (self._source_key(source), login, start, end)
        with self._cache_lock:
            cache_available = key in self._raw_rows_cache or len(self._raw_rows_cache) < RAW_HISTORY_CACHE_LIMIT
        if cache_available:
            return self._cached(
                self._raw_rows_cache,
                key,
                lambda: self._raw_rows(source, login, start, end),
            )
        return self._raw_rows(source, login, start, end)

    def _mt5_events(self, rows: list[dict], scale: float, peer_logins: set[int]) -> list[dict]:
        deposits = []
        events = []
        for row in rows:
            action = _integer(row.get("Action"), -1)
            comment = _text(row.get("Comment"))
            upper = comment.upper()
            amount = sum(number(row.get(key)) for key in ("Profit", "Commission", "Storage", "Fee")) * scale
            kind = "other"
            if action == 2:
                if upper.startswith("DEP-RS"):
                    kind = "cash_reversal"
                elif upper.startswith(("DEP-", "CRM-DP-")) and amount > 0:
                    kind = "deposit"
                    deposits.append(parse_datetime(row.get("TimeMsc") or row.get("Time")))
                elif upper.startswith(("WDR-", "CRM-CW", "IPD")) or (amount < 0 and upper.startswith("DEP-")):
                    kind = "withdrawal"
                elif upper.startswith(("TFM-", "TFH-")):
                    kind = "transfer"
                elif upper.startswith("RST-") or "NEGATIVE BALANCE" in upper:
                    kind = "reset"
            elif action == 3:
                kind = "bonus_remove" if amount < 0 else "bonus_restore"
                if amount > 0 and ("PRESENTED CREDIT" in upper or "BONUS" in upper):
                    kind = "bonus_grant"
            elif action == 6 and amount > 0 and ("BONUS" in upper or "REWARD" in upper):
                kind = "bonus_grant"
            counterpart = ""
            match = COUNTERPART_RE.search(comment)
            if match and _integer(match.group(1)) in peer_logins:
                counterpart = match.group(1)
            events.append({
                "id": str(row.get("Deal") or ""), "time": _time_text(row.get("TimeMsc") or row.get("Time")),
                "kind": kind, "amount": amount, "comment": comment, "counterparty": counterpart,
                "affectsBalance": action == 2,
            })
        for event in events:
            if event["kind"] != "bonus_restore" or number(event["amount"]) <= 0:
                continue
            when = parse_datetime(event["time"])
            if when and any(value and abs((when - value).total_seconds()) <= 5 for value in deposits):
                event["kind"] = "bonus_grant"
        return events

    def _mt4_events(self, rows: list[dict], scale: float, peer_logins: set[int]) -> list[dict]:
        deposits = []
        events = []
        for row in rows:
            command = _integer(row.get("CMD"), -1)
            comment = _text(row.get("COMMENT"))
            upper = comment.upper()
            amount = number(row.get("PROFIT")) * scale
            kind = "other"
            if command == 6:
                if upper.startswith("DEP-RS"):
                    kind = "cash_reversal"
                elif upper.startswith(("DEP-", "CRM-DP-")) and amount > 0:
                    kind = "deposit"
                    deposits.append(parse_datetime(row.get("OPEN_TIME")))
                elif upper.startswith(("TFM-", "TFH-")) or "INTERNAL TRANSFER" in upper:
                    kind = "transfer"
                elif upper.startswith(("WDR-", "CRM-CW", "IPD")) or amount < 0:
                    kind = "withdrawal"
                elif upper.startswith("RST-") or "NEGATIVE BALANCE" in upper or "ZERO BALANCE" in upper:
                    kind = "reset"
            elif command == 7:
                kind = "bonus_remove" if amount < 0 else "bonus_restore"
                if amount > 0 and ("CREDIT" in upper or "BONUS" in upper):
                    kind = "bonus_grant"
            counterpart = ""
            match = COUNTERPART_RE.search(comment)
            if match and _integer(match.group(1)) in peer_logins:
                counterpart = match.group(1)
            events.append({
                "id": str(row.get("TICKET") or ""), "time": _time_text(row.get("OPEN_TIME")),
                "kind": kind, "amount": amount, "comment": comment, "counterparty": counterpart,
                "affectsBalance": command == 6,
            })
        for event in events:
            if event["kind"] != "bonus_restore" or number(event["amount"]) <= 0:
                continue
            when = parse_datetime(event["time"])
            if when and any(value and abs((when - value).total_seconds()) <= 5 for value in deposits):
                event["kind"] = "bonus_grant"
        return events

    def _events(self, source: dict, rows: list[dict], scale: float, peer_logins: set[int]) -> list[dict]:
        if source.get("kind") == "mt5_deals":
            return self._mt5_events(rows, scale, peer_logins)
        return self._mt4_events(rows, scale, peer_logins)

    def _mt5_trades(self, rows: list[dict], scale: float) -> list[dict]:
        grouped = defaultdict(list)
        for row in rows:
            position = _integer(row.get("PositionID"))
            if position:
                grouped[position].append(row)
        trades = []
        for position, deals in grouped.items():
            opens = [row for row in deals if _integer(row.get("Entry"), -1) == 0]
            closes = [row for row in deals if _integer(row.get("Entry"), -1) in (1, 2, 3)]
            if not opens:
                continue
            opens.sort(key=lambda row: (parse_datetime(row.get("TimeMsc") or row.get("Time")) or datetime.min, _integer(row.get("Deal"))))
            closes.sort(key=lambda row: (parse_datetime(row.get("TimeMsc") or row.get("Time")) or datetime.min, _integer(row.get("Deal"))))
            opened_volume = sum(
                (number(row.get("VolumeExt")) / 100000000.0 if number(row.get("VolumeExt")) else number(row.get("Volume")) / 10000.0)
                for row in opens
            )
            closed_volume = sum(
                (number(row.get("VolumeExt")) / 100000000.0 if number(row.get("VolumeExt")) else number(row.get("Volume")) / 10000.0)
                for row in closes
            )
            remaining_volume = max(opened_volume - closed_volume, 0.0)
            is_open = remaining_volume > 1e-8
            open_price = sum(
                number(row.get("Price")) * (
                    number(row.get("VolumeExt")) / 100000000.0
                    if number(row.get("VolumeExt")) else number(row.get("Volume")) / 10000.0
                )
                for row in opens
            ) / max(opened_volume, 1e-9)
            close_price = sum(
                number(row.get("Price")) * (
                    number(row.get("VolumeExt")) / 100000000.0
                    if number(row.get("VolumeExt")) else number(row.get("Volume")) / 10000.0
                )
                for row in closes
            ) / max(closed_volume, 1e-9) if closes else 0.0
            trades.append({
                "id": str(position), "ticket": str(position), "symbol": _text(opens[0].get("Symbol")),
                "direction": "buy" if _integer(opens[0].get("Action")) == 0 else "sell",
                "openTime": _time_text(opens[0].get("TimeMsc") or opens[0].get("Time")),
                "closeTime": "" if is_open else _time_text(closes[-1].get("TimeMsc") or closes[-1].get("Time")),
                "volume": opened_volume,
                "remainingVolume": remaining_volume,
                "isOpen": is_open,
                "openPrice": open_price,
                "closePrice": close_price,
                "contractSize": number(opens[0].get("ContractSize")),
                "netProfit": sum(sum(number(row.get(key)) for key in ("Profit", "Commission", "Storage", "Fee")) for row in deals) * scale,
                "entryOrders": [
                    {
                        "orderId": str(row.get("Order") or row.get("Deal") or position),
                        "dealId": str(row.get("Deal") or ""),
                        "time": _time_text(row.get("TimeMsc") or row.get("Time")),
                        "volume": (
                            number(row.get("VolumeExt")) / 100000000.0
                            if number(row.get("VolumeExt")) else number(row.get("Volume")) / 10000.0
                        ),
                        "price": number(row.get("Price")),
                    }
                    for row in opens
                ],
            })
        return trades

    def _mt4_trades(self, rows: list[dict], scale: float) -> list[dict]:
        trades = []
        for row in rows:
            opened, closed = parse_datetime(row.get("OPEN_TIME")), parse_datetime(row.get("CLOSE_TIME"))
            if not opened:
                continue
            is_open = not closed or closed <= opened or closed.year <= 1970
            trades.append({
                "id": str(row.get("TICKET") or ""), "ticket": str(row.get("TICKET") or ""),
                "symbol": _text(row.get("SYMBOL")), "direction": "buy" if _integer(row.get("CMD")) == 0 else "sell",
                "openTime": _time_text(opened), "closeTime": "" if is_open else _time_text(closed),
                "volume": number(row.get("VOLUME")) / 100.0,
                "remainingVolume": number(row.get("VOLUME")) / 100.0 if is_open else 0.0,
                "isOpen": is_open,
                "openPrice": number(row.get("OPEN_PRICE")),
                "closePrice": number(row.get("CLOSE_PRICE")),
                "netProfit": sum(number(row.get(key)) for key in ("PROFIT", "COMMISSION", "SWAPS", "TAXES")) * scale,
                "entryOrders": [{
                    "orderId": str(row.get("TICKET") or ""), "dealId": "",
                    "time": _time_text(opened),
                    "volume": number(row.get("VOLUME")) / 100.0,
                    "price": number(row.get("OPEN_PRICE")),
                }],
            })
        return trades

    def _trades(self, source: dict, rows: list[dict], scale: float) -> list[dict]:
        if source.get("kind") == "mt5_deals":
            return self._mt5_trades(rows, scale)
        return self._mt4_trades(rows, scale)

    def _peer_family_mappings(self, source: dict, user_id: int) -> list[dict]:
        crm_schema, _ = _source_route(source)
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select id,user_id,mt_login,mt_server_code,status,mt_type_name,create_time
                    from `{crm_schema}`.`mt_users_account`
                    where user_id=%s
                    order by id desc limit 21
                    """,
                    (user_id,),
                )
                return [dict(row) for row in cursor.fetchall()]

    def _peer_mappings(self, source: dict, mapping: dict, login: int) -> list[dict]:
        user_id = _integer(mapping.get("user_id"))
        crm_schema, _ = _source_route(source)
        if not user_id or not crm_schema:
            return []
        key = (self._source_key(source), crm_schema, user_id)
        family = self._cached(
            self._peer_family_cache,
            key,
            lambda: self._peer_family_mappings(source, user_id),
        )
        return [row for row in family if _integer(row.get("mt_login")) != login][:20]

    def _source_for_mapping(self, crm_schema: str, mapping: dict) -> dict | None:
        return self.module.rebate_churning._source_for(self.module.MYSQL_SOURCES, crm_schema, mapping.get("mt_server_code"))

    def load_account_context(self, login: str, filters: dict) -> dict:
        account = _integer(login)
        if not account:
            raise ValueError("账号格式无效")
        mapping_hint = filters.get("_candidateMapping") or {}
        crm_schema = _text(mapping_hint.get("crmSchema"))
        hinted_mapping = {
            key: mapping_hint.get(key)
            for key in ("user_id", "mt_login", "mt_server_code", "status", "mt_type_name", "create_time")
        }
        hinted_source = self._source_for_mapping(crm_schema, hinted_mapping) if crm_schema else None
        if hinted_source and _integer(hinted_mapping.get("mt_login")) == account:
            located = [(hinted_source, hinted_mapping)]
        else:
            located = self._sources(account, filters)
        if not located:
            raise ValueError("没有找到与所选平台和服务器一致的账户路由")
        source, mapping = located[0]
        profile = self._cached_profile(source, mapping, account)
        profile = dict(profile)
        profile["sourceAmbiguous"] = len(located) > 1
        start, end = self._window(profile, filters)
        peer_mappings = self._peer_mappings(source, mapping, account)
        peer_logins = {_integer(row.get("mt_login")) for row in peer_mappings if _integer(row.get("mt_login"))}
        ledger_rows, trade_rows = self._cached_raw_rows(source, account, start, end)
        events = self._events(source, ledger_rows, number(profile.get("moneyScale"), 1.0), peer_logins)
        trades = self._trades(source, trade_rows, number(profile.get("moneyScale"), 1.0))
        peers = []
        crm_schema = _source_route(source)[0]
        for peer_mapping in peer_mappings:
            peer_source = self._source_for_mapping(crm_schema, peer_mapping)
            peer_login = _integer(peer_mapping.get("mt_login"))
            if not peer_source or not peer_login:
                continue
            peer_profile = self._cached_profile(peer_source, peer_mapping, peer_login)
            _, peer_trade_rows = self._cached_raw_rows(peer_source, peer_login, start, end)
            peers.append({
                "account": str(peer_login),
                "platform": _text(peer_source.get("platform")),
                "server": _text(peer_source.get("server")),
                "sameUser": True,
                "trades": self._trades(peer_source, peer_trade_rows, number(peer_profile.get("moneyScale"), 1.0)),
            })
        return {"profile": profile, "events": events, "trades": trades, "peers": peers}
