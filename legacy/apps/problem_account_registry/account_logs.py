from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Mapping


MAX_RANGE_DAYS = 31
MAX_ROWS = 10_000


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = _text(value).replace("T", " ")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        for fmt, size in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
            try:
                return datetime.strptime(text[:size], fmt)
            except ValueError:
                continue
    return None


def _identifier(value: object) -> str:
    text = _text(value)
    if not re.fullmatch(r"[A-Za-z0-9_]+", text):
        raise ValueError(f"Unsafe SQL identifier: {text!r}")
    return text


def _mysql_time(row: Mapping[str, object], mt4: bool = False) -> datetime | None:
    if mt4:
        return _parse_datetime(row.get("OPEN_TIME") or row.get("CLOSE_TIME"))
    return _parse_datetime(row.get("TimeMsc") or row.get("Time"))


def _json_value(value: object):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S.%f").rstrip("0").rstrip(".")
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _normalize_mt5(row: Mapping[str, object], source: Mapping[str, object]) -> dict:
    event_time = _mysql_time(row)
    return {
        "eventTime": _json_value(event_time),
        "source": source.get("name") or source.get("server"),
        "platform": "MT5",
        "eventType": "deal",
        "ticket": row.get("Deal") or row.get("Order") or row.get("PositionID"),
        "symbol": row.get("Symbol"),
        "details": _json_value(row),
    }


def _normalize_mt4(row: Mapping[str, object], source: Mapping[str, object]) -> dict:
    event_time = _mysql_time(row, mt4=True)
    return {
        "eventTime": _json_value(event_time),
        "source": source.get("name") or source.get("server"),
        "platform": "MT4",
        "eventType": "trade",
        "ticket": row.get("TICKET"),
        "symbol": row.get("SYMBOL"),
        "details": _json_value(row),
    }


def _query_source(source: Mapping[str, object], login: str, start: datetime, end: datetime, connect: Callable) -> dict:
    schema = _identifier(source.get("schema"))
    table = _identifier(source.get("table"))
    kind = _text(source.get("kind"))
    mt4 = kind == "mt4_trades"
    if kind != "mt5_deals" and not mt4:
        return {"rows": [], "warning": f"{source.get('name')}: unsupported log source"}
    if mt4:
        sql = f"""
            select * from `{schema}`.`{table}`
            where LOGIN = %s
              and ((OPEN_TIME between %s and %s) or (CLOSE_TIME between %s and %s))
            order by OPEN_TIME desc, TICKET desc
            limit %s
        """
    else:
        sql = f"""
            select * from `{schema}`.`{table}`
            where Login = %s and Time between %s and %s
            order by TimeMsc desc, Deal desc
            limit %s
        """
    args = (int(login), start, end, start, end, MAX_ROWS) if mt4 else (int(login), start, end, MAX_ROWS)
    with connect(source) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            raw_rows = list(cur.fetchall())
    normalizer = _normalize_mt4 if mt4 else _normalize_mt5
    return {"rows": [normalizer(row, source) for row in raw_rows]}


def query_account_logs(
    account: str,
    start: object,
    end: object,
    sources: list[Mapping[str, object]],
    connect: Callable,
) -> dict:
    account = _text(account)
    if not account or len(account) > 64 or not re.fullmatch(r"[0-9A-Za-z_.-]+", account):
        raise ValueError("账号格式无效")
    start_dt = _parse_datetime(start)
    end_dt = _parse_datetime(end)
    if start_dt is None or end_dt is None:
        raise ValueError("请输入有效的开始和结束时间")
    if end_dt < start_dt:
        raise ValueError("结束时间不能早于开始时间")
    if end_dt - start_dt > timedelta(days=MAX_RANGE_DAYS):
        raise ValueError(f"日志查询时间范围不能超过 {MAX_RANGE_DAYS} 天")

    rows: list[dict] = []
    warnings: list[str] = []
    query_sources = [source for source in sources if _text(source.get("kind")) in {"mt5_deals", "mt4_trades"}]
    with ThreadPoolExecutor(max_workers=min(8, max(len(query_sources), 1)), thread_name_prefix="account-logs") as executor:
        futures = {executor.submit(_query_source, source, account, start_dt, end_dt, connect): source for source in query_sources}
        for future in as_completed(futures):
            source = futures[future]
            try:
                result = future.result()
                rows.extend(result.get("rows", []))
                if result.get("warning"):
                    warnings.append(result["warning"])
            except Exception as exc:
                warnings.append(f"{source.get('name')}: {exc}")
    rows.sort(key=lambda row: _mysql_time(row["details"], row["platform"] == "MT4") or datetime.min, reverse=True)
    return {
        "ok": True,
        "account": account,
        "start": _json_value(start_dt),
        "end": _json_value(end_dt),
        "rows": rows[:MAX_ROWS],
        "matchedCount": len(rows),
        "truncated": len(rows) > MAX_ROWS,
        "warnings": warnings,
        "source": "MySQL trade export",
    }
