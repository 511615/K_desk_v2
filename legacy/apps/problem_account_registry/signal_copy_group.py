from __future__ import annotations

import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any


SIGNAL_IN_COMMENT_RE = re.compile(r"(?i)\bSignal\s*#\s*([A-Z0-9_-]+)\s+IN\b")


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


def _rounded(value: object, digits: int = 2) -> float:
    return round(_number(value), digits)


def _batches(values: list[int], size: int = 300):
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


def signal_in_identifier(value: object) -> str:
    match = SIGNAL_IN_COMMENT_RE.search(_text(value))
    return match.group(1) if match else ""


def signal_in_tag(value: object) -> str:
    signal_id = signal_in_identifier(value)
    return f"Signal #{signal_id} IN" if signal_id else ""


def signal_group_totals(rows: list[dict]) -> dict:
    combined = _rounded(sum(_number(row.get("combinedNetProfit")) for row in rows))
    rebate = _rounded(sum(_number(row.get("rebate")) for row in rows))
    closed_lots = _rounded(sum(_number(row.get("closedLots")) for row in rows), 4)
    statuses: dict[str, int] = {}
    for row in rows:
        status = _text(row.get("status")) or "未填"
        statuses[status] = statuses.get(status, 0) + 1
    client_loss = max(-combined, 0.0)
    return {
        "accounts": len(rows),
        "profitableAccounts": sum(1 for row in rows if _number(row.get("combinedNetProfit")) > 0),
        "losingAccounts": sum(1 for row in rows if _number(row.get("combinedNetProfit")) < 0),
        "flatAccounts": sum(1 for row in rows if _number(row.get("combinedNetProfit")) == 0),
        "statusCounts": statuses,
        "closedOrders": sum(_integer(row.get("closedOrders")) for row in rows),
        "openOrders": sum(_integer(row.get("openOrders")) for row in rows),
        "closedLots": closed_lots,
        "closedNetProfit": _rounded(sum(_number(row.get("closedNetProfit")) for row in rows)),
        "floatingNetProfit": _rounded(sum(_number(row.get("floatingNetProfit")) for row in rows)),
        "combinedNetProfit": combined,
        "rebate": rebate,
        "rebatePerLot": _rounded(rebate / closed_lots, 2) if closed_lots else None,
        "rebateShareOfClientLoss": _rounded(rebate / client_loss, 4) if client_loss else None,
        "estimatedPlatformAfterRebate": _rounded(-combined - rebate),
    }


