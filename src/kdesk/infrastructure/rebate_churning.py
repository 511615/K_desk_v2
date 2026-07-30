from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from kdesk.domain.rebate_churning import integer, number, parse_datetime
from kdesk.infrastructure.legacy_bridge import LegacyBridge

ENVIRONMENT_SCHEMAS = {
    "gb": ("AC GB", "int_sass_crm_ac"),
    "cn": ("AC CN", "sass_crm_ac"),
    "dbg_cn": ("DBG CN", "crm_cn"),
    "dbg_vn": ("DBG VN", "crm_vn"),
}


def _batches(values, size: int = 50):
    values = list(values)
    for index in range(0, len(values), size):
        yield values[index:index + size]


class LegacyRebateRepository:
    """Read-only indexed rebate queries behind the governed legacy bridge."""

    def __init__(self, bridge: LegacyBridge):
        self.module = bridge.module()
        self.service = self.module.REBATE_CHURNING_SERVICE

    def _source(self, environment: str) -> dict:
        return self.service._environment_source(environment)

    def discover_active_ibs(self, environment: str, start: str, end: str) -> set[int]:
        source = self._source(environment)
        schema = ENVIRONMENT_SCHEMAS[environment][1]
        start_dt, end_dt = parse_datetime(start), parse_datetime(end)
        if not start_dt or not end_dt:
            raise ValueError("日期格式无效")
        found: set[int] = set()
        shard_start = start_dt
        while shard_start < end_dt:
            shard_end = min(shard_start + timedelta(days=1), end_dt)
            try:
                found.update(self._query_active_ibs(source, schema, shard_start, shard_end))
            except Exception:
                cursor = shard_start
                while cursor < shard_end:
                    six_end = min(cursor + timedelta(hours=6), shard_end)
                    found.update(self._query_active_ibs(source, schema, cursor, six_end))
                    cursor = six_end
            shard_start = shard_end
        return found

    def _query_active_ibs(self, source: dict, schema: str, start: datetime, end: datetime) -> set[int]:
        with self.service.connect(source) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"select distinct rebate_ib_id from `{schema}`.`rebate_task_detail` force index (idx_covering) where rebate_ib_id is not null and create_time >= %s and create_time < %s",
                    (start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")),
                )
                return {integer(row.get("rebate_ib_id")) for row in cursor.fetchall() if integer(row.get("rebate_ib_id"))}

    def load_rebate_rows(self, environment: str, ib_ids: set[int], start: str, end: str) -> list[dict]:
        source = self._source(environment)
        schema = ENVIRONMENT_SCHEMAS[environment][1]
        deduplicated = {}
        with self.service.connect(source) as connection:
            with connection.cursor() as cursor:
                for batch in _batches(sorted(ib_ids)):
                    placeholders = ",".join(["%s"] * len(batch))
                    cursor.execute(
                        f"""
                        select rebate_ib_id,trade_user_id,trade_mt_login,mt_server_code,
                               trade_mt_ticket,trade_mt_deal,rebate_amount,create_time,
                               mt_symbol,mt_volume,mt_open_time,mt_close_time,usd_or_usc,rebate_type
                        from `{schema}`.`rebate_task_detail` force index (idx_covering)
                        where rebate_ib_id in ({placeholders}) and create_time >= %s and create_time < %s
                        order by rebate_ib_id,create_time
                        """,
                        [*batch, start, end],
                    )
                    for row in cursor.fetchall():
                        deal = str(row.get("trade_mt_deal") or "").strip()
                        ticket = str(row.get("trade_mt_ticket") or "").strip()
                        identity = deal if deal not in {"", "0"} else ticket
                        key = (
                            integer(row.get("rebate_ib_id")), str(row.get("mt_server_code") or ""),
                            integer(row.get("trade_mt_login")), identity or str(row.get("create_time") or ""),
                        )
                        current = deduplicated.get(key)
                        if current is None:
                            deduplicated[key] = dict(row)
                        else:
                            current["rebate_amount"] = number(current.get("rebate_amount")) + number(row.get("rebate_amount"))
        return list(deduplicated.values())

    def proxy_accounts(self, environment: str, rows: list[dict]) -> list[dict]:
        keys = {(str(row.get("mt_server_code") or ""), integer(row.get("trade_mt_login"))) for row in rows}
        mappings = self.service._account_mappings(environment, keys)
        grouped = defaultdict(list)
        for row in rows:
            grouped[(integer(row.get("rebate_ib_id")), str(row.get("mt_server_code") or ""), integer(row.get("trade_mt_login")))].append(row)
        output = []
        for (ib_id, server_code, account), account_rows in grouped.items():
            mapping = mappings.get((server_code, account), {})
            volume_scale = self.module.rebate_churning._money_scale(mapping, account_rows)
            lots = sum(max(number(row.get("mt_volume")), 0) * volume_scale for row in account_rows)
            rebate = sum(number(row.get("rebate_amount")) for row in account_rows)
            holds = []
            signatures = []
            volumes = Counter()
            days = set()
            for row in account_rows:
                opened, closed = parse_datetime(row.get("mt_open_time")), parse_datetime(row.get("mt_close_time"))
                if opened:
                    days.add(opened.date())
                if opened and closed:
                    normalized_volume = max(number(row.get("mt_volume")), 0) * volume_scale
                    holds.append(((closed - opened).total_seconds(), normalized_volume))
                    signatures.append((server_code, str(row.get("mt_symbol") or "").upper(), int(opened.timestamp()), int(closed.timestamp()), round(normalized_volume, 4)))
                volumes[round(number(row.get("mt_volume")) * volume_scale, 4)] += 1
            short_lots = sum(volume for seconds, volume in holds if seconds <= 10)
            repeated = sum(count for count in Counter(signatures).values() if count >= 2)
            orders = len(account_rows)
            output.append({
                "ibId": ib_id, "serverCode": server_code, "account": account,
                "userId": integer(mapping.get("user_id")), "isCent": "USC" in str(mapping.get("mt_type_name") or "").upper() or "CENT" in str(mapping.get("mt_type_name") or "").upper(),
                "orders": orders, "activeDays": max(len(days), 1), "ordersPerActiveDay": orders / max(len(days), 1),
                "lots": lots, "currentIbRebate": rebate, "rebatePerLot": rebate / lots if lots else 0,
                "short10Coverage": short_lots / lots if lots else 0, "fixedLotCoverage": max(volumes.values(), default=0) / orders if orders else 0,
                "repeatCoverage": repeated / orders if orders else 0, "signatures": signatures,
            })
        return output

    def _exact_trades(self, environment: str, mappings: dict, rebates: dict) -> dict:
        crm_schema = ENVIRONMENT_SCHEMAS[environment][1]
        grouped = defaultdict(list)
        for key in mappings:
            source = self.module.rebate_churning._source_for(self.service.sources, crm_schema, key[0])
            if source:
                grouped[source.get("name")].append((key, source))
        output = defaultdict(list)
        for source_rows in grouped.values():
            source = source_rows[0][1]
            scale_by_login = {
                key[1]: self.module.rebate_churning._money_scale(mappings.get(key, {}), rebates.get(key))
                for key, _ in source_rows
            }
            raw_rows = []
            if source.get("kind") == "mt5_deals":
                deal_ids = {
                    integer(row.get("trade_mt_deal"))
                    for key, _ in source_rows for row in rebates.get(key, [])
                    if integer(row.get("trade_mt_deal"))
                }
                order_ids = {
                    integer(row.get("trade_mt_ticket"))
                    for key, _ in source_rows for row in rebates.get(key, [])
                    if integer(row.get("trade_mt_ticket"))
                }
                position_ids = set()
                with self.service.connect(source) as connection:
                    with connection.cursor() as cursor:
                        for batch in _batches(sorted(deal_ids), 100):
                            placeholders = ",".join(["%s"] * len(batch))
                            cursor.execute(
                                f"select Deal,Login,`Order`,PositionID,Action,Entry,Reason,Time,TimeMsc,Symbol,Volume,VolumeClosed,Profit,Commission,Storage,Fee,Comment,ExpertID from `{source['schema']}`.`{source['table']}` where Deal in ({placeholders})",
                                batch,
                            )
                            located = cursor.fetchall()
                            raw_rows.extend(located)
                            position_ids.update(integer(row.get("PositionID")) for row in located if integer(row.get("PositionID")))
                        for batch in _batches(sorted(order_ids), 100):
                            placeholders = ",".join(["%s"] * len(batch))
                            cursor.execute(
                                f"select Deal,Login,`Order`,PositionID,Action,Entry,Reason,Time,TimeMsc,Symbol,Volume,VolumeClosed,Profit,Commission,Storage,Fee,Comment,ExpertID from `{source['schema']}`.`{source['table']}` where `Order` in ({placeholders})",
                                batch,
                            )
                            located = cursor.fetchall()
                            raw_rows.extend(located)
                            position_ids.update(integer(row.get("PositionID")) for row in located if integer(row.get("PositionID")))
                        for batch in _batches(sorted(position_ids), 100):
                            placeholders = ",".join(["%s"] * len(batch))
                            cursor.execute(
                                f"select Deal,Login,`Order`,PositionID,Action,Entry,Reason,Time,TimeMsc,Symbol,Volume,VolumeClosed,Profit,Commission,Storage,Fee,Comment,ExpertID from `{source['schema']}`.`{source['table']}` where PositionID in ({placeholders}) order by Login,PositionID,Time,Deal",
                                batch,
                            )
                            raw_rows.extend(cursor.fetchall())
                unique_rows = {integer(row.get("Deal")): row for row in raw_rows if integer(row.get("Deal"))}
                converted = self.module.rebate_churning._mt5_rows_to_trades(list(unique_rows.values()), scale_by_login, source)
            else:
                ticket_ids = {
                    integer(row.get("trade_mt_ticket"))
                    for key, _ in source_rows for row in rebates.get(key, [])
                    if integer(row.get("trade_mt_ticket"))
                }
                with self.service.connect(source) as connection:
                    with connection.cursor() as cursor:
                        for batch in _batches(sorted(ticket_ids), 100):
                            placeholders = ",".join(["%s"] * len(batch))
                            cursor.execute(
                                f"select TICKET,LOGIN,CMD,SYMBOL,VOLUME,OPEN_TIME,CLOSE_TIME,COMMISSION,SWAPS,PROFIT,TAXES,REASON,MAGIC,COMMENT from `{source['schema']}`.`{source['table']}` where TICKET in ({placeholders}) and CMD in (0,1) order by LOGIN,OPEN_TIME,TICKET",
                                batch,
                            )
                            raw_rows.extend(cursor.fetchall())
                unique_rows = {integer(row.get("TICKET")): row for row in raw_rows if integer(row.get("TICKET"))}
                converted = self.module.rebate_churning._mt4_rows_to_trades(list(unique_rows.values()), scale_by_login, source)
            for key, _ in source_rows:
                output[key] = converted.get(key[1], [])
        return output

    def load_deep_accounts(self, environment: str, ib_id: int, keys: set[tuple[str, int]], rows: list[dict], start: str, end: str) -> list[dict]:
        if not keys:
            return []
        mappings = self.service._account_mappings(environment, keys)
        rebates = defaultdict(list)
        for row in rows:
            key = (str(row.get("mt_server_code") or ""), integer(row.get("trade_mt_login")))
            if key in keys and integer(row.get("rebate_ib_id")) == ib_id:
                rebates[key].append(row)
        timestamps = [parse_datetime(row.get(field)) for values in rebates.values() for row in values for field in ("mt_open_time", "mt_close_time")]
        timestamps = [value for value in timestamps if value]
        query_start = max(min(timestamps, default=parse_datetime(start)), parse_datetime(end) - timedelta(days=31))
        query_end = min(max(timestamps, default=parse_datetime(end)) + timedelta(seconds=1), parse_datetime(end) + timedelta(days=1))
        trades = self._exact_trades(environment, mappings, rebates)
        cash_period = {
            "startText": (query_start - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),
            "endText": (query_end + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S"),
        }
        cashflows = self.service._cashflow_metrics(environment, mappings, rebates, trades, cash_period)
        features = []
        for key in keys:
            mapping = mappings.get(key, {})
            account_trades = trades.get(key, [])
            feature = self.module.rebate_churning.account_features(account_trades)
            feature.update(cashflows.get(key, {}))
            details = rebates.get(key, [])
            rebate = sum(number(row.get("rebate_amount")) for row in details)
            trade_keys = set(feature.get("tradeKeys") or []) | set(feature.get("ticketKeys") or [])
            matched = {str(row.get("trade_mt_deal") or row.get("trade_mt_ticket") or "") for row in details if str(row.get("trade_mt_deal") or row.get("trade_mt_ticket") or "") in trade_keys}
            source = self.module.rebate_churning._source_for(self.service.sources, ENVIRONMENT_SCHEMAS[environment][1], key[0]) or {}
            feature.update({
                "account": key[1], "serverCode": key[0], "userId": integer(mapping.get("user_id")),
                "ownerName": self.module.rebate_churning._full_name(mapping), "typeName": str(mapping.get("mt_type_name") or ""),
                "platform": source.get("platform", ""), "server": source.get("server", ""),
                "currentIbRebate": round(rebate, 5), "currentIbRebateRows": len(details), "matchedRebateOrders": len(matched),
                "hierarchyRebate": round(rebate, 5), "_trades": account_trades,
            })
            features.append(feature)
        return features

    def ib_names(self, environment: str, ib_ids: set[int]) -> dict[int, dict]:
        return self.service._ib_names(environment, ib_ids)

    def ib_display_name(self, row: dict) -> str:
        return self.module.rebate_churning._full_name(row)

    def ib_detail(self, environment: str, ib_id: int, start: str, end: str) -> dict:
        return self.service.ib_detail(environment, ib_id, start, end)
