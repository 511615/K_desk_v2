from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from kdesk.domain.position_risk import (
    OPPOSITE_LOT_SIMILARITY_THRESHOLD,
    canonical_symbol,
    match_synchronized_peer_orders,
    number,
    parse_datetime,
)
from kdesk.infrastructure.bonus_arbitrage import _integer, _money_scale, _source_route, _text, _time_text
from kdesk.infrastructure.legacy_bridge import LegacyBridge


def _volume_mt5(row: dict) -> float:
    extended = number(row.get("VolumeExt"))
    return extended / 100_000_000.0 if extended else number(row.get("Volume")) / 10_000.0


def _batches(values: list[int], size: int = 500):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _source_key(source: dict) -> tuple[str, str, str, str]:
    return tuple(_text(source.get(key)) for key in ("host", "schema", "table", "kind"))


def _bounded_target_query(
    targets: list,
    fetch_batch: Callable[[list], list[dict]],
    *,
    row_limit: int,
    saturated_message: str,
) -> list[dict]:
    if not targets:
        return []
    rows = fetch_batch(targets)
    if len(rows) < row_limit:
        return rows
    if len(targets) == 1:
        raise RuntimeError(saturated_message)
    midpoint = len(targets) // 2
    return [
        *_bounded_target_query(
            targets[:midpoint],
            fetch_batch,
            row_limit=row_limit,
            saturated_message=saturated_message,
        ),
        *_bounded_target_query(
            targets[midpoint:],
            fetch_batch,
            row_limit=row_limit,
            saturated_message=saturated_message,
        ),
    ]


def _distinct_target_windows(target_orders: list[dict], *, require_close: bool) -> list[dict]:
    distinct = []
    seen = set()
    for target in target_orders:
        opened = parse_datetime(target.get("openTime"))
        closed = parse_datetime(target.get("closeTime")) if require_close else None
        if not opened or (require_close and not closed):
            continue
        key = (opened, closed)
        if key in seen:
            continue
        seen.add(key)
        distinct.append(target)
    return distinct


def _target_open_index(target_orders: list[dict]) -> dict[tuple[str, int], list[dict]]:
    index: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for target in target_orders:
        opened = parse_datetime(target.get("openTime"))
        if opened:
            index[(canonical_symbol(target.get("symbol")), int(opened.timestamp()))].append(target)
    return index


def _mt5_open_matches_target(row: dict, target_index: dict[tuple[str, int], list[dict]], *, opposite_only: bool) -> bool:
    opened = parse_datetime(row.get("Time"))
    if not opened:
        return False
    symbol = canonical_symbol(row.get("Symbol"))
    direction = "buy" if _integer(row.get("Action")) == 0 else "sell"
    volume = _volume_mt5(row)
    for second in range(int(opened.timestamp()) - 5, int(opened.timestamp()) + 6):
        for target in target_index.get((symbol, second), []):
            target_opened = parse_datetime(target.get("openTime"))
            if not target_opened or abs((opened - target_opened).total_seconds()) > 5:
                continue
            same_direction = direction == _text(target.get("direction")).lower()
            if opposite_only and same_direction:
                continue
            if not same_direction:
                target_volume = number(target.get("volume"))
                similarity = min(target_volume, volume) / max(target_volume, volume, 1e-9)
                if similarity < OPPOSITE_LOT_SIMILARITY_THRESHOLD:
                    continue
            return True
    return False


def _mt5_target_predicate(target: dict, *, opposite_only: bool) -> tuple[str, tuple] | None:
    opened = parse_datetime(target.get("openTime"))
    symbol = canonical_symbol(target.get("symbol"))
    if not opened or not symbol:
        return None
    clause = "(Time >= %s and Time <= %s and Symbol like %s"
    parameters: list[object] = [opened - timedelta(seconds=5), opened + timedelta(seconds=5), f"{symbol}%"]
    direction = _text(target.get("direction")).lower()
    volume = number(target.get("volume"))
    if opposite_only and direction in {"buy", "sell"} and volume > 0:
        clause += (
            " and Action=%s and "
            "(case when VolumeExt>0 then VolumeExt/100000000.0 else Volume/10000.0 end) between %s and %s"
        )
        parameters.extend((1 if direction == "buy" else 0, volume * OPPOSITE_LOT_SIMILARITY_THRESHOLD, volume / OPPOSITE_LOT_SIMILARITY_THRESHOLD))
    return f"{clause})", tuple(parameters)