class SignalCopyGroupService:
    """Read-only Signal copy-group lookup and profit aggregation.

    The runtime object is the host application module. Dependencies are resolved
    at call time so the service remains isolated from the monolithic HTTP app and
    can reuse its database connection, money scaling and MT5 deal conversion.
    """

    def __init__(self, runtime: Any):
        self.runtime = runtime

    def _user_view_config(self, source: dict) -> dict[str, str]:
        if source.get("kind") == "mt5_deals":
            return {
                "table": "mt5_users_view", "login": "Login", "comment": "Comment",
                "status": "Status", "group": "Group", "currency": "",
            }
        return {
            "table": "mt4_users_view", "login": "LOGIN", "comment": "COMMENT",
            "status": "STATUS", "group": "GROUP", "currency": "CURRENCY",
        }

    def _member_money_meta(self, source: dict, row: dict) -> dict:
        r = self.runtime
        currency = r.normalize_text(row.get("currency")).upper()
        group = r.normalize_text(row.get("group"))
        if not currency and re.search(r"(?i)(?:cent|usc)", group):
            currency = "USC"
        return r.account_money_meta(currency, group, source.get("name"))

    def query_seed(self, source: dict, login: str) -> dict | None:
        r = self.runtime
        config = self._user_view_config(source)
        currency_select = f", `{config['currency']}` as AccountCurrency" if config["currency"] else ""
        sql = f"""
            select `{config['login']}` as Login, `{config['comment']}` as UserComment,
                   `{config['status']}` as UserStatus, `{config['group']}` as AccountGroup
                   {currency_select}
            from `{source['schema']}`.`{config['table']}`
            where `{config['login']}` = %s
            limit 1
        """
        with r.mysql_trade_connect(source) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (int(login),))
                row = cur.fetchone() or {}
        if not row:
            return None
        signal_id = signal_in_identifier(row.get("UserComment"))
        if not signal_id:
            return None
        return {
            "account": r.normalize_text(row.get("Login")),
            "signalId": signal_id,
            "signalTag": f"Signal #{signal_id} IN",
            "status": r.normalize_text(row.get("UserStatus")),
            "group": r.normalize_text(row.get("AccountGroup")),
            "currency": r.normalize_text(row.get("AccountCurrency")).upper(),
            "platform": r.normalize_text(source.get("platform")),
            "server": r.normalize_text(source.get("server") or source.get("name")),
        }

    def query_members(self, source: dict, signal_id: str, limit: int = 5000) -> tuple[list[dict], bool]:
        r = self.runtime
        signal_id = r.normalize_text(signal_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", signal_id):
            return [], False
        config = self._user_view_config(source)
        currency_select = f", `{config['currency']}` as AccountCurrency" if config["currency"] else ""
        sql = f"""
            select `{config['login']}` as Login, `{config['comment']}` as UserComment,
                   `{config['status']}` as UserStatus, `{config['group']}` as AccountGroup
                   {currency_select}
            from `{source['schema']}`.`{config['table']}`
            where `{config['comment']}` like %s
            limit %s
        """
        with r.mysql_trade_connect(source) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (f"%{signal_id}%", limit + 1))
                raw_rows = cur.fetchall()
        truncated = len(raw_rows) > limit
        members = []
        for row in raw_rows[:limit]:
            matched_id = signal_in_identifier(row.get("UserComment"))
            if not matched_id or matched_id.lower() != signal_id.lower():
                continue
            login = r.normalize_text(row.get("Login"))
            if not login.isdigit():
                continue
            members.append({
                "account": login,
                "status": r.normalize_text(row.get("UserStatus")),
                "group": r.normalize_text(row.get("AccountGroup")),
                "currency": r.normalize_text(row.get("AccountCurrency")).upper(),
            })
        members.sort(key=lambda row: int(row["account"]))
        return members, truncated

    def query_rebates(self, source: dict, logins: list[int]) -> tuple[dict[str, float], str]:
        r = self.runtime
        crm_schema = r.normalize_text(source.get("crm_schema"))
        mt_server_code = r.normalize_text(source.get("mt_server_code"))
        if not crm_schema or not mt_server_code or not logins:
            return {}, "当前服务器未配置 CRM 返佣数据源"
        rebates: dict[str, float] = defaultdict(float)
        try:
            with r.mysql_trade_connect(source) as conn:
                with conn.cursor() as cur:
                    for batch in _batches(logins):
                        placeholders = ",".join(["%s"] * len(batch))
                        cur.execute(
                            f"""
                                select trade_mt_login as Login, sum(rebate_amount) as Rebate
                                from `{crm_schema}`.`rebate_task_detail`
                                where mt_server_code = %s and trade_mt_login in ({placeholders})
                                group by trade_mt_login
                            """,
                            [mt_server_code, *batch],
                        )
                        for row in cur.fetchall():
                            rebates[r.normalize_text(row.get("Login"))] += r.numeric_value(row.get("Rebate"))
        except Exception as exc:
            return {}, f"返佣查询失败：{exc}"
        return dict(rebates), ""

    def query_mt4_stats(self, source: dict, members: list[dict]) -> tuple[list[dict], list[str]]:
        r = self.runtime
        member_map = {row["account"]: row for row in members}
        logins = [int(account) for account in member_map]
        raw_stats: dict[str, dict] = {}
        with r.mysql_trade_connect(source) as conn:
            with conn.cursor() as cur:
                for batch in _batches(logins):
                    placeholders = ",".join(["%s"] * len(batch))
                    cur.execute(
                        f"""
                            select LOGIN,
                                   sum(case when CMD in (0,1) and CLOSE_TIME > '1971-01-02' then 1 else 0 end) as ClosedOrders,
                                   sum(case when CMD in (0,1) and CLOSE_TIME <= '1971-01-02' then 1 else 0 end) as OpenOrders,
                                   sum(case when CMD in (0,1) and CLOSE_TIME > '1971-01-02' then VOLUME else 0 end) / 100 as ClosedLots,
                                   sum(case when CMD in (0,1) and CLOSE_TIME > '1971-01-02'
                                            then coalesce(PROFIT,0)+coalesce(COMMISSION,0)+coalesce(SWAPS,0)+coalesce(TAXES,0)
                                            else 0 end) as ClosedNetProfit,
                                   sum(case when CMD in (0,1) and CLOSE_TIME <= '1971-01-02'
                                            then coalesce(PROFIT,0)+coalesce(COMMISSION,0)+coalesce(SWAPS,0)+coalesce(TAXES,0)
                                            else 0 end) as FloatingNetProfit,
                                   min(case when CMD in (0,1) and CLOSE_TIME > '1971-01-02' then CLOSE_TIME end) as FirstClose,
                                   max(case when CMD in (0,1) and CLOSE_TIME > '1971-01-02' then CLOSE_TIME end) as LastClose
                            from `{source['schema']}`.`{source['table']}`
                            where LOGIN in ({placeholders}) and CMD in (0,1)
                            group by LOGIN
                        """,
                        batch,
                    )
                    for row in cur.fetchall():
                        raw_stats[r.normalize_text(row.get("LOGIN"))] = row
        rebates, rebate_error = self.query_rebates(source, logins)
        limitations = [rebate_error] if rebate_error else []
        results = []
        for login, member in member_map.items():
            row = raw_stats.get(login, {})
            meta = self._member_money_meta(source, member)
            money_scale = r.numeric_value(meta.get("moneyScale")) or 1.0
            closed_net = r.numeric_value(row.get("ClosedNetProfit")) * money_scale
            floating_net = r.numeric_value(row.get("FloatingNetProfit")) * money_scale
            results.append({
                "account": login,
                "status": member.get("status", ""),
                "currency": meta.get("displayCurrency") or meta.get("currency") or "",
                "isCentAccount": bool(meta.get("isCentAccount")),
                "closedOrders": r.mysql_int(row.get("ClosedOrders")),
                "openOrders": r.mysql_int(row.get("OpenOrders")),
                "closedLots": r.rounded(r.numeric_value(row.get("ClosedLots")), 4),
                "closedNetProfit": r.rounded(closed_net),
                "floatingNetProfit": r.rounded(floating_net),
                "combinedNetProfit": r.rounded(closed_net + floating_net),
                "rebate": r.rounded(rebates.get(login, 0.0)),
                "firstClose": r.mysql_datetime_text(row.get("FirstClose")),
                "lastClose": r.mysql_datetime_text(row.get("LastClose")),
            })
        return results, limitations

    def query_mt5_stats(self, source: dict, members: list[dict]) -> tuple[list[dict], list[str]]:
        r = self.runtime
        member_map = {row["account"]: row for row in members}
        logins = [int(account) for account in member_map]
        deals_by_login: dict[str, list[dict]] = defaultdict(list)
        positions: dict[str, dict] = {}
        limitations: list[str] = []
        with r.mysql_trade_connect(source) as conn:
            with conn.cursor() as cur:
                for batch in _batches(logins, 100):
                    placeholders = ",".join(["%s"] * len(batch))
                    cur.execute(
                        f"""
                            select Deal, Login, `Order`, PositionID, Action, Entry, Reason, Time, TimeMsc,
                                   Symbol, Price, Volume, VolumeExt, VolumeClosed, VolumeClosedExt,
                                   Profit, Commission, Storage, Fee, Comment, ExpertID, PriceSL, PriceTP,
                                   ContractSize, TickValue, TickSize, MarketBid, MarketAsk, PriceGateway
                            from `{source['schema']}`.`{source['table']}`
                            where Login in ({placeholders}) and Action in (0,1) and Entry in (0,1)
                            order by Login, PositionID, Time, Deal
                        """,
                        batch,
                    )
                    for row in cur.fetchall():
                        deals_by_login[r.normalize_text(row.get("Login"))].append(row)
                try:
                    for batch in _batches(logins):
                        placeholders = ",".join(["%s"] * len(batch))
                        cur.execute(
                            f"""
                                select Login, count(*) as OpenOrders,
                                       sum(coalesce(Profit,0)+coalesce(Storage,0)) as FloatingNetProfit
                                from `{source['schema']}`.`mt5_positions`
                                where Login in ({placeholders})
                                group by Login
                            """,
                            batch,
                        )
                        for row in cur.fetchall():
                            positions[r.normalize_text(row.get("Login"))] = row
                except Exception as exc:
                    limitations.append(f"MT5 当前持仓盈亏未取到：{exc}")
        rebates, rebate_error = self.query_rebates(source, logins)
        if rebate_error:
            limitations.append(rebate_error)
        results = []
        for login, member in member_map.items():
            meta = self._member_money_meta(source, member)
            trades = r.mt5_deals_to_trades(deals_by_login.get(login, []), source, login, meta)
            close_times = [r.parse_trade_time(row.get("close_time")) for row in trades]
            close_times = [value for value in close_times if value]
            closed_net = sum(r.toxic_trade_net(row) for row in trades)
            position = positions.get(login, {})
            money_scale = r.numeric_value(meta.get("moneyScale")) or 1.0
            floating_net = r.numeric_value(position.get("FloatingNetProfit")) * money_scale
            results.append({
                "account": login,
                "status": member.get("status", ""),
                "currency": meta.get("displayCurrency") or meta.get("currency") or "",
                "isCentAccount": bool(meta.get("isCentAccount")),
                "closedOrders": len(trades),
                "openOrders": r.mysql_int(position.get("OpenOrders")),
                "closedLots": r.rounded(sum(r.numeric_value(row.get("volume")) for row in trades), 4),
                "closedNetProfit": r.rounded(closed_net),
                "floatingNetProfit": r.rounded(floating_net),
                "combinedNetProfit": r.rounded(closed_net + floating_net),
                "rebate": r.rounded(rebates.get(login, 0.0)),
                "firstClose": min(close_times).strftime("%Y-%m-%d %H:%M:%S") if close_times else "",
                "lastClose": max(close_times).strftime("%Y-%m-%d %H:%M:%S") if close_times else "",
            })
        return results, limitations

    def query_group_for_source(self, source: dict, login: str) -> dict | None:
        r = self.runtime
        seed = self.query_seed(source, login)
        if not seed:
            return None
        members, truncated = self.query_members(source, seed["signalId"])
        if not members:
            return {
                **seed, "members": [], "totals": signal_group_totals([]),
                "truncated": truncated, "limitations": ["识别到 Signal 标识，但未找到同组账户"],
            }
        if source.get("kind") == "mt5_deals":
            rows, limitations = self.query_mt5_stats(source, members)
        else:
            rows, limitations = self.query_mt4_stats(source, members)
        rows.sort(key=lambda row: (-r.numeric_value(row.get("combinedNetProfit")), int(row.get("account") or 0)))
        return {
            **seed,
            "members": rows,
            "totals": signal_group_totals(rows),
            "truncated": truncated,
            "limitations": limitations,
        }

    def payload(self, login: str, filters: dict | None = None) -> dict:
        r = self.runtime
        filters = filters or {}
        login = r.normalize_text(login)
        if not login or not re.fullmatch(r"\d+", login):
            raise ValueError("账号格式无效")
        platform = r.normalize_text(filters.get("platform")).upper()
        server = r.normalize_text(filters.get("server"))
        sources = [source for source in r.MYSQL_SOURCES if r.source_allowed(source, platform=platform, server=server)]
        groups: list[dict] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=min(4, len(sources) or 1), thread_name_prefix="copy-group") as executor:
            futures = {executor.submit(self.query_group_for_source, source, login): source for source in sources}
            for future in as_completed(futures):
                source = futures[future]
                try:
                    group = future.result()
                    if group:
                        groups.append(group)
                except Exception as exc:
                    errors.append(f"{source.get('name')}: {exc}")
        source_order = {r.normalize_text(source.get("name")): index for index, source in enumerate(r.MYSQL_SOURCES)}
        groups.sort(key=lambda group: source_order.get(r.normalize_text(group.get("server")), len(source_order)))
        return {
            "ok": True,
            "account": login,
            "detected": bool(groups),
            "groups": groups,
            "errors": errors[:8],
            "privacy": "仅返回账号、Signal 标识、状态和交易汇总；不返回 users.comment 原文或个人资料。",
            "definition": "同一服务器 users.comment 中匹配相同 Signal #… IN 的账户视为同一跟单组；交易净盈亏包含手续费、利息和税费，返佣单独列示。",
            "refreshedAt": r.now_text(),
        }
