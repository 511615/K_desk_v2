from __future__ import annotations

import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

_IGNORED_COMMENTS = {
    "auto",
    "auto trade",
    "autotrade",
    "ea",
    "expert",
    "manual",
    "mobile",
    "robot",
    "sl",
    "so",
    "tp",
    "web",
}


def _text(value: object) -> str:
    return str(value or "").strip()


def _number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _integer(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _batches(values: list[int], size: int = 300):
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


def ea_comment_parts(value: object) -> list[str]:
    """Return exact, useful EA comment values from a normalized trade comment."""

    values = []
    for part in _text(value).split(" / "):
        comment = re.sub(r"(?i)\s*(?:\[(?:s/?l|t/?p|so)\])+$", "", part).strip()
        normalized = comment.casefold()
        if len(comment) < 3 or len(comment) > 255 or normalized in _IGNORED_COMMENTS:
            continue
        if re.fullmatch(r"(?i)[\[\(< ]*(?:s/?l|t/?p|stop\s*out)[\]\)> ]*", comment):
            continue
        if re.search(r"(?i)CPT-[A-Z0-9]+#\d+", comment) or re.search(r"(?i)\bSignal\s*#.+\s+IN\b", comment):
            continue
        if re.fullmatch(r"(?i)(?:from|copy|copied)\s*#?\s*\d+", comment):
            continue
        if not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", comment):
            continue
        if normalized not in {item.casefold() for item in values}:
            values.append(comment)
    return values


def ea_comment_query_values(comments: list[str]) -> list[str]:
    values = []
    for comment in comments:
        for value in (comment, f"{comment}[tp]", f"{comment}[sl]", f"{comment}[so]"):
            if value.casefold() not in {item.casefold() for item in values}:
                values.append(value)
    return values


def ea_comment_totals(rows: list[dict]) -> dict:
    currencies = sorted({_text(row.get("currency")) for row in rows if _text(row.get("currency"))})
    return {
        "accounts": len(rows),
        "profitableAccounts": sum(1 for row in rows if _number(row.get("netProfit")) > 0),
        "losingAccounts": sum(1 for row in rows if _number(row.get("netProfit")) < 0),
        "flatAccounts": sum(1 for row in rows if _number(row.get("netProfit")) == 0),
        "orders": sum(_integer(row.get("orders")) for row in rows),
        "volume": round(sum(_number(row.get("volume")) for row in rows), 4),
        "grossProfit": round(sum(_number(row.get("grossProfit")) for row in rows), 2),
        "commission": round(sum(_number(row.get("commission")) for row in rows), 2),
        "swap": round(sum(_number(row.get("swap")) for row in rows), 2),
        "taxes": round(sum(_number(row.get("taxes")) for row in rows), 2),
        "netProfit": round(sum(_number(row.get("netProfit")) for row in rows), 2),
        "currency": currencies[0] if len(currencies) == 1 else "多币种" if currencies else "",
        "currencies": currencies,
    }


class EaCommentGroupService:
    """Read-only same-comment EA lookup and realized-profit aggregation."""

    def __init__(self, runtime: Any):
        self.runtime = runtime

    def _source_rows(self, rows: list[dict], source: dict) -> list[dict]:
        r = self.runtime
        platform = r.normalize_text(source.get("platform")).upper()
        server = r.normalize_text(source.get("server") or source.get("name"))
        return [
            row for row in rows
            if r.normalize_text(row.get("platform")).upper() == platform
            and r.normalize_text(row.get("server")) == server
        ]

    def _seed_comments(self, rows: list[dict], limit: int = 50) -> list[dict]:
        r = self.runtime
        grouped: dict[str, dict] = {}
        for row in rows:
            if not r.is_ea_trade(row) or r.is_copy_trade(row):
                continue
            for comment in ea_comment_parts(row.get("comment")):
                key = comment.casefold()
                item = grouped.setdefault(key, {
                    "comment": comment,
                    "currentOrders": 0,
                    "currentVolume": 0.0,
                    "currentNetProfit": 0.0,
                    "firstTime": "",
                    "lastTime": "",
                })
                item["currentOrders"] += 1
                item["currentVolume"] += r.numeric_value(row.get("volume"))
                item["currentNetProfit"] += (
                    r.numeric_value(row.get("profit"))
                    + r.numeric_value(row.get("commission"))
                    + r.numeric_value(row.get("fee"))
                    + r.numeric_value(row.get("swap"))
                    + r.numeric_value(row.get("taxes"))
                )
                opened = r.mysql_datetime_text(row.get("open_time"))
                closed = r.mysql_datetime_text(row.get("close_time")) or opened
                if opened:
                    item["firstTime"] = min(filter(None, [item["firstTime"], opened]), default=opened)
                if closed:
                    item["lastTime"] = max(item["lastTime"], closed)
        seeds = list(grouped.values())
        for item in seeds:
            item["currentVolume"] = r.rounded(item["currentVolume"], 4)
            item["currentNetProfit"] = r.rounded(item["currentNetProfit"])
        seeds.sort(key=lambda item: (-item["currentOrders"], item["comment"].casefold()))
        return seeds[:limit]

    def _summarize_records(self, records: list[dict], current_account: str) -> list[dict]:
        r = self.runtime
        grouped: dict[tuple[str, str], dict] = {}
        for row in records:
            account = r.normalize_text(row.get("account"))
            comment = r.normalize_text(row.get("comment"))
            if not account or not comment:
                continue
            key = (comment.casefold(), account)
            item = grouped.setdefault(key, {
                "account": account,
                "comment": comment,
                "orders": 0,
                "volume": 0.0,
                "grossProfit": 0.0,
                "commission": 0.0,
                "swap": 0.0,
                "taxes": 0.0,
                "netProfit": 0.0,
                "currency": r.normalize_text(row.get("currency")),
                "isCentAccount": bool(row.get("isCentAccount")),
                "symbols": set(),
                "tickets": [],
                "firstTime": "",
                "lastTime": "",
            })
            item["orders"] += 1
            for field in ("volume", "grossProfit", "commission", "swap", "taxes", "netProfit"):
                item[field] += r.numeric_value(row.get(field))
            symbol = r.normalize_text(row.get("symbol"))
            if symbol:
                item["symbols"].add(symbol)
            ticket = r.normalize_text(row.get("ticket"))
            if ticket and len(item["tickets"]) < 12:
                item["tickets"].append(ticket)
            opened = r.mysql_datetime_text(row.get("openTime"))
            closed = r.mysql_datetime_text(row.get("closeTime")) or opened
            if opened:
                item["firstTime"] = min(filter(None, [item["firstTime"], opened]), default=opened)
            if closed:
                item["lastTime"] = max(item["lastTime"], closed)
        results = []
        for item in grouped.values():
            for field in ("volume", "grossProfit", "commission", "swap", "taxes", "netProfit"):
                item[field] = r.rounded(item[field], 4 if field == "volume" else 2)
            item["symbols"] = sorted(item["symbols"])
            item["isCurrentAccount"] = item["account"] == current_account
            results.append(item)
        results.sort(key=lambda item: (item["comment"].casefold(), not item["isCurrentAccount"], -item["orders"], item["account"]))
        return results

    def _query_mt4(self, source: dict, seeds: list[dict], row_limit: int) -> tuple[list[dict], bool, list[str]]:
        r = self.runtime
        comments = [item["comment"] for item in seeds]
        query_comments = ea_comment_query_values(comments)
        start = min((r.parse_trade_time(item.get("firstTime")) for item in seeds), default=None)
        end = max((r.parse_trade_time(item.get("lastTime")) for item in seeds), default=None)
        if not start or not end:
            return [], False, ["MT4 同备注查询缺少有效交易时间范围"]
        placeholders = ",".join(["%s"] * len(query_comments))
        sql = f"""
            select TICKET, LOGIN, SYMBOL, VOLUME, OPEN_TIME, CLOSE_TIME,
                   PROFIT, COMMISSION, SWAPS, TAXES, COMMENT
            from `{source['schema']}`.`{source['table']}`
            where OPEN_TIME >= %s and OPEN_TIME <= %s
              and CMD in (0,1) and COMMENT in ({placeholders})
            order by OPEN_TIME, TICKET
            limit %s
        """
        with r.mysql_trade_connect(source) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, [start, end, *query_comments, row_limit + 1])
                raw_rows = cur.fetchall()
                truncated = len(raw_rows) > row_limit
                raw_rows = raw_rows[:row_limit]
                accounts = {r.normalize_text(row.get("LOGIN")) for row in raw_rows}
                metadata = r._copy_follower_money_meta(cur, source, accounts)
        records = []
        for row in raw_rows:
            opened = r.parse_trade_time(row.get("OPEN_TIME"))
            closed = r.parse_trade_time(row.get("CLOSE_TIME"))
            if not opened or not closed or closed <= datetime(1971, 1, 2) or closed < opened:
                continue
            account = r.normalize_text(row.get("LOGIN"))
            meta = metadata.get(account) or r.account_money_meta(source_name=source.get("name"))
            scale = r.numeric_value(meta.get("moneyScale")) or 1.0
            gross = r.numeric_value(row.get("PROFIT")) * scale
            commission = r.numeric_value(row.get("COMMISSION")) * scale
            swap = r.numeric_value(row.get("SWAPS")) * scale
            taxes = r.numeric_value(row.get("TAXES")) * scale
            matched_comments = ea_comment_parts(row.get("COMMENT"))
            if not matched_comments:
                continue
            records.append({
                "account": account,
                "comment": matched_comments[0],
                "ticket": r.normalize_text(row.get("TICKET")),
                "symbol": r.normalize_text(row.get("SYMBOL")),
                "openTime": r.mysql_datetime_text(row.get("OPEN_TIME")),
                "closeTime": r.mysql_datetime_text(row.get("CLOSE_TIME")),
                "volume": r.rounded(r.normalize_mt4_volume(row.get("VOLUME")), 4),
                "grossProfit": r.rounded(gross),
                "commission": r.rounded(commission),
                "swap": r.rounded(swap),
                "taxes": r.rounded(taxes),
                "netProfit": r.rounded(gross + commission + swap + taxes),
                "currency": r.normalize_text(meta.get("displayCurrency") or meta.get("currency")),
                "isCentAccount": bool(meta.get("isCentAccount")),
            })
        limitations = [
            f"MT4 备注列无独立索引，结果按当前账号使用区间 {start:%Y-%m-%d %H:%M:%S} 至 {end:%Y-%m-%d %H:%M:%S} 查询"
        ]
        return records, truncated, limitations

    def _query_mt5(self, source: dict, seeds: list[dict], row_limit: int) -> tuple[list[dict], bool, list[str]]:
        r = self.runtime
        comments = [item["comment"] for item in seeds]
        query_comments = ea_comment_query_values(comments)
        placeholders = ",".join(["%s"] * len(query_comments))
        seed_sql = f"""
            select Deal, Login, PositionID, Comment
            from `{source['schema']}`.`{source['table']}`
            where Comment in ({placeholders}) and Action in (0,1) and Entry in (0,1) and PositionID <> 0
            order by Deal
            limit %s
        """
        positions: dict[tuple[str, str], set[str]] = defaultdict(set)
        deals_by_login: dict[str, list[dict]] = defaultdict(list)
        metadata: dict[str, dict] = {}
        with r.mysql_trade_connect(source) as conn:
            with conn.cursor() as cur:
                cur.execute(seed_sql, [*query_comments, row_limit + 1])
                seed_rows = cur.fetchall()
                truncated = len(seed_rows) > row_limit
                for row in seed_rows[:row_limit]:
                    key = (r.normalize_text(row.get("Login")), r.normalize_text(row.get("PositionID")))
                    matched_comments = ea_comment_parts(row.get("Comment"))
                    if key[0] and key[1] and matched_comments:
                        positions[key].add(matched_comments[0])
                position_ids = sorted({int(key[1]) for key in positions if key[1].isdigit()})
                for batch in _batches(position_ids):
                    position_placeholders = ",".join(["%s"] * len(batch))
                    cur.execute(
                        f"""
                            select Deal, Login, `Order`, PositionID, Action, Entry, Reason, Time, TimeMsc,
                                   Symbol, Price, Volume, VolumeExt, VolumeClosed, VolumeClosedExt,
                                   Profit, Commission, Storage, Fee, Comment, ExpertID, PriceSL, PriceTP,
                                   ContractSize, TickValue, TickSize, MarketBid, MarketAsk, PriceGateway
                            from `{source['schema']}`.`{source['table']}`
                            where PositionID in ({position_placeholders}) and Action in (0,1) and Entry in (0,1)
                            order by Login, PositionID, Time, Deal
                        """,
                        batch,
                    )
                    for row in cur.fetchall():
                        key = (r.normalize_text(row.get("Login")), r.normalize_text(row.get("PositionID")))
                        if key in positions:
                            deals_by_login[key[0]].append(row)
                metadata = r._copy_follower_money_meta(cur, source, set(deals_by_login))
        records = []
        for account, deals in deals_by_login.items():
            meta = metadata.get(account) or r.account_money_meta(source_name=source.get("name"))
            for trade in r.mt5_deals_to_trades(deals, source, account, meta):
                key = (account, r.normalize_text(trade.get("ticket")))
                matched_comments = positions.get(key, set())
                for comment in matched_comments:
                    gross = r.numeric_value(trade.get("profit"))
                    commission = r.numeric_value(trade.get("commission")) + r.numeric_value(trade.get("fee"))
                    swap = r.numeric_value(trade.get("swap"))
                    taxes = r.numeric_value(trade.get("taxes"))
                    records.append({
                        "account": account,
                        "comment": comment,
                        "ticket": r.normalize_text(trade.get("ticket")),
                        "symbol": r.normalize_text(trade.get("symbol")),
                        "openTime": r.mysql_datetime_text(trade.get("open_time")),
                        "closeTime": r.mysql_datetime_text(trade.get("close_time")),
                        "volume": r.rounded(r.numeric_value(trade.get("volume")), 4),
                        "grossProfit": r.rounded(gross),
                        "commission": r.rounded(commission),
                        "swap": r.rounded(swap),
                        "taxes": r.rounded(taxes),
                        "netProfit": r.rounded(gross + commission + swap + taxes),
                        "currency": r.normalize_text(meta.get("displayCurrency") or meta.get("currency")),
                        "isCentAccount": bool(meta.get("isCentAccount")),
                    })
        return records, truncated, []

    def query_source(self, source: dict, rows: list[dict], current_account: str, row_limit: int = 50000) -> list[dict]:
        r = self.runtime
        seeds = self._seed_comments(self._source_rows(rows, source))
        if not seeds:
            return []
        if source.get("kind") == "mt5_deals":
            records, truncated, limitations = self._query_mt5(source, seeds, row_limit)
        else:
            records, truncated, limitations = self._query_mt4(source, seeds, row_limit)
        members = self._summarize_records(records, current_account)
        by_comment: dict[str, list[dict]] = defaultdict(list)
        for member in members:
            by_comment[member["comment"].casefold()].append(member)
        groups = []
        for seed in seeds:
            group_members = by_comment.get(seed["comment"].casefold(), [])
            group = {
                **seed,
                "platform": r.normalize_text(source.get("platform")),
                "server": r.normalize_text(source.get("server") or source.get("name")),
                "members": group_members,
                "totals": ea_comment_totals(group_members),
                "truncated": truncated,
                "limitations": limitations,
            }
            if group["totals"]["accounts"] >= 2:
                groups.append(group)
        groups.sort(key=lambda group: (-group["totals"]["accounts"], -group["totals"]["orders"], group["comment"].casefold()))
        return groups[:20]

    def payload(self, login: str, filters: dict | None = None) -> dict:
        r = self.runtime
        filters = filters or {}
        login = r.normalize_text(login)
        if not login or not re.fullmatch(r"\d+", login):
            raise ValueError("账号格式无效")
        platform = r.normalize_text(filters.get("platform")).upper()
        server = r.normalize_text(filters.get("server"))
        rows = r.query_db_trades(login, platform=platform, server=server, limit=50000)
        sources = [source for source in r.MYSQL_SOURCES if r.source_allowed(source, platform=platform, server=server)]
        groups: list[dict] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=min(4, len(sources) or 1), thread_name_prefix="ea-comment") as executor:
            futures = {executor.submit(self.query_source, source, rows, login): source for source in sources}
            for future in as_completed(futures):
                source = futures[future]
                try:
                    groups.extend(future.result())
                except Exception as exc:
                    errors.append(f"{source.get('name')}: {exc}")
        source_order = {r.normalize_text(source.get("name")): index for index, source in enumerate(r.MYSQL_SOURCES)}
        groups.sort(key=lambda group: (
            source_order.get(r.normalize_text(group.get("server")), len(source_order)),
            -group["totals"]["accounts"],
            -group["totals"]["orders"],
            group["comment"].casefold(),
        ))
        return {
            "ok": True,
            "account": login,
            "detected": bool(groups),
            "groups": groups,
            "errors": errors[:8],
            "definition": "同一平台、同一服务器内，至少两个账户的已平仓交易使用相同 EA comment 时归为一组；MT4 系统追加的 [tp]/[sl]/[so] 会合并，净盈亏包含手续费、Fee、利息和税费。",
            "refreshedAt": r.now_text(),
        }