class LegacyPositionRiskRepository:
    """Read-only, route-aware account history used by both Toxic and discovery."""

    def __init__(self, bridge: LegacyBridge):
        self.bridge = bridge
        self.module = bridge.module()

    @staticmethod
    def _mapping_hint(filters: dict) -> dict:
        value = filters.get("_candidateMapping")
        return dict(value) if isinstance(value, dict) else {}

    def _source_from_hint(self, hint: dict, filters: dict) -> tuple[dict, dict] | None:
        crm_schema = _text(hint.get("crmSchema"))
        server_code = _text(hint.get("mt_server_code") or hint.get("serverCode"))
        login = _integer(hint.get("mt_login"))
        for source in self.module.MYSQL_SOURCES:
            route_schema, route_server = _source_route(source)
            if crm_schema == route_schema and server_code == route_server and login:
                return source, hint
        return None

    def _locate(self, account: int, filters: dict) -> tuple[dict, dict]:
        hinted = self._source_from_hint(self._mapping_hint(filters), filters)
        if hinted and _integer(hinted[1].get("mt_login")) == account:
            return hinted
        platform = _text(filters.get("platform"))
        server = _text(filters.get("server"))
        for source in self.module.MYSQL_SOURCES:
            if not self.module.source_allowed(source, platform=platform, server=server):
                continue
            crm_schema, server_code = _source_route(source)
            with self.module.mysql_trade_connect(source) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        select user_id,mt_login,mt_server_code,status,mt_type_name,create_time
                        from `{crm_schema}`.`mt_users_account`
                        where mt_login=%s and mt_server_code=%s order by id desc limit 1
                        """,
                        (account, server_code),
                    )
                    mapping = cursor.fetchone()
            if mapping:
                return source, dict(mapping)
        raise ValueError("没有找到与所选平台和服务器一致的账户路由")

    def _profile(self, source: dict, mapping: dict, account: int) -> dict:
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                if source.get("kind") == "mt5_deals":
                    cursor.execute(
                        f"""
                        select u.Login,u.`Group`,u.Registration,u.Balance,u.Credit,u.Leverage,
                               a.Equity,a.Margin,a.MarginFree,a.MarginLevel
                        from `{source['schema']}`.`mt5_users_view` u
                        left join `{source['schema']}`.`mt5_accounts` a on a.Login=u.Login
                        where u.Login=%s limit 1
                        """,
                        (account,),
                    )
                else:
                    cursor.execute(
                        f"""
                        select LOGIN,`GROUP`,REGDATE,BALANCE,CREDIT,LEVERAGE,EQUITY,MARGIN,
                               MARGIN_FREE,MARGIN_LEVEL,CURRENCY
                        from `{source['schema']}`.`mt4_users_view` where LOGIN=%s limit 1
                        """,
                        (account,),
                    )
                current = dict(cursor.fetchone() or {})
        group = _text(current.get("Group") or current.get("GROUP") or mapping.get("mt_type_name"))
        currency = _text(current.get("CURRENCY")) or source.get("default_currency") or ("USC" if _money_scale(group) == 0.01 else "USD")
        scale = _money_scale(group, mapping.get("mt_type_name"), currency)
        return {
            "account": str(account),
            "platform": _text(source.get("platform")),
            "server": _text(source.get("server") or source.get("name")),
            "currency": currency,
            "moneyScale": scale,
            "group": group,
            "registration": _time_text(current.get("Registration") or current.get("REGDATE") or mapping.get("create_time")),
            "balance": number(current.get("Balance") if "Balance" in current else current.get("BALANCE")) * scale,
            "credit": number(current.get("Credit") if "Credit" in current else current.get("CREDIT")) * scale,
            "equity": number(current.get("Equity") if "Equity" in current else current.get("EQUITY")) * scale,
            "margin": number(current.get("Margin") if "Margin" in current else current.get("MARGIN")) * scale,
            "marginLevel": number(current.get("MarginLevel") if "MarginLevel" in current else current.get("MARGIN_LEVEL")),
            "leverage": number(current.get("Leverage") if "Leverage" in current else current.get("LEVERAGE"), 1.0),
            "crmSchema": _source_route(source)[0],
            "serverCode": _source_route(source)[1],
            "databaseStatus": _text(mapping.get("status")),
        }

    def _window(self, profile: dict, filters: dict) -> tuple[datetime, datetime, datetime | None, datetime | None]:
        now = datetime.now()
        requested_start = parse_datetime(filters.get("start"))
        requested_end = parse_datetime(filters.get("end"))
        registration = parse_datetime(profile.get("registration"))
        analysis_start = requested_start
        analysis_end = requested_end
        if requested_start:
            start = requested_start - timedelta(days=180)
        else:
            start = max(registration or now - timedelta(days=400), now - timedelta(days=400))
        end = min((requested_end + timedelta(days=7)) if requested_end else now + timedelta(days=1), now + timedelta(days=1))
        return start, end, analysis_start, analysis_end

    def _mt5_history(self, source: dict, account: int, start: datetime, end: datetime, scale: float) -> tuple[list[dict], list[dict]]:
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select Deal,`Order`,PositionID,Action,Entry,Time,TimeMsc,Symbol,Price,Volume,VolumeExt,
                           Profit,Commission,Storage,Fee,ContractSize,Comment
                    from `{source['schema']}`.`{source['table']}`
                    where Login=%s and Time >= %s and Time < %s
                    order by PositionID,Time,Deal
                    limit 100000
                    """,
                    (account, start, end),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        grouped: dict[int, list[dict]] = defaultdict(list)
        cashflows = []
        for row in rows:
            action = _integer(row.get("Action"), -1)
            if action in (0, 1) and _integer(row.get("PositionID")):
                grouped[_integer(row.get("PositionID"))].append(row)
            elif action >= 2:
                cashflows.append({
                    "time": _time_text(row.get("TimeMsc") or row.get("Time")),
                    "amount": sum(number(row.get(key)) for key in ("Profit", "Commission", "Storage", "Fee")) * scale,
                    "affectsBalance": action not in {3, 6},
                    "comment": _text(row.get("Comment")),
                })
        trades = []
        for position, deals in grouped.items():
            opens = [row for row in deals if _integer(row.get("Entry"), -1) == 0]
            closes = [row for row in deals if _integer(row.get("Entry"), -1) in {1, 2, 3}]
            if not opens:
                continue
            opens.sort(key=lambda row: (_time_text(row.get("TimeMsc") or row.get("Time")), _integer(row.get("Deal"))))
            closes.sort(key=lambda row: (_time_text(row.get("TimeMsc") or row.get("Time")), _integer(row.get("Deal"))))
            open_volume = sum(_volume_mt5(row) for row in opens)
            close_volume = sum(_volume_mt5(row) for row in closes)
            open_price = sum(number(row.get("Price")) * _volume_mt5(row) for row in opens) / max(open_volume, 1e-9)
            close_price = sum(number(row.get("Price")) * _volume_mt5(row) for row in closes) / max(close_volume, 1e-9) if closes else 0.0
            action = _integer(opens[0].get("Action"))
            trades.append({
                "id": str(position), "ticket": str(position), "symbol": _text(opens[0].get("Symbol")),
                "direction": "buy" if action == 0 else "sell",
                "openTime": _time_text(opens[0].get("TimeMsc") or opens[0].get("Time")),
                "closeTime": _time_text(closes[-1].get("TimeMsc") or closes[-1].get("Time")) if closes else "",
                "volume": open_volume, "remainingVolume": max(open_volume - close_volume, 0.0),
                "isOpen": not closes or close_volume + 1e-8 < open_volume,
                "openPrice": open_price, "closePrice": close_price,
                "contractSize": number(opens[0].get("ContractSize")),
                "profit": sum(number(row.get("Profit")) for row in deals) * scale,
                "netProfit": sum(sum(number(row.get(key)) for key in ("Profit", "Commission", "Storage", "Fee")) for row in deals) * scale,
                "entryOrders": [
                    {
                        "orderId": str(row.get("Order") or row.get("Deal") or position),
                        "dealId": str(row.get("Deal") or ""),
                        "time": _time_text(row.get("TimeMsc") or row.get("Time")),
                        "volume": _volume_mt5(row),
                        "price": number(row.get("Price")),
                    }
                    for row in opens
                ],
            })
        return trades, cashflows

    def _mt4_history(self, source: dict, account: int, start: datetime, end: datetime, scale: float) -> tuple[list[dict], list[dict]]:
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    select TICKET,CMD,SYMBOL,VOLUME,OPEN_TIME,OPEN_PRICE,CLOSE_TIME,CLOSE_PRICE,
                           PROFIT,COMMISSION,SWAPS,TAXES,COMMENT
                    from `{source['schema']}`.`{source['table']}`
                    where LOGIN=%s and OPEN_TIME >= %s and OPEN_TIME < %s and CMD in (0,1,6,7)
                    order by OPEN_TIME,TICKET
                    limit 100000
                    """,
                    (account, start, end),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        trades = []
        cashflows = []
        for row in rows:
            command = _integer(row.get("CMD"), -1)
            if command in (6, 7):
                cashflows.append({
                    "time": _time_text(row.get("OPEN_TIME")), "amount": number(row.get("PROFIT")) * scale,
                    "affectsBalance": command == 6,
                    "comment": _text(row.get("COMMENT")),
                })
                continue
            closed = parse_datetime(row.get("CLOSE_TIME"))
            is_open = not closed or closed.year <= 1971
            trades.append({
                "id": str(row.get("TICKET")), "ticket": str(row.get("TICKET")), "symbol": _text(row.get("SYMBOL")),
                "direction": "buy" if command == 0 else "sell", "openTime": _time_text(row.get("OPEN_TIME")),
                "closeTime": "" if is_open else _time_text(row.get("CLOSE_TIME")),
                "volume": number(row.get("VOLUME")) / 100.0, "remainingVolume": number(row.get("VOLUME")) / 100.0 if is_open else 0.0,
                "isOpen": is_open, "openPrice": number(row.get("OPEN_PRICE")), "closePrice": number(row.get("CLOSE_PRICE")),
                "profit": number(row.get("PROFIT")) * scale,
                "netProfit": sum(number(row.get(key)) for key in ("PROFIT", "COMMISSION", "SWAPS", "TAXES")) * scale,
                "entryOrders": [{
                    "orderId": str(row.get("TICKET") or ""), "dealId": "",
                    "time": _time_text(row.get("OPEN_TIME")),
                    "volume": number(row.get("VOLUME")) / 100.0,
                    "price": number(row.get("OPEN_PRICE")),
                }],
            })
        return trades, cashflows

    def load_account_context(self, account: str, filters: dict) -> dict:
        login = int(account)
        source, mapping = self._locate(login, filters)
        profile = self._profile(source, mapping, login)
        start, end, analysis_start, analysis_end = self._window(profile, filters)
        if source.get("kind") == "mt5_deals":
            trades, cashflows = self._mt5_history(source, login, start, end, number(profile.get("moneyScale"), 1.0))
        else:
            trades, cashflows = self._mt4_history(source, login, start, end, number(profile.get("moneyScale"), 1.0))
        if not trades:
            raise ValueError("账户在分析范围内没有可检测交易")
        return {
            "profile": profile,
            "trades": trades,
            "cashflows": cashflows,
            "source": source,
            "mapping": mapping,
            "analysisStart": analysis_start,
            "analysisEnd": analysis_end,
        }

    def _peer_source_units(self) -> list[dict]:
        grouped: dict[tuple[str, str, str, str], list[dict]] = {}
        for source in self.module.MYSQL_SOURCES:
            grouped.setdefault(_source_key(source), []).append(source)
        return [{"key": key, "representative": sources[0], "sources": sources} for key, sources in grouped.items()]

    @staticmethod
    def _peer_source_metadata(unit: dict) -> dict:
        source = unit["representative"]
        servers = list(dict.fromkeys(_text(item.get("server") or item.get("name")) for item in unit["sources"]))
        return {
            "platform": _text(source.get("platform")),
            "server": " / ".join(servers),
            "database": f"{_text(source.get('schema'))}.{_text(source.get('table'))}",
            "physicalSource": "|".join(unit["key"][1:]),
        }

    def _load_mt4_peer_orders(self, unit: dict, target_orders: list[dict]) -> list[dict]:
        source = unit["representative"]
        metadata = self._peer_source_metadata(unit)
        rows: dict[tuple[str, str], dict] = {}
        target_windows = _distinct_target_windows(target_orders, require_close=True)
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                for index in range(0, len(target_windows), 25):
                    batch = target_windows[index:index + 25]

                    def fetch_batch(targets: list[dict]) -> list[dict]:
                        clauses = []
                        parameters = []
                        for target in targets:
                            opened = parse_datetime(target.get("openTime"))
                            closed = parse_datetime(target.get("closeTime"))
                            assert opened and closed
                            clauses.append("(OPEN_TIME >= %s and OPEN_TIME <= %s and CLOSE_TIME >= %s and CLOSE_TIME <= %s)")
                            parameters.extend((opened - timedelta(seconds=5), opened + timedelta(seconds=5), closed - timedelta(seconds=5), closed + timedelta(seconds=5)))
                        cursor.execute(
                            f"""
                            select TICKET,LOGIN,CMD,SYMBOL,VOLUME,OPEN_TIME,CLOSE_TIME
                            from `{source['schema']}`.`{source['table']}`
                            where CMD in (0,1) and ({' or '.join(clauses)})
                            order by OPEN_TIME,TICKET limit 20000
                            """,
                            tuple(parameters),
                        )
                        return [dict(row) for row in cursor.fetchall()]

                    fetched = _bounded_target_query(
                        batch,
                        fetch_batch,
                        row_limit=20_000,
                        saturated_message="MT4单笔目标订单的同步候选达到20000行上限，结果不能视为完整",
                    )
                    for raw in fetched:
                        row = raw
                        closed = parse_datetime(row.get("CLOSE_TIME"))
                        if not closed or closed.year <= 1971:
                            continue
                        login = str(row.get("LOGIN") or "")
                        ticket = str(row.get("TICKET") or "")
                        rows[(login, ticket)] = {
                            **metadata, "account": login, "orderId": ticket, "positionId": ticket, "dealId": "",
                            "symbol": _text(row.get("SYMBOL")),
                            "direction": "buy" if _integer(row.get("CMD")) == 0 else "sell",
                            "volume": number(row.get("VOLUME")) / 100.0,
                            "openTime": _time_text(row.get("OPEN_TIME")), "closeTime": _time_text(row.get("CLOSE_TIME")),
                            "fullyClosed": True,
                        }
        return list(rows.values())

    def _load_mt5_peer_orders(self, unit: dict, target_orders: list[dict]) -> list[dict]:
        source = unit["representative"]
        metadata = self._peer_source_metadata(unit)
        candidate_opens: dict[tuple[int, int, int], dict] = {}
        target_windows = _distinct_target_windows(target_orders, require_close=False)
        target_index = _target_open_index(target_orders)
        opposite_only = bool(target_orders) and all(bool(target.get("_oppositeOnly")) for target in target_orders)
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                for index in range(0, len(target_windows), 25):
                    batch = target_windows[index:index + 25]

                    def fetch_batch(targets: list[dict]) -> list[dict]:
                        clauses = []
                        parameters = []
                        for target in targets:
                            predicate = _mt5_target_predicate(target, opposite_only=opposite_only)
                            if predicate:
                                clause, values = predicate
                                clauses.append(clause)
                                parameters.extend(values)
                        if not clauses:
                            return []
                        cursor.execute(
                            f"""
                            select Deal,`Order`,PositionID,Login,Action,Entry,Time,TimeMsc,Symbol,Volume,VolumeExt
                            from `{source['schema']}`.`{source['table']}`
                            where Entry=0 and Action in (0,1) and ({' or '.join(clauses)})
                            order by Time,Deal limit 20000
                            """,
                            tuple(parameters),
                        )
                        return [dict(row) for row in cursor.fetchall()]

                    fetched = _bounded_target_query(
                        batch,
                        fetch_batch,
                        row_limit=20_000,
                        saturated_message="MT5单笔目标订单的同步开仓候选达到20000行上限，结果不能视为完整",
                    )
                    for raw in fetched:
                        row = raw
                        if not _mt5_open_matches_target(row, target_index, opposite_only=opposite_only):
                            continue
                        key = (_integer(row.get("Login")), _integer(row.get("PositionID")), _integer(row.get("Deal")))
                        if key[0] and key[1]:
                            candidate_opens[key] = row
                pairs = sorted({(login, position) for login, position, _deal in candidate_opens})
                if not pairs:
                    return []
                opened_values = [parse_datetime(row.get("openTime")) for row in target_orders]
                closed_values = [parse_datetime(row.get("closeTime")) for row in target_orders]
                earliest = min(value for value in opened_values if value) - timedelta(seconds=5)
                latest = max(value for value in closed_values if value) + timedelta(seconds=5)
                deal_rows = []
                for index in range(0, len(pairs), 150):
                    batch = pairs[index:index + 150]
                    pair_sql = " or ".join(["(Login=%s and PositionID=%s)"] * len(batch))
                    pair_params = tuple(value for pair in batch for value in pair)
                    cursor.execute(
                        f"""
                        select Deal,`Order`,PositionID,Login,Action,Entry,Time,TimeMsc,Symbol,Volume,VolumeExt
                        from `{source['schema']}`.`{source['table']}`
                        where Action in (0,1) and Time >= %s and Time <= %s and ({pair_sql})
                        order by Login,PositionID,Time,Deal limit 50000
                        """,
                        (earliest, latest, *pair_params),
                    )
                    fetched = cursor.fetchall()
                    if len(fetched) >= 50000:
                        raise RuntimeError("MT5候选仓位成交达到50000行上限，结果不能视为完整")
                    deal_rows.extend(dict(row) for row in fetched)
        grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
        for row in deal_rows:
            grouped[(_integer(row.get("Login")), _integer(row.get("PositionID")))].append(row)
        normalized = []
        for (login, position), rows in grouped.items():
            opens = [row for row in rows if _integer(row.get("Entry"), -1) == 0]
            closes = [row for row in rows if _integer(row.get("Entry"), -1) in {1, 2, 3}]
            open_volume = sum(_volume_mt5(row) for row in opens)
            close_volume = sum(_volume_mt5(row) for row in closes)
            close_times = [parse_datetime(row.get("TimeMsc") or row.get("Time")) for row in closes]
            close_times = [value for value in close_times if value]
            if not opens or not close_times or close_volume + 1e-8 < open_volume:
                continue
            close_time = max(close_times)
            for row in opens:
                normalized.append({
                    **metadata, "account": str(login),
                    "orderId": str(row.get("Order") or row.get("Deal") or position),
                    "positionId": str(position), "dealId": str(row.get("Deal") or ""),
                    "symbol": _text(row.get("Symbol")),
                    "direction": "buy" if _integer(row.get("Action")) == 0 else "sell",
                    "volume": _volume_mt5(row), "openTime": _time_text(row.get("TimeMsc") or row.get("Time")),
                    "closeTime": close_time.strftime("%Y-%m-%d %H:%M:%S"), "fullyClosed": True,
                })
        return normalized

    def _resolve_peer_servers(self, unit: dict, rows: list[dict]) -> list[dict]:
        if len(unit["sources"]) <= 1 or not rows:
            return rows
        logins = sorted({_integer(row.get("account")) for row in rows if _integer(row.get("account"))})
        routed_servers: dict[int, set[str]] = defaultdict(set)
        source = unit["representative"]
        with self.module.mysql_trade_connect(source) as connection:
            with connection.cursor() as cursor:
                for logical_source in unit["sources"]:
                    crm_schema, server_code = _source_route(logical_source)
                    server = _text(logical_source.get("server") or logical_source.get("name"))
                    for batch in _batches(logins):
                        placeholders = ",".join(["%s"] * len(batch))
                        cursor.execute(
                            f"""
                            select mt_login
                            from `{crm_schema}`.`mt_users_account`
                            where mt_server_code=%s and mt_login in ({placeholders})
                            """,
                            (server_code, *batch),
                        )
                        for mapping in cursor.fetchall():
                            routed_servers[_integer(mapping.get("mt_login"))].add(server)
        for row in rows:
            resolved = sorted(routed_servers.get(_integer(row.get("account"))) or [])
            if resolved:
                row["server"] = " / ".join(resolved)
        return rows

    def _load_peer_orders_from_source(self, unit: dict, target_orders: list[dict]) -> list[dict]:
        if unit["representative"].get("kind") == "mt5_deals":
            rows = self._load_mt5_peer_orders(unit, target_orders)
        else:
            rows = self._load_mt4_peer_orders(unit, target_orders)
        return self._resolve_peer_servers(unit, rows)

    def load_peer_accounts(self, account: str, context: dict, event: dict) -> dict:
        target_orders = [dict(row) for row in event.get("heavyOrders") or []]
        closed_targets = [row for row in target_orders if parse_datetime(row.get("openTime")) and parse_datetime(row.get("closeTime"))]
        skipped = [
            {"orderId": str(row.get("orderId") or ""), "reason": "目标订单没有完整平仓时间，不能验证同步平仓"}
            for row in target_orders if row not in closed_targets
        ]
        units = self._peer_source_units()
        coverage = {
            "scope": "AC/DBG 全平台 MT4 + MT5", "toleranceSeconds": 5,
            "oppositeLotSimilarityThreshold": 0.8,
            "physicalSourceTotal": len(units), "scannedSourceCount": 0, "failedSourceCount": 0,
            "scannedSources": [], "failures": [], "targetOrderCount": len(target_orders),
            "checkedTargetOrderCount": len(closed_targets), "skippedTargetOrders": skipped,
            "status": "数据不足" if not closed_targets else "完成",
        }
        evidence = {
            "eventStart": event.get("start"), "eventEnd": event.get("end"),
            "sameDirectionAccounts": [], "oppositeDirectionAccounts": [], "peerAccounts": [],
            "sameDirectionMatches": [], "oppositeDirectionMatches": [], "peerSearchCoverage": coverage,
            "sameDirectionMatchTotal": 0, "oppositeDirectionMatchTotal": 0,
            "oppositeLotSimilarityThreshold": 0.8,
            "peerMatchDetailLimit": 500, "peerMatchesTruncated": False,
        }
        if not closed_targets:
            return evidence
        target_key = _source_key(context.get("source") or {})
        peer_orders = []
        with ThreadPoolExecutor(max_workers=min(4, len(units)), thread_name_prefix="position-peer") as executor:
            futures = {executor.submit(self._load_peer_orders_from_source, unit, closed_targets): unit for unit in units}
            for future in as_completed(futures):
                unit = futures[future]
                metadata = self._peer_source_metadata(unit)
                try:
                    rows = future.result()
                    if unit["key"] == target_key:
                        rows = [row for row in rows if str(row.get("account")) != str(account)]
                    peer_orders.extend(rows)
                    coverage["scannedSourceCount"] += 1
                    coverage["scannedSources"].append({key: metadata[key] for key in ("platform", "server", "database")})
                except Exception as exc:
                    coverage["failures"].append({
                        **{key: metadata[key] for key in ("platform", "server", "database")}, "reason": str(exc),
                    })
        coverage["failedSourceCount"] = len(coverage["failures"])
        if coverage["failedSourceCount"]:
            coverage["status"] = "部分失败"
        elif skipped:
            coverage["status"] = "数据不足"
        evidence.update(match_synchronized_peer_orders(closed_targets, peer_orders, tolerance_seconds=5))
        return evidence
