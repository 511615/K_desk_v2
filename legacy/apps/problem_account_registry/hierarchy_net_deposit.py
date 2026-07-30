from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Callable, Iterable


MAX_USERS = 2500
MAX_ACCOUNTS = 5000
MAX_RANGE_DAYS = 366
CENT_PATTERN = re.compile(r"(?i)(?:cent|usc)")
PRODUCT_PATTERN = re.compile(r"[0-9A-Za-z._#-]{1,40}")
PROMOTION_PRODUCT = "@PROMOTION"
PROMOTION_NET_DEPOSIT_THRESHOLD = 60000.0
PROMOTION_LOTS_THRESHOLD = 600.0
CURRENCY_CODES = {
    "USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "SGD", "HKD",
    "CNH", "CNY", "NOK", "SEK", "DKK", "PLN", "ZAR", "TRY", "MXN", "THB",
}


class AmbiguousTargetError(ValueError):
    def __init__(self, message: str, candidates: list[dict]):
        super().__init__(message)
        self.candidates = candidates


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _number(value: object) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rounded(value: object) -> float:
    return round(_number(value), 2)


def _batches(values: Iterable[object], size: int = 250):
    values = list(values)
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def _parse_datetime(value: object, field: str, *, end_of_day: bool = False) -> datetime:
    text = _text(value)
    if not text:
        raise ValueError(f"请输入{field}")
    try:
        parsed = datetime.fromisoformat(text.replace("T", " "))
    except ValueError as exc:
        raise ValueError(f"{field}格式无效") from exc
    if end_of_day and len(text) == 10:
        parsed += timedelta(days=1)
        parsed -= timedelta(microseconds=1)
    return parsed.replace(tzinfo=None)


def _boolean(value: object) -> bool:
    return value is True or _text(value).lower() in {"1", "true", "yes", "on"}


def parse_query(
    target: object,
    start: object,
    end: object,
    product: object = "",
    activity_rules: object = False,
) -> dict:
    target_text = _text(target)
    if not target_text or len(target_text) > 100:
        raise ValueError("请输入有效的IB或客户标识")
    start_at = _parse_datetime(start, "开始时间")
    end_at = _parse_datetime(end, "结束时间", end_of_day=True)
    if end_at < start_at:
        raise ValueError("结束时间不能早于开始时间")
    if end_at - start_at > timedelta(days=MAX_RANGE_DAYS):
        raise ValueError(f"单次查询时间范围不能超过{MAX_RANGE_DAYS}天")
    activity_rules_enabled = _boolean(activity_rules)
    product_text = PROMOTION_PRODUCT if activity_rules_enabled else _text(product).upper()
    if product_text and product_text != PROMOTION_PRODUCT and not PRODUCT_PATTERN.fullmatch(product_text):
        raise ValueError("产品格式无效")
    return {
        "target": target_text,
        "start": start_at,
        "end": end_at,
        "product": product_text,
        "activityRules": activity_rules_enabled,
    }


def is_promotion_product(symbol: object) -> bool:
    text = re.sub(r"[^A-Z]", "", _text(symbol).upper())
    if text.startswith(("XAU", "XAG", "XPT", "XPD", "GOLD", "SILVER", "PLATINUM", "PALLADIUM", "GAU")):
        return True
    for offset in range(max(len(text) - 5, 1)):
        pair = text[offset : offset + 6]
        if len(pair) == 6 and pair[:3] in CURRENCY_CODES and pair[3:] in CURRENCY_CODES:
            return True
    return False


def _full_name(row: dict) -> str:
    full_name = _text(row.get("full_name"))
    if full_name:
        return " ".join(full_name.split())
    return " ".join(
        value
        for value in (_text(row.get("first_name")), _text(row.get("middle_name")), _text(row.get("last_name")))
        if value
    )


def _source_routes(source: dict) -> list[dict]:
    routes = []
    raw_routes = source.get("crm_routes")
    if isinstance(raw_routes, list):
        routes.extend(route for route in raw_routes if isinstance(route, dict))
    account_route = source.get("account_route")
    if isinstance(account_route, dict):
        routes.append(account_route)
    routes.append({
        "schema": source.get("crm_schema"),
        "mt_server_code": source.get("mt_server_code"),
    })

    result = []
    seen = set()
    for route in routes:
        schema = _text(route.get("schema") or route.get("crm_schema"))
        server_code = _text(route.get("mt_server_code") or route.get("server_code"))
        key = (schema, server_code)
        if not schema or not server_code or key in seen:
            continue
        seen.add(key)
        result.append({"schema": schema, "mt_server_code": server_code})
    return result


def _server_codes_for_schema(sources: list[dict], schema: str) -> list[str]:
    return sorted({
        route["mt_server_code"]
        for source in sources
        for route in _source_routes(source)
        if route["schema"] == schema
    })


def _crm_sources(sources: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for source in sources:
        for route in _source_routes(source):
            schema = route["schema"]
            key = (_text(source.get("host")), schema)
            if key in seen:
                continue
            seen.add(key)
            result.append({**source, "crm_schema": schema})
    return result


def _target_mode(raw_target: str) -> tuple[str, str, str]:
    environment_match = re.fullmatch(r"(?i)(gb|cn|ac-gb|ac-cn|dbg-cn|dbg-vn)\s*:\s*(\d+)", raw_target)
    if environment_match:
        schema = {
            "gb": "int_sass_crm_ac",
            "cn": "sass_crm_ac",
            "ac-gb": "int_sass_crm_ac",
            "ac-cn": "sass_crm_ac",
            "dbg-cn": "crm_cn",
            "dbg-vn": "crm_vn",
        }[environment_match.group(1).lower()]
        return "user", environment_match.group(2), schema
    if ":" in raw_target:
        prefix, value = raw_target.split(":", 1)
        prefix = prefix.strip().lower()
        value = value.strip()
        if prefix in {"user", "crm"}:
            if not value.isdigit():
                raise ValueError("CRM用户ID格式无效")
            return "user", value, ""
        if prefix in {"account", "login"}:
            if not value.isdigit():
                raise ValueError("交易账号格式无效")
            return "account", value, ""
    if raw_target.isdigit():
        return "numeric", raw_target, ""
    return "name", raw_target, ""


def _subject_from_row(row: dict, schema: str, source: dict, matched_by: str, matched_account: object = "") -> dict:
    user_type = _integer(row.get("user_type"), -1)
    return {
        "schema": schema,
        "source": source,
        "environment": _text(source.get("name")),
        "userId": _integer(row.get("id")),
        "parentUserId": _integer(row.get("supper_id")) or None,
        "topIbId": _integer(row.get("top_ib_id")) or None,
        "userType": user_type,
        "role": "referral" if user_type == 1 else "customer",
        "roleLabel": "Referral" if user_type == 1 else "普通客户",
        "name": _full_name(row),
        "customerType": _text(row.get("customer_type")),
        "ibLevel": row.get("ib_level"),
        "status": row.get("status"),
        "matchedBy": matched_by,
        "matchedAccount": _integer(matched_account) or None,
    }


def resolve_subject(target: str, sources: list[dict], connect: Callable) -> dict:
    mode, value, schema_filter = _target_mode(target)
    matches = []
    fields = """
        u.id, u.supper_id, u.top_ib_id, u.user_type, u.customer_type,
        u.ib_level, u.status, u.full_name, u.first_name, u.middle_name, u.last_name
    """
    for source in _crm_sources(sources):
        schema = _text(source.get("crm_schema"))
        if schema_filter and schema != schema_filter:
            continue
        server_codes = _server_codes_for_schema(sources, schema)
        if not server_codes:
            continue
        with connect(source) as conn:
            with conn.cursor() as cur:
                account_rows = []
                if mode in {"account", "numeric"}:
                    placeholders = ",".join(["%s"] * len(server_codes))
                    cur.execute(
                        f"""
                        select {fields}, a.mt_login as matched_account
                        from `{schema}`.`mt_users_account` a
                        join `{schema}`.`sys_user_view` u on u.id = a.user_id
                        where a.mt_login = %s and a.mt_server_code in ({placeholders})
                        """,
                        [int(value), *server_codes],
                    )
                    account_rows = cur.fetchall()
                    for row in account_rows:
                        matches.append(_subject_from_row(row, schema, source, "account", row.get("matched_account")))
                if mode == "user" or (mode == "numeric" and not account_rows):
                    cur.execute(
                        f"select {fields} from `{schema}`.`sys_user_view` u where u.id = %s",
                        (int(value),),
                    )
                    for row in cur.fetchall():
                        matches.append(_subject_from_row(row, schema, source, "user"))
                if mode == "name":
                    normalized_name = " ".join(value.upper().split())
                    cur.execute(
                        f"""
                        select {fields}
                        from `{schema}`.`sys_user_view` u
                        where upper(trim(u.full_name)) = %s
                           or upper(trim(concat_ws(' ', u.first_name, u.middle_name, u.last_name))) = %s
                        """,
                        (normalized_name, normalized_name),
                    )
                    for row in cur.fetchall():
                        matches.append(_subject_from_row(row, schema, source, "name"))

    if mode == "numeric" and any(match["matchedBy"] == "account" for match in matches):
        matches = [match for match in matches if match["matchedBy"] == "account"]
    deduplicated = {}
    for match in matches:
        deduplicated[(match["schema"], match["userId"])] = match
    matches = list(deduplicated.values())
    if not matches:
        raise ValueError("没有找到对应的IB、客户或交易账号")
    if len(matches) > 1:
        candidate_rows = []
        prefixes = {
            "int_sass_crm_ac": "gb",
            "sass_crm_ac": "cn",
            "crm_cn": "dbg-cn",
            "crm_vn": "dbg-vn",
        }
        for row in sorted(matches, key=lambda item: (item["schema"], item["userId"])):
            prefix = prefixes[row["schema"]]
            candidate_rows.append(
                {
                    "target": f"{prefix}:{row['userId']}",
                    "userId": row["userId"],
                    "name": row["name"],
                    "role": row["role"],
                    "roleLabel": row["roleLabel"],
                    "environment": row["environment"],
                    "ibLevel": row["ibLevel"],
                }
            )
        raise AmbiguousTargetError("找到多个匹配，请选择具体IB或客户", candidate_rows)
    return matches[0]


def _fetch_tree_and_accounts(subject: dict, sources: list[dict], connect: Callable) -> tuple[dict[int, dict], list[dict]]:
    schema = subject["schema"]
    source = subject["source"]
    server_codes = _server_codes_for_schema(sources, schema)
    if not server_codes:
        raise ValueError(f"{schema}没有配置可用的交易服务器")
    fields = """
        id, supper_id, top_ib_id, user_type, customer_type, ib_level,
        status, full_name, first_name, middle_name, last_name
    """
    users: dict[int, dict] = {}
    with connect(source) as conn:
        with conn.cursor() as cur:
            cur.execute(f"select {fields} from `{schema}`.`sys_user_view` where id = %s", (subject["userId"],))
            root = cur.fetchone()
            if not root:
                raise ValueError("目标CRM用户不存在")
            root_id = _integer(root.get("id"))
            users[root_id] = {**root, "depth": 0}
            frontier = [root_id]
            depth = 0
            while frontier:
                depth += 1
                next_frontier = []
                for batch in _batches(frontier):
                    placeholders = ",".join(["%s"] * len(batch))
                    cur.execute(
                        f"select {fields} from `{schema}`.`sys_user_view` where supper_id in ({placeholders})",
                        batch,
                    )
                    for row in cur.fetchall():
                        user_id = _integer(row.get("id"))
                        if not user_id or user_id in users:
                            continue
                        users[user_id] = {**row, "depth": depth}
                        next_frontier.append(user_id)
                        if len(users) > MAX_USERS:
                            raise ValueError(f"下线用户超过安全上限{MAX_USERS}，请缩小查询对象")
                frontier = next_frontier

            accounts = []
            for batch in _batches(users):
                placeholders = ",".join(["%s"] * len(batch))
                server_placeholders = ",".join(["%s"] * len(server_codes))
                cur.execute(
                    f"""
                    select user_id, mt_login, mt_server_code, mt_type_name, status, create_time
                    from `{schema}`.`mt_users_account`
                    where user_id in ({placeholders}) and mt_server_code in ({server_placeholders})
                    """,
                    [*batch, *server_codes],
                )
                accounts.extend(cur.fetchall())
                if len(accounts) > MAX_ACCOUNTS:
                    raise ValueError(f"下线账户超过安全上限{MAX_ACCOUNTS}，请缩小查询对象")
    return users, accounts


def _source_for_account(sources: list[dict], crm_schema: str, server_code: str) -> dict | None:
    route_key = (_text(crm_schema), _text(server_code))
    return next(
        (
            source
            for source in sources
            if route_key in {
                (route["schema"], route["mt_server_code"])
                for route in _source_routes(source)
            }
        ),
        None,
    )


def list_products(sources: list[dict], connect: Callable) -> dict:
    products: dict[str, str] = {}
    errors = []
    physical_sources = []
    seen = set()
    for source in sources:
        key = (
            _text(source.get("host")),
            _text(source.get("schema")),
            _text(source.get("table")),
            _text(source.get("kind")),
        )
        if not key[1] or not key[2] or not key[3] or key in seen or not _source_routes(source):
            continue
        seen.add(key)
        physical_sources.append(source)

    for source in physical_sources:
        try:
            with connect(source) as conn:
                with conn.cursor() as cur:
                    if source.get("kind") == "mt5_deals":
                        cur.execute(
                            f"""
                            select distinct Symbol as Product
                            from `{source['schema']}`.`mt5_symbols`
                            where Symbol is not null and Symbol <> ''
                            order by Symbol
                            """
                        )
                    else:
                        cur.execute(
                            f"""
                            select distinct SYMBOL as Product
                            from `{source['schema']}`.`mt4_trades_snap`
                            where SYMBOL is not null and SYMBOL <> ''
                            order by SYMBOL
                            """
                        )
                    for row in cur.fetchall():
                        product = _text(row.get("Product"))
                        if product:
                            base_product = product.split(".", 1)[0]
                            products.setdefault(base_product.upper(), base_product)
        except Exception as exc:
            errors.append(f"{_text(source.get('name'))}: {exc}")
    if not products and errors:
        raise RuntimeError("；".join(errors[:3]))
    values = sorted(products.values(), key=lambda value: value.upper())
    eligible = [value for value in values if is_promotion_product(value)]
    other = [value for value in values if not is_promotion_product(value)]
    return {
        "ok": True,
        "products": values,
        "promotionProducts": eligible,
        "otherProducts": other,
        "promotionValue": PROMOTION_PRODUCT,
        "promotionLabel": "本次活动产品（外汇 + 贵金属）",
    }


def _empty_metrics() -> dict:
    return {
        "deposit": 0.0,
        "withdrawal": 0.0,
        "netDeposit": 0.0,
        "depositCount": 0,
        "withdrawalCount": 0,
        "orders": 0,
        "lots": 0.0,
        "tradingProfit": 0.0,
        "symbols": [],
    }


def _account_key(crm_schema: str, row: dict) -> tuple[str, str, int]:
    return crm_schema, _text(row.get("mt_server_code")), _integer(row.get("mt_login"))


def _collect_metrics(
    subject: dict,
    accounts: list[dict],
    query: dict,
    sources: list[dict],
    connect: Callable,
    classify_mt5_cashflows: Callable,
    classify_mt4_cashflows: Callable,
) -> dict[tuple[str, str, int], dict]:
    crm_schema = subject["schema"]
    metrics = {_account_key(crm_schema, row): _empty_metrics() for row in accounts}
    grouped = defaultdict(list)
    for row in accounts:
        server_code = _text(row.get("mt_server_code"))
        source = _source_for_account(sources, crm_schema, server_code)
        if source:
            grouped[_text(source.get("name"))].append(row)

    for source_name, source_accounts in grouped.items():
        source = next(source for source in sources if _text(source.get("name")) == source_name)
        kind = source.get("kind")
        for batch_rows in _batches(source_accounts):
            logins = sorted({_integer(row.get("mt_login")) for row in batch_rows})
            placeholders = ",".join(["%s"] * len(logins))
            row_by_login = {_integer(row.get("mt_login")): row for row in batch_rows}
            cash_by_login = defaultdict(list)
            with connect(source) as conn:
                with conn.cursor() as cur:
                    if kind == "mt5_deals":
                        cur.execute(
                            f"""
                            select Login, Action, Profit, Comment, Time, TimeMsc
                            from `{source['schema']}`.`{source['table']}`
                            where Login in ({placeholders}) and Action not in (0, 1)
                              and Time >= %s and Time <= %s
                            """,
                            [*logins, query["start"], query["end"]],
                        )
                        for row in cur.fetchall():
                            cash_by_login[_integer(row.get("Login"))].append(row)
                        product_sql = (
                            " and upper(Symbol) like concat(upper(%s), '%%')"
                            if query["product"] and query["product"] != PROMOTION_PRODUCT
                            else ""
                        )
                        parameters = [*logins, query["start"], query["end"]]
                        if product_sql:
                            parameters.append(query["product"])
                        cur.execute(
                            f"""
                            select Login, Symbol as Product, count(*) as Orders,
                                   sum(coalesce(nullif(VolumeClosed, 0), Volume)) / 10000 as Lots,
                                   sum(coalesce(Profit, 0) + coalesce(Commission, 0)
                                       + coalesce(Storage, 0) + coalesce(Fee, 0)) as TradingProfit
                            from `{source['schema']}`.`{source['table']}`
                            where Login in ({placeholders}) and Action in (0, 1) and Entry = 1
                              and Time >= %s and Time <= %s {product_sql}
                            group by Login, Symbol
                            """,
                            parameters,
                        )
                        trade_rows = defaultdict(list)
                        for row in cur.fetchall():
                            trade_rows[_integer(row.get("Login"))].append(row)
                    else:
                        cur.execute(
                            f"""
                            select LOGIN, CMD, PROFIT, COMMENT, OPEN_TIME, CLOSE_TIME
                            from `{source['schema']}`.`{source['table']}`
                            where LOGIN in ({placeholders}) and CMD in (6, 7)
                              and OPEN_TIME >= %s and OPEN_TIME <= %s
                            """,
                            [*logins, query["start"], query["end"]],
                        )
                        for row in cur.fetchall():
                            cash_by_login[_integer(row.get("LOGIN"))].append(row)
                        product_sql = (
                            " and upper(SYMBOL) like concat(upper(%s), '%%')"
                            if query["product"] and query["product"] != PROMOTION_PRODUCT
                            else ""
                        )
                        parameters = [*logins, query["start"], query["end"]]
                        if product_sql:
                            parameters.append(query["product"])
                        cur.execute(
                            f"""
                            select LOGIN, SYMBOL as Product, count(*) as Orders, sum(VOLUME) / 100 as Lots,
                                   sum(coalesce(PROFIT, 0) + coalesce(COMMISSION, 0)
                                       + coalesce(SWAPS, 0) + coalesce(TAXES, 0)) as TradingProfit
                            from `{source['schema']}`.`{source['table']}`
                            where LOGIN in ({placeholders}) and CMD in (0, 1)
                              and CLOSE_TIME >= %s and CLOSE_TIME <= %s {product_sql}
                            group by LOGIN, SYMBOL
                            """,
                            parameters,
                        )
                        trade_rows = defaultdict(list)
                        for row in cur.fetchall():
                            trade_rows[_integer(row.get("LOGIN"))].append(row)

            for login in logins:
                account = row_by_login[login]
                is_cent = bool(CENT_PATTERN.search(_text(account.get("mt_type_name"))))
                money_scale = 0.01 if is_cent else 1.0
                cash = (
                    classify_mt5_cashflows(cash_by_login.get(login, []), money_scale)
                    if kind == "mt5_deals"
                    else classify_mt4_cashflows(cash_by_login.get(login, []), money_scale)
                )
                selected_trades = trade_rows.get(login, [])
                if query["product"] == PROMOTION_PRODUCT:
                    selected_trades = [row for row in selected_trades if is_promotion_product(row.get("Product"))]
                trade = {
                    "Orders": sum(_integer(row.get("Orders")) for row in selected_trades),
                    "Lots": sum(_number(row.get("Lots")) for row in selected_trades),
                    "TradingProfit": sum(_number(row.get("TradingProfit")) for row in selected_trades),
                    "Symbols": ",".join(sorted({_text(row.get("Product")) for row in selected_trades if _text(row.get("Product"))})),
                }
                key = _account_key(crm_schema, account)
                metrics[key].update(
                    {
                        "deposit": _number(cash.get("depositTotal")),
                        "withdrawal": _number(cash.get("withdrawalTotal")),
                        "netDeposit": _number(cash.get("netDeposit")),
                        "depositCount": _integer(cash.get("depositCount")),
                        "withdrawalCount": _integer(cash.get("withdrawalCount")),
                        "orders": _integer(trade.get("Orders")),
                        "lots": _number(trade.get("Lots")),
                        "tradingProfit": _number(trade.get("TradingProfit")) * money_scale,
                        "symbols": [symbol for symbol in _text(trade.get("Symbols")).split(",") if symbol],
                    }
                )
    return metrics


def _sum_rows(rows: list[dict]) -> dict:
    keys = ("deposit", "withdrawal", "netDeposit", "depositCount", "withdrawalCount", "orders", "lots", "tradingProfit")
    totals = {key: sum(_number(row.get(key)) for row in rows) for key in keys}
    totals["depositCount"] = int(totals["depositCount"])
    totals["withdrawalCount"] = int(totals["withdrawalCount"])
    totals["orders"] = int(totals["orders"])
    for key in ("deposit", "withdrawal", "netDeposit", "lots", "tradingProfit"):
        totals[key] = _rounded(totals[key])
    return totals


def _promotion_rules_payload(subject: dict, users_list: list[dict], account_rows: list[dict]) -> dict:
    users_by_id = {row["userId"]: row for row in users_list}
    children = defaultdict(list)
    for row in users_list:
        if row.get("parentUserId") in users_by_id:
            children[row["parentUserId"]].append(row["userId"])

    standard_accounts = defaultdict(list)
    for row in account_rows:
        if not row.get("isCent"):
            standard_accounts[row["userId"]].append(row)
    own_metrics = {user_id: _sum_rows(standard_accounts.get(user_id, [])) for user_id in users_by_id}

    decisions = {}
    customer_qualified = {}
    owner_by_user = {}
    for row in users_list:
        if row["role"] != "customer":
            continue
        metrics = own_metrics[row["userId"]]
        qualified = (
            metrics["netDeposit"] >= PROMOTION_NET_DEPOSIT_THRESHOLD
            and metrics["lots"] >= PROMOTION_LOTS_THRESHOLD
        )
        customer_qualified[row["userId"]] = qualified
        if qualified:
            owner_by_user[row["userId"]] = row["userId"]
        decisions[row["userId"]] = {
            "userId": row["userId"],
            "parentUserId": row.get("parentUserId"),
            "depth": row["depth"],
            "name": row["name"],
            "role": row["role"],
            "roleLabel": row["roleLabel"],
            "ibLevel": row.get("ibLevel"),
            "customerType": row.get("customerType", ""),
            "netDeposit": metrics["netDeposit"],
            "lots": metrics["lots"],
            "orders": metrics["orders"],
            "qualified": qualified,
            "statusLabel": "普通客户自行达标" if qualified else "未达标，计入直属IB候选池",
            "rollsToUserId": None if qualified else row.get("parentUserId"),
            "contributorUserIds": [row["userId"]],
        }

    rolled_metrics = defaultdict(list)
    rolled_contributors = defaultdict(list)
    referral_rows = sorted(
        (row for row in users_list if row["role"] == "referral"),
        key=lambda row: (row["depth"], row["userId"]),
        reverse=True,
    )
    root_user_id = subject["userId"]
    for row in referral_rows:
        user_id = row["userId"]
        direct_customers = [
            child_id
            for child_id in children.get(user_id, [])
            if users_by_id[child_id]["role"] == "customer" and not customer_qualified.get(child_id, False)
        ]
        direct_referrals = [
            child_id
            for child_id in children.get(user_id, [])
            if users_by_id[child_id]["role"] == "referral"
        ]
        contributors = direct_customers + direct_referrals + rolled_contributors.get(user_id, [])
        pool_rows = [own_metrics[customer_id] for customer_id in direct_customers]
        pool_rows.extend(own_metrics[referral_id] for referral_id in direct_referrals)
        pool_rows.extend(rolled_metrics.get(user_id, []))
        metrics = _sum_rows(pool_rows)
        region_eligible = _text(row.get("customerType")).upper() == "VN"
        qualified = (
            region_eligible
            and metrics["netDeposit"] >= PROMOTION_NET_DEPOSIT_THRESHOLD
            and metrics["lots"] >= PROMOTION_LOTS_THRESHOLD
        )
        parent_id = row.get("parentUserId")
        parent_is_referral = parent_id in users_by_id and users_by_id[parent_id]["role"] == "referral"
        rolls_to = parent_id if not qualified and parent_is_referral else None
        if qualified:
            for contributor_id in contributors:
                owner_by_user[contributor_id] = user_id
        elif rolls_to:
            rolled_metrics[rolls_to].append(metrics)
            rolled_contributors[rolls_to].extend(contributors)
        elif user_id == root_user_id:
            for contributor_id in contributors:
                owner_by_user[contributor_id] = user_id
        if qualified:
            status_label = "当前目标达标" if user_id == root_user_id else "下级IB达标，独立领取"
        elif rolls_to:
            status_label = "未达标，向上级IB归集"
        elif not region_eligible:
            status_label = "非越南Referral，不具备活动资格"
        else:
            status_label = "当前目标未达标"
        decisions[user_id] = {
            "userId": user_id,
            "parentUserId": parent_id,
            "depth": row["depth"],
            "name": row["name"],
            "role": row["role"],
            "roleLabel": row["roleLabel"],
            "ibLevel": row.get("ibLevel"),
            "customerType": row.get("customerType", ""),
            "netDeposit": metrics["netDeposit"],
            "lots": metrics["lots"],
            "orders": metrics["orders"],
            "qualified": qualified,
            "regionEligible": region_eligible,
            "statusLabel": status_label,
            "rollsToUserId": rolls_to,
            "contributorUserIds": sorted(set(contributors)),
        }

    if subject.get("role") == "customer":
        owner_by_user[root_user_id] = root_user_id

    included_user_ids = {
        user_id for user_id, owner_id in owner_by_user.items() if owner_id == root_user_id
    }
    included_accounts = [
        row
        for row in account_rows
        if not row.get("isCent") and row["userId"] in included_user_ids
    ]
    summary = _sum_rows(included_accounts)
    summary.update(
        {
            "users": len(included_user_ids),
            "referrals": sum(1 for user_id in included_user_ids if users_by_id[user_id]["role"] == "referral"),
            "customers": sum(1 for user_id in included_user_ids if users_by_id[user_id]["role"] == "customer"),
            "accounts": len(included_accounts),
            "standardAccounts": len(included_accounts),
            "centAccounts": 0,
            "standardNetDeposit": summary["netDeposit"],
            "centNetDeposit": 0.0,
            "standardLots": summary["lots"],
            "centLots": 0.0,
            "standardTradingProfit": summary["tradingProfit"],
            "centTradingProfit": 0.0,
            "accountsWithCashflow": sum(
                1 for row in included_accounts if row["depositCount"] or row["withdrawalCount"]
            ),
            "accountsWithTrades": sum(1 for row in included_accounts if row["orders"]),
        }
    )

    for row in account_rows:
        if row.get("isCent"):
            row.update(
                {
                    "activityIncluded": False,
                    "activityOwnerUserId": None,
                    "activityReason": "Cent账户不参加活动",
                }
            )
        else:
            owner_id = owner_by_user.get(row["userId"])
            is_root_referral_account = row["userId"] == root_user_id and row["role"] == "referral"
            row.update(
                {
                    "activityIncluded": owner_id == root_user_id,
                    "activityOwnerUserId": owner_id,
                    "activityReason": (
                        "计入当前目标活动业绩"
                        if owner_id == root_user_id
                        else (
                            "当前Referral本人账户不计入自己的直属客户业绩"
                            if is_root_referral_account
                            else ("归属自行达标客户" if owner_id == row["userId"] else "归属已达标下级对象")
                        )
                    ),
                }
            )

    subject_decision = decisions.get(root_user_id, {})
    return {
        "enabled": True,
        "netDepositThreshold": PROMOTION_NET_DEPOSIT_THRESHOLD,
        "lotsThreshold": PROMOTION_LOTS_THRESHOLD,
        "subjectQualified": bool(subject_decision.get("qualified")),
        "includedUserIds": sorted(included_user_ids),
        "includedCustomerIds": sorted(
            user_id for user_id in included_user_ids if users_by_id[user_id]["role"] == "customer"
        ),
        "decisions": sorted(decisions.values(), key=lambda row: (row["depth"], row["userId"]), reverse=True),
        "summary": summary,
        "notes": [
            "外汇和贵金属手数；Cent账户排除",
            "普通客户自行达标时独立领取；否则计入直属IB候选池",
            "下级Referral本人交易属于上级直属客户业绩；其下线业绩达标后不再向上重复归集",
            "下级IB未达标的下线业绩逐级向上归集",
            "Referral佣金出金按交易账户已识别的出金流水扣除；独立返佣钱包出金仍需人工复核",
        ],
    }


def build_payload(
    target: object,
    start: object,
    end: object,
    product: object,
    activity_rules: object = False,
    *,
    sources: list[dict],
    connect: Callable,
    classify_mt5_cashflows: Callable,
    classify_mt4_cashflows: Callable,
    refreshed_at: str,
) -> dict:
    query = parse_query(target, start, end, product, activity_rules)
    subject = resolve_subject(query["target"], sources, connect)
    users, raw_accounts = _fetch_tree_and_accounts(subject, sources, connect)
    metrics = _collect_metrics(
        subject,
        raw_accounts,
        query,
        sources,
        connect,
        classify_mt5_cashflows,
        classify_mt4_cashflows,
    )

    user_rows = {}
    for user_id, user in users.items():
        user_type = _integer(user.get("user_type"), -1)
        user_rows[user_id] = {
            "userId": user_id,
            "parentUserId": _integer(user.get("supper_id")) or None,
            "depth": _integer(user.get("depth")),
            "name": _full_name(user),
            "role": "referral" if user_type == 1 else "customer",
            "roleLabel": "Referral" if user_type == 1 else "普通客户",
            "ibLevel": user.get("ib_level"),
            "customerType": _text(user.get("customer_type")),
            "accountCount": 0,
            **_empty_metrics(),
        }

    account_rows = []
    for account in raw_accounts:
        user_id = _integer(account.get("user_id"))
        user = users[user_id]
        server_code = _text(account.get("mt_server_code"))
        source = _source_for_account(sources, subject["schema"], server_code)
        type_name = _text(account.get("mt_type_name"))
        is_cent = bool(CENT_PATTERN.search(type_name))
        account_metrics = metrics[_account_key(subject["schema"], account)]
        row = {
            "userId": user_id,
            "parentUserId": _integer(user.get("supper_id")) or None,
            "depth": _integer(user.get("depth")),
            "name": _full_name(user),
            "role": "referral" if _integer(user.get("user_type"), -1) == 1 else "customer",
            "roleLabel": "Referral" if _integer(user.get("user_type"), -1) == 1 else "普通客户",
            "account": _integer(account.get("mt_login")),
            "platform": _text(source.get("platform")) if source else "",
            "server": _text(source.get("server")) if source else "",
            "typeName": type_name,
            "isCent": is_cent,
            "displayCurrency": "USD",
            "status": account.get("status"),
            "sourceAvailable": bool(source),
            **account_metrics,
        }
        for key in ("deposit", "withdrawal", "netDeposit", "lots", "tradingProfit"):
            row[key] = _rounded(row[key])
        account_rows.append(row)
        user_row = user_rows[user_id]
        user_row["accountCount"] += 1
        for key in ("deposit", "withdrawal", "netDeposit", "depositCount", "withdrawalCount", "orders", "lots", "tradingProfit"):
            user_row[key] += row[key]
        user_row["symbols"] = sorted(set(user_row["symbols"]) | set(row.get("symbols", [])))

    for row in user_rows.values():
        for key in ("deposit", "withdrawal", "netDeposit", "lots", "tradingProfit"):
            row[key] = _rounded(row[key])
        for key in ("depositCount", "withdrawalCount", "orders"):
            row[key] = int(row[key])

    account_rows.sort(key=lambda row: (row["depth"], row["role"] != "referral", row["userId"], row["platform"], row["account"]))
    users_list = sorted(user_rows.values(), key=lambda row: (row["depth"], row["userId"]))
    totals = _sum_rows(account_rows)
    standard_rows = [row for row in account_rows if not row["isCent"]]
    cent_rows = [row for row in account_rows if row["isCent"]]
    totals.update(
        {
            "users": len(users),
            "referrals": sum(1 for row in users_list if row["role"] == "referral"),
            "customers": sum(1 for row in users_list if row["role"] == "customer"),
            "accounts": len(account_rows),
            "standardAccounts": len(standard_rows),
            "centAccounts": len(cent_rows),
            "standardNetDeposit": _sum_rows(standard_rows)["netDeposit"],
            "centNetDeposit": _sum_rows(cent_rows)["netDeposit"],
            "standardLots": _sum_rows(standard_rows)["lots"],
            "centLots": _sum_rows(cent_rows)["lots"],
            "standardTradingProfit": _sum_rows(standard_rows)["tradingProfit"],
            "centTradingProfit": _sum_rows(cent_rows)["tradingProfit"],
            "accountsWithCashflow": sum(1 for row in account_rows if row["depositCount"] or row["withdrawalCount"]),
            "accountsWithTrades": sum(1 for row in account_rows if row["orders"]),
        }
    )
    raw_totals = totals
    promotion_rules = None
    if query["activityRules"]:
        promotion_rules = _promotion_rules_payload(subject, users_list, account_rows)
        totals = promotion_rules["summary"]
    public_subject = {key: value for key, value in subject.items() if key not in {"source"}}
    product_label = (
        "本次活动产品（外汇 + 贵金属）"
        if query["product"] == PROMOTION_PRODUCT
        else (query["product"] or "全部产品")
    )
    return {
        "ok": True,
        "query": {
            "target": query["target"],
            "start": query["start"].strftime("%Y-%m-%d %H:%M:%S"),
            "end": query["end"].strftime("%Y-%m-%d %H:%M:%S"),
            "product": query["product"],
            "productLabel": product_label,
            "productMode": "promotion" if query["product"] == PROMOTION_PRODUCT else ("prefix" if query["product"] else "all"),
            "cashflowScope": "promotion-standard-accounts" if query["activityRules"] else "all-products",
            "activityRules": query["activityRules"],
        },
        "subject": public_subject,
        "summary": totals,
        "rawSummary": raw_totals if promotion_rules else None,
        "promotionRules": promotion_rules,
        "users": users_list,
        "accounts": account_rows,
        "refreshedAt": refreshed_at,
    }
