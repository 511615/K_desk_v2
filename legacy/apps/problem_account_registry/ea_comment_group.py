from __future__ import annotations

import re
import sqlite3
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
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

_EXIT_ONLY_COMMENT_RE = re.compile(r"^\[\s*(?:s/?l|t/?p|so)(?:\s+[^\]]*)?\s*\]$", re.IGNORECASE)
_TRAILING_EXIT_RE = re.compile(r"(?i)\s*(?:\[(?:s/?l|t/?p|so)(?:\s+[^\]]*)?\])+$")
_ROUTE_PATTERNS = (
    (re.compile(r"(?i)^CPT(?:-[A-Z0-9]+)?\s*#\s*(\d+)$"), "CPT 路由编号"),
    (re.compile(r"(?i)^Signal\s*#.+\s+IN$"), "平台 Signal 路由"),
    (re.compile(r"^@(\d+)@(\d+)@(\d+)$"), "三段 @ 数字路由"),
    (re.compile(r"^(\d{1,9})/(\d{1,9})/(\d{5,})$"), "三段斜杠数字路由"),
    (re.compile(r"^(\d{5,})-(\d{5,})$"), "账号与来源号路由"),
)
_SYSTEM_EVENT_RE = re.compile(
    r"(?i)^(?:so\s*:|from\s*#|to\s*#|balance\b|deposit\b|withdraw(?:al)?\b|credit\b|"
    r"stop\s*out\b|margin\s*call\b)"
)
_CONTACT_TOKEN_RE = re.compile(
    r"(?i)(?:\b(?:QQ|VX|WX|WECHAT|ZALO|TEL|PHONE|WHATSAPP)\b\s*[:：-]?\s*[+\d][\d -]{4,}|"
    r"(?:微信|电话|手机)\s*[:：-]?\s*[+\d][\d -]{4,})"
)
_DYNAMIC_RULE_VERSION = "2026.07.24.2"
_DYNAMIC_PRIMARY_SCHEMAS = {
    "sass_crm_ac_mt5_live",
    "mt5_export_new",
    "crm_vn_mt5_live2",
}
_DYNAMIC_DISCOVERY_CACHE_TTL = 60.0
_DYNAMIC_DISCOVERY_CACHE: dict[tuple, tuple[float, frozenset[tuple[str, str]]]] = {}
_DYNAMIC_DISCOVERY_CACHE_LOCK = threading.Lock()
_GLOBAL_COMMENT_QUERY_MAX_WORKERS = 12
_MT5_POSITION_QUERY_BATCH_SIZE = 1000
_EXPERT_SEQUENCE_MIN_SHARED = 5
_EXPERT_SEQUENCE_MIN_OVERLAP = 0.80
_EXPERT_SEQUENCE_TIME_TOLERANCE_SECONDS = 2.0
_EXPERT_SEQUENCE_MIN_TIME_POINTS = 3
_EXPERT_SEQUENCE_MIN_SPAN_SECONDS = 60.0
_EXPERT_SEQUENCE_MAX_EVENTS = 200
_EXPERT_SEQUENCE_MAX_DAYS = 31


def _classification(
    category: str,
    label: str,
    comment: str,
    *,
    template: str = "",
    prefix: str = "",
    evidence: str = "",
    dynamic: bool = False,
    source: str = "builtin",
) -> dict:
    return {
        "classification": category,
        "classificationLabel": label,
        "countedAsEa": category in {"exact_ea", "dynamic_ea"},
        "normalizedComment": comment,
        "normalizedTemplate": template or comment,
        "stablePrefix": prefix or comment,
        "classificationEvidence": evidence,
        "dynamicEligible": dynamic,
        "classificationSource": source,
        "ruleVersion": _DYNAMIC_RULE_VERSION,
    }


def _strip_comment_suffix(value: object) -> str:
    return _TRAILING_EXIT_RE.sub("", _text(value)).strip()


def _route_classification(comment: str) -> dict | None:
    for pattern, evidence in _ROUTE_PATTERNS:
        match = pattern.fullmatch(comment)
        if not match:
            continue
        if comment.startswith("@"):
            template = f"@{match.group(1)}@{{SOURCE_ID}}@{match.group(3)}"
            prefix = f"@{match.group(1)}@"
        elif "/" in comment:
            template = f"{match.group(1)}/{match.group(2)}/{{SOURCE_ID}}"
            prefix = f"{match.group(1)}/{match.group(2)}/"
        elif re.fullmatch(r"\d{5,}-\d{5,}", comment):
            template = f"{match.group(1)}-{{SOURCE_ID}}"
            prefix = f"{match.group(1)}-"
        elif comment.casefold().startswith("signal"):
            template = re.sub(r"(?i)#.+(?=\s+IN$)", "#{SOURCE_ID}", comment)
            prefix = comment.split("#", 1)[0] + "#"
        else:
            marker = comment.rfind("#")
            template = f"{comment[:marker + 1]}{{SOURCE_ID}}"
            prefix = comment[:marker + 1]
        return _classification(
            "possible_copy_route",
            "可能是跟单路由",
            comment,
            template=template,
            prefix=prefix,
            evidence=evidence,
            dynamic=True,
        )
    return None


def _dynamic_ea_classification(comment: str) -> dict | None:
    rules = (
        (re.compile(r"(?i)^(B\d+:)\d{5,}$"), lambda m: (f"{m.group(1)}{{ORDER_REF}}", m.group(1), "订单引用随交易变化")),
        (re.compile(r"^(.+\{)\d{5,}(\})$"), lambda m: (f"{m.group(1)}{{ORDER_REF}}{m.group(2)}", m.group(1), "花括号内订单引用变化")),
        (re.compile(r"(?i)^RST_RESTART_([BS])_(\d{5,})$"), lambda _m: ("RST_RESTART_{SIDE}_{INSTANCE}", "RST_RESTART_", "方向与实例号结构")),
        (re.compile(r"(?i)^(DCA_[A-Z0-9_-]*?_)\d{5,}$"), lambda m: (f"{m.group(1)}{{INSTANCE}}", m.group(1), "DCA 实例号结构")),
        (re.compile(r"(?i)^(.+?\bCID\s*=\s*)\d+(.*)$"), lambda m: (f"{m.group(1)}{{CLIENT}}{m.group(2)}", m.group(1), "CID 客户实例字段")),
        (re.compile(r"(?i)^(BuyOrder#)\d+$"), lambda m: (f"{m.group(1)}{{LEVEL}}", m.group(1), "策略层级编号")),
        (re.compile(r"(?i)^([BS]R)\d{1,3}$"), lambda m: (f"{m.group(1).upper()}{{LEVEL}}", m.group(1), "买卖方向层级编号")),
        (re.compile(r"(?i)^((?:GRID|LAYER|ORDER)[#_ -]*)\d+$"), lambda m: (f"{m.group(1)}{{LEVEL}}", m.group(1), "网格或订单层级编号")),
    )
    for pattern, build in rules:
        match = pattern.fullmatch(comment)
        if match:
            template, prefix, evidence = build(match)
            return _classification(
                "dynamic_ea", "动态 EA", comment, template=template, prefix=prefix,
                evidence=evidence, dynamic=True,
            )
    return None


def _unknown_fingerprint(comment: str, *, ea_hint: bool) -> dict:
    matches = list(re.finditer(r"\d{6,}", comment))
    if ea_hint and matches and re.search(r"[A-Za-z\u4e00-\u9fff]", comment):
        template = re.sub(r"\d{6,}", "{ID}", comment)
        prefix = comment[:matches[0].start()]
        if len(prefix) >= 2:
            return _classification(
                "dynamic_ea", "动态 EA", comment, template=template, prefix=prefix,
                evidence="自动识别到稳定文本与长数字实例字段", dynamic=True, source="learned",
            )
    return _classification(
        "unknown", "未确认格式", comment, evidence="未命中内置规则，保留精确查询", source="learned",
    )


def classify_ea_comment(value: object, *, ea_hint: bool = False) -> dict:
    """Classify one authoritative opening Comment without database or HTTP dependencies."""

    comment = _strip_comment_suffix(value)
    normalized = comment.casefold()
    if (
        not comment
        or len(comment) < 3
        or len(comment) > 255
        or normalized in _IGNORED_COMMENTS
        or _EXIT_ONLY_COMMENT_RE.fullmatch(comment)
        or _SYSTEM_EVENT_RE.search(comment)
        or re.fullmatch(r"\d+", comment)
    ):
        return _classification("system_excluded", "系统/通用备注", comment, evidence="系统事件或无业务识别意义")
    route = _route_classification(comment)
    if not route and comment.startswith("[") and comment.endswith("]"):
        route = _route_classification(comment[1:-1].strip())
        if route:
            route["normalizedComment"] = comment
    if route:
        return route
    if _CONTACT_TOKEN_RE.fullmatch(comment):
        return _classification(
            "exact_ea",
            "联系方式 Comment",
            comment,
            evidence="完整联系方式 Comment 按用户定义参与精确 EA 查询",
            source="contact",
        )
    contact_stripped = _CONTACT_TOKEN_RE.sub("", comment).strip(" -_/|,;，；")
    if not contact_stripped or not re.search(r"[A-Za-z\u4e00-\u9fff]", contact_stripped):
        return _classification("system_excluded", "联系方式备注", comment, evidence="仅包含联系方式或营销账号")
    comment = re.sub(r"\s+", " ", contact_stripped).strip()
    dynamic = _dynamic_ea_classification(comment)
    if dynamic:
        return dynamic
    unknown = _unknown_fingerprint(comment, ea_hint=ea_hint)
    if unknown["classification"] != "unknown":
        return unknown
    if ea_hint or re.search(r"(?i)(\bEA\b|expert|bot|robot|scalp|grid|dca|trade)", comment):
        return _classification("exact_ea", "EA", comment, evidence="稳定 Comment 与 EA 交易属性一致")
    return unknown


class EaCommentPatternStore:
    """Small local SQLite registry for observed non-exact Comment structures."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("pragma journal_mode=WAL")
        connection.execute("pragma busy_timeout=10000")
        connection.execute(
            """
            create table if not exists learned_ea_comment_patterns (
                normalized_template text primary key,
                stable_prefix text not null,
                classification text not null,
                classification_label text not null,
                evidence text not null,
                source text not null,
                rule_version text not null,
                first_seen_at text not null,
                last_seen_at text not null,
                observations integer not null default 1,
                sample_comment text not null
            )
            """
        )
        return connection

    def observe(self, result: dict, comment: str, observed_at: str) -> None:
        if result.get("classification") in {"exact_ea", "system_excluded"}:
            return
        with self._lock:
            connection = self._connect()
            try:
                with connection:
                    connection.execute(
                        """
                        insert into learned_ea_comment_patterns (
                            normalized_template, stable_prefix, classification, classification_label,
                            evidence, source, rule_version, first_seen_at, last_seen_at, observations, sample_comment
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                        on conflict(normalized_template) do update set
                            stable_prefix=excluded.stable_prefix,
                            classification=case when learned_ea_comment_patterns.source='manual'
                                then learned_ea_comment_patterns.classification else excluded.classification end,
                            classification_label=case when learned_ea_comment_patterns.source='manual'
                                then learned_ea_comment_patterns.classification_label else excluded.classification_label end,
                            evidence=case when learned_ea_comment_patterns.source='manual'
                                then learned_ea_comment_patterns.evidence else excluded.evidence end,
                            rule_version=excluded.rule_version,
                            last_seen_at=excluded.last_seen_at,
                            observations=learned_ea_comment_patterns.observations + 1,
                            sample_comment=excluded.sample_comment
                        """,
                        (
                            result["normalizedTemplate"], result["stablePrefix"], result["classification"],
                            result["classificationLabel"], result["classificationEvidence"],
                            result.get("classificationSource") or "learned", result["ruleVersion"],
                            observed_at, observed_at, comment,
                        ),
                    )
            finally:
                connection.close()

    def resolve(self, result: dict) -> dict:
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    """
                    select classification, classification_label, evidence, source
                    from learned_ea_comment_patterns where normalized_template = ?
                    """,
                    (result.get("normalizedTemplate"),),
                ).fetchone()
            finally:
                connection.close()
        if not row or row[3] != "manual":
            return result
        category, label, evidence, source = row
        return {
            **result,
            "classification": category,
            "classificationLabel": label,
            "classificationEvidence": evidence,
            "classificationSource": source,
            "countedAsEa": category in {"exact_ea", "dynamic_ea"},
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


def _sql_like_prefix(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def ea_comment_parts(value: object) -> list[str]:
    """Return useful, suffix-normalized comment values without inventing EA identity."""

    values = []
    for part in _text(value).split(" / "):
        if _EXIT_ONLY_COMMENT_RE.fullmatch(part.strip()):
            continue
        comment = _strip_comment_suffix(part)
        if classify_ea_comment(comment)["classification"] == "system_excluded":
            continue
        normalized = comment.casefold()
        if normalized not in {item.casefold() for item in values}:
            values.append(comment)
    return values


def ea_comment_identity(comment: object, expert_id: object = "", *, ea_hint: bool = True) -> dict:
    """Build the exact identity used by the mandatory first lookup stage."""

    result = classify_ea_comment(comment, ea_hint=ea_hint)
    value = result["normalizedComment"]
    expert = _integer(expert_id)
    return {
        **result,
        "comment": value,
        # An exact Comment is the EA lookup key. ExpertID/MAGIC varies between
        # accounts and is retained only as row-level evidence, never as a
        # second grouping key.
        "signatureKey": f"exact:{value.casefold()}",
        "signatureType": "exact-comment",
        "commentFamily": "",
        "expertId": expert,
    }


def ea_match_evidence(seed: dict, target: dict, matched_expert_id: object) -> dict | None:
    """Return an auditable clue when a target row satisfies the server-aware EA rule."""

    origin_server = _text(seed.get("originServer"))
    target_server = _text(target.get("server") or target.get("name"))
    same_server = bool(origin_server and target_server and origin_server.casefold() == target_server.casefold())
    expected_expert = _integer(seed.get("expertId"))
    matched_expert = _integer(matched_expert_id)
    dynamic = seed.get("signatureType") == "dynamic-template"
    possible_route = seed.get("classification") == "possible_copy_route"
    if dynamic and not possible_route and expected_expert > 0 and matched_expert != expected_expert:
        return None

    platform = _text(target.get("platform") or seed.get("originPlatform")).upper()
    expert_label = "MAGIC" if platform == "MT4" else "ExpertID"
    comment_value = _text(seed.get("normalizedTemplate") if dynamic else seed.get("comment"))
    comment_label = "动态 Comment 模板" if dynamic else "Comment"
    if same_server:
        clue = f"同服务器：{comment_label}「{comment_value}」相同"
        scope = "same-server-comment"
        if matched_expert > 0:
            clue += f"（{expert_label} {matched_expert}）"
    else:
        clue = f"跨服务器：{comment_label}「{comment_value}」相同"
        scope = "cross-server-comment"
        if dynamic and not possible_route:
            clue += f"，{expert_label} {expected_expert} 相同"
            scope = "cross-server-dynamic-comment-expert"
    return {
        "matchClue": clue,
        "matchScope": scope,
        "matchedExpertId": matched_expert,
    }


def ea_comment_query_values(comments: list[str]) -> list[str]:
    values = []
    for comment in comments:
        for value in (comment, f"{comment}[tp]", f"{comment}[sl]", f"{comment}[so]"):
            if value.casefold() not in {item.casefold() for item in values}:
                values.append(value)
    return values


def ea_comment_query_plan(comments: list[str]) -> tuple[list[str], list[str]]:
    """Return exact values first and dynamic templates available only as fallback."""

    exact_comments = list(dict.fromkeys(_text(comment) for comment in comments if _text(comment)))
    dynamic_patterns = []
    for comment in exact_comments:
        result = classify_ea_comment(comment, ea_hint=True)
        if result["dynamicEligible"] and result["normalizedTemplate"] not in dynamic_patterns:
            dynamic_patterns.append(result["normalizedTemplate"])
    return ea_comment_query_values(exact_comments), dynamic_patterns


def ea_dynamic_identity(seed: dict) -> dict:
    """Convert an exact seed to its structural fallback identity."""

    template = _text(seed.get("normalizedTemplate"))
    expert = _integer(seed.get("expertId"))
    category = _text(seed.get("classification"))
    expert_key = 0 if category == "possible_copy_route" else expert
    return {
        **seed,
        "comment": template,
        "signatureKey": f"dynamic:{category}:{template.casefold()}:{expert_key}",
        "signatureType": "dynamic-template",
        "originalComment": _text(seed.get("comment")),
    }


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


def ea_group_summary(groups: list[dict]) -> dict:
    accounts = {
        (_text(member.get("database")), _text(member.get("server")), _text(member.get("account")))
        for group in groups
        for member in group.get("members", [])
        if _text(member.get("account"))
    }
    return {
        "groups": len(groups),
        "accounts": len(accounts),
        "orders": sum(_integer((group.get("totals") or {}).get("orders")) for group in groups),
        "volume": round(sum(_number((group.get("totals") or {}).get("volume")) for group in groups), 4),
        "netProfit": round(sum(_number((group.get("totals") or {}).get("netProfit")) for group in groups), 2),
    }


def ea_expert_sequence_match(
    seed_events: list[dict],
    candidate_events: list[dict],
    *,
    min_shared: int = _EXPERT_SEQUENCE_MIN_SHARED,
    min_overlap: float = _EXPERT_SEQUENCE_MIN_OVERLAP,
    time_tolerance_seconds: float = _EXPERT_SEQUENCE_TIME_TOLERANCE_SECONDS,
    min_time_points: int = _EXPERT_SEQUENCE_MIN_TIME_POINTS,
    min_span_seconds: float = _EXPERT_SEQUENCE_MIN_SPAN_SECONDS,
) -> dict | None:
    """Return a conservative no-comment ExpertID sequence match, never a prefix match."""

    if not seed_events or not candidate_events:
        return None
    candidates_by_expert: dict[int, list[tuple[int, dict]]] = defaultdict(list)
    for index, event in enumerate(candidate_events):
        expert_id = _integer(event.get("expertId"))
        opened = event.get("openTime")
        if expert_id > 0 and isinstance(opened, datetime):
            candidates_by_expert[expert_id].append((index, event))

    used_candidates: set[int] = set()
    matches: list[dict] = []
    ordered_seeds = sorted(
        (event for event in seed_events if isinstance(event.get("openTime"), datetime)),
        key=lambda event: event["openTime"],
    )
    for seed in ordered_seeds:
        expert_id = _integer(seed.get("expertId"))
        seed_time = seed["openTime"]
        symbol = _text(seed.get("symbol")).casefold()
        action = _integer(seed.get("action"))
        eligible = []
        for candidate_index, candidate in candidates_by_expert.get(expert_id, []):
            if candidate_index in used_candidates:
                continue
            if _text(candidate.get("symbol")).casefold() != symbol or _integer(candidate.get("action")) != action:
                continue
            delta = abs((candidate["openTime"] - seed_time).total_seconds())
            if delta <= time_tolerance_seconds:
                eligible.append((delta, candidate_index, candidate))
        if not eligible:
            continue
        delta, candidate_index, candidate = min(eligible, key=lambda item: (item[0], item[1]))
        used_candidates.add(candidate_index)
        matches.append({
            "expertId": expert_id,
            "seed": seed,
            "candidate": candidate,
            "timeDeltaSeconds": delta,
        })

    shared_expert_ids = sorted({match["expertId"] for match in matches})
    seed_overlap = len(matches) / len(seed_events)
    candidate_overlap = len(matches) / len(candidate_events)
    matched_times = sorted({match["seed"]["openTime"].replace(microsecond=0) for match in matches})
    span_seconds = (matched_times[-1] - matched_times[0]).total_seconds() if len(matched_times) >= 2 else 0.0
    if (
        len(shared_expert_ids) < min_shared
        or seed_overlap < min_overlap
        or candidate_overlap < min_overlap
        or len(matched_times) < min_time_points
        or span_seconds < min_span_seconds
    ):
        return None
    return {
        "matches": matches,
        "sharedExpertIds": shared_expert_ids,
        "sharedCount": len(shared_expert_ids),
        "seedOverlap": round(seed_overlap, 4),
        "candidateOverlap": round(candidate_overlap, 4),
        "timePointCount": len(matched_times),
        "spanSeconds": span_seconds,
        "maxTimeDeltaSeconds": max((match["timeDeltaSeconds"] for match in matches), default=0.0),
    }


class EaCommentGroupService:
    """Read-only same-comment EA lookup and realized-profit aggregation."""

    def __init__(self, runtime: Any):
        self.runtime = runtime
        pattern_path = getattr(runtime, "EA_PATTERN_DB_PATH", None)
        self.pattern_store = EaCommentPatternStore(Path(pattern_path)) if pattern_path else None

    def _source_identity(self, source: dict) -> dict:
        r = self.runtime
        name = r.normalize_text(source.get("name"))
        database = "AC" if name.upper().startswith("AC") else "DBG" if name.upper().startswith("DBG") else name
        return {
            "database": database,
            "platform": r.normalize_text(source.get("platform")),
            "server": r.normalize_text(source.get("server") or name),
            "source": name,
        }

    def _annotate_seeds(self, source: dict, seeds: list[dict]) -> list[dict]:
        identity = self._source_identity(source)
        annotated = []
        for seed in seeds:
            seed_identity = ea_comment_identity(seed.get("comment"), seed.get("expertId"))
            signature_key = _text(seed.get("signatureKey")) or seed_identity["signatureKey"]
            annotated.append({
                **seed,
                "signatureKey": f"{signature_key}|origin:{identity['server'].casefold()}",
                "originDatabase": identity["database"],
                "originPlatform": identity["platform"],
                "originServer": identity["server"],
                "originSource": identity["source"],
            })
        return annotated

    def _seed_scope_bounds(self, seeds: list[dict]) -> tuple[datetime | None, datetime | None, bool]:
        """Return the optional user-selected opening-time scope carried by EA seeds."""

        r = self.runtime
        start_values = [
            value for value in (r.parse_trade_time(item.get("scopeStart")) for item in seeds if item.get("scopeStart"))
            if value
        ]
        end_values = [
            value for value in (r.parse_trade_time(item.get("scopeEnd")) for item in seeds if item.get("scopeEnd"))
            if value
        ]
        selected = bool(start_values or end_values)
        return (
            min(start_values, default=None),
            max(end_values, default=None),
            selected,
        )

    def _routed_accounts(self, cur: Any, source: dict, accounts: set[str]) -> set[str]:
        route = source.get("account_route")
        if not isinstance(route, dict):
            return accounts
        schema = _text(route.get("schema"))
        server_code = _text(route.get("mt_server_code"))
        numeric_accounts = sorted({int(account) for account in accounts if _text(account).isdigit()})
        if not schema or not server_code or not numeric_accounts:
            return accounts
        routed: set[str] = set()
        for batch in _batches(numeric_accounts, 500):
            placeholders = ",".join(["%s"] * len(batch))
            cur.execute(
                f"select mt_login from `{schema}`.`mt_users_account` "
                f"where mt_server_code = %s and mt_login in ({placeholders})",
                (server_code, *batch),
            )
            routed.update(_text(row.get("mt_login")) for row in cur.fetchall() if _text(row.get("mt_login")))
        return routed

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
            ea_hint = bool(r.is_ea_trade(row))
            raw_value = row.get("open_comment") or row.get("comment")
            row_signatures: set[str] = set()
            for raw_comment in ea_comment_parts(raw_value):
                classification = classify_ea_comment(raw_comment, ea_hint=ea_hint)
                if self.pattern_store and classification["classification"] != "system_excluded":
                    classification = self.pattern_store.resolve(classification)
                category = classification["classification"]
                if category == "system_excluded":
                    continue
                contact_comment = classification.get("classificationSource") == "contact"
                if category != "possible_copy_route" and (not ea_hint or r.is_copy_trade(row)) and not contact_comment:
                    continue
                identity = {
                    **ea_comment_identity(raw_comment, row.get("expert_id"), ea_hint=ea_hint),
                    **classification,
                }
                if self.pattern_store:
                    self.pattern_store.observe(classification, raw_comment, r.now_text())
                key = identity["signatureKey"]
                if key in row_signatures:
                    continue
                row_signatures.add(key)
                item = grouped.setdefault(key, {
                    **identity,
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
        grouped: dict[tuple[str, str, str, str], dict] = {}
        for row in records:
            account = r.normalize_text(row.get("account"))
            comment = r.normalize_text(row.get("comment"))
            if not account or not comment:
                continue
            database = r.normalize_text(row.get("database"))
            server = r.normalize_text(row.get("server"))
            signature_key = r.normalize_text(row.get("signatureKey")) or f"exact:{comment.casefold()}:0"
            key = (signature_key, database, server, account)
            item = grouped.setdefault(key, {
                "account": account,
                "comment": comment,
                "signatureKey": signature_key,
                "database": database,
                "platform": r.normalize_text(row.get("platform")),
                "server": server,
                "source": r.normalize_text(row.get("source")),
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
                "expertIds": set(),
                "matchClues": set(),
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
            expert_id = r.normalize_text(row.get("matchedExpertId"))
            if expert_id:
                item["expertIds"].add(expert_id)
            match_clue = r.normalize_text(row.get("matchClue"))
            if match_clue:
                item["matchClues"].add(match_clue)
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
            item["expertIds"] = sorted(item["expertIds"], key=lambda value: (_integer(value), value))
            item["matchClues"] = sorted(item["matchClues"])
            item["matchClue"] = "；".join(item["matchClues"])
            item["isCurrentAccount"] = item["account"] == current_account
            results.append(item)
        results.sort(key=lambda item: (
            item["comment"].casefold(), not item["isCurrentAccount"], item["database"], item["server"],
            -item["orders"], item["account"],
        ))
        return results

    def _query_mt4(self, source: dict, seeds: list[dict], row_limit: int) -> tuple[list[dict], bool, list[str]]:
        r = self.runtime
        seeds = [item for item in seeds if item.get("signatureType") != "dynamic-template"]
        comments = [item["comment"] for item in seeds]
        if not comments:
            return [], False, []
        query_comments = ea_comment_query_values(comments)
        scope_start, scope_end, selected_scope = self._seed_scope_bounds(seeds)
        start = scope_start if selected_scope else min((r.parse_trade_time(item.get("firstTime")) for item in seeds), default=None)
        end = scope_end if selected_scope else max((r.parse_trade_time(item.get("lastTime")) for item in seeds), default=None)
        if not selected_scope and (not start or not end):
            return [], False, ["MT4 同备注查询缺少有效交易时间范围"]
        placeholders = ",".join(["%s"] * len(query_comments))
        time_clauses: list[str] = []
        parameters: list[object] = []
        if start:
            time_clauses.append("OPEN_TIME >= %s")
            parameters.append(start)
        if end:
            time_clauses.append("OPEN_TIME <= %s")
            parameters.append(end)
        sql = f"""
            select TICKET, LOGIN, SYMBOL, VOLUME, OPEN_TIME, CLOSE_TIME,
                   PROFIT, COMMISSION, SWAPS, TAXES, COMMENT, MAGIC
            from `{source['schema']}`.`{source['table']}`
            where {' and '.join(time_clauses)}
              and CMD in (0,1) and COMMENT in ({placeholders})
            order by OPEN_TIME, TICKET
            limit %s
        """
        with r.mysql_trade_connect(source) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, [*parameters, *query_comments, row_limit + 1])
                raw_rows = cur.fetchall()
                truncated = len(raw_rows) > row_limit
                raw_rows = raw_rows[:row_limit]
                accounts = {r.normalize_text(row.get("LOGIN")) for row in raw_rows}
                routed_accounts = self._routed_accounts(cur, source, accounts)
                raw_rows = [row for row in raw_rows if r.normalize_text(row.get("LOGIN")) in routed_accounts]
                accounts = {r.normalize_text(row.get("LOGIN")) for row in raw_rows}
                metadata = r._copy_follower_money_meta(cur, source, accounts)
        records = []
        source_identity = self._source_identity(source)
        seeds_by_comment: dict[str, list[dict]] = defaultdict(list)
        for seed in seeds:
            seeds_by_comment[_text(seed.get("comment")).casefold()].append(seed)
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
            for matched_comment in matched_comments:
                for seed in seeds_by_comment.get(matched_comment.casefold(), []):
                    evidence = ea_match_evidence(seed, source_identity, row.get("MAGIC"))
                    if not evidence:
                        continue
                    records.append({
                        **source_identity,
                        **evidence,
                        "signatureKey": seed["signatureKey"],
                        "account": account,
                        "comment": seed["comment"],
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
        if selected_scope:
            scope_text = f"{start:%Y-%m-%d %H:%M:%S}" if start else "最早"
            scope_text += f" 至 {end:%Y-%m-%d %H:%M:%S}" if end else " 至 最新"
            limitations = [f"MT4 备注列无独立索引，结果按选择的开仓时间范围 {scope_text} 查询"]
        else:
            limitations = [
                f"MT4 备注列无独立索引，结果按当前账号使用区间 {start:%Y-%m-%d %H:%M:%S} 至 {end:%Y-%m-%d %H:%M:%S} 查询"
            ]
        return records, truncated, limitations

    def _query_mt4_dynamic(self, source: dict, seeds: list[dict], row_limit: int) -> tuple[list[dict], bool, list[str]]:
        r = self.runtime
        records: list[dict] = []
        truncated = False
        source_identity = self._source_identity(source)
        for seed in seeds:
            scope_start, scope_end, selected_scope = self._seed_scope_bounds([seed])
            start = scope_start if selected_scope else r.parse_trade_time(seed.get("firstTime"))
            end = scope_end if selected_scope else r.parse_trade_time(seed.get("lastTime"))
            prefix = r.normalize_text(seed.get("stablePrefix"))
            if (not selected_scope and (not start or not end)) or not prefix:
                continue
            route = seed.get("classification") == "possible_copy_route"
            expert_id = _integer(seed.get("expertId"))
            magic_clause = "" if route or expert_id <= 0 else " and MAGIC = %s"
            time_clauses: list[str] = []
            parameters: list[object] = []
            if start:
                time_clauses.append("OPEN_TIME >= %s")
                parameters.append(start)
            if end:
                time_clauses.append("OPEN_TIME <= %s")
                parameters.append(end)
            parameters.append(f"{_sql_like_prefix(prefix)}%")
            if magic_clause:
                parameters.append(expert_id)
            parameters.append(row_limit + 1)
            with r.mysql_trade_connect(source) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        select TICKET, LOGIN, SYMBOL, VOLUME, OPEN_TIME, CLOSE_TIME,
                               PROFIT, COMMISSION, SWAPS, TAXES, COMMENT, MAGIC
                        from `{source['schema']}`.`{source['table']}`
                        where {' and '.join(time_clauses)}
                          and CMD in (0,1) and COMMENT like %s escape '!'{magic_clause}
                        order by OPEN_TIME, TICKET
                        limit %s
                        """,
                        parameters,
                    )
                    raw_rows = cur.fetchall()
                    truncated = truncated or len(raw_rows) > row_limit
                    raw_rows = raw_rows[:row_limit]
                    routed_accounts = self._routed_accounts(
                        cur, source, {r.normalize_text(row.get("LOGIN")) for row in raw_rows}
                    )
                    raw_rows = [
                        row for row in raw_rows
                        if r.normalize_text(row.get("LOGIN")) in routed_accounts
                    ]
                    metadata = r._copy_follower_money_meta(
                        cur, source, {r.normalize_text(row.get("LOGIN")) for row in raw_rows}
                    )
            expected_template = r.normalize_text(seed.get("normalizedTemplate")).casefold()
            expected_category = r.normalize_text(seed.get("classification"))
            for row in raw_rows:
                opened = r.parse_trade_time(row.get("OPEN_TIME"))
                closed = r.parse_trade_time(row.get("CLOSE_TIME"))
                if not opened or not closed or closed <= datetime(1971, 1, 2) or closed < opened:
                    continue
                classified = classify_ea_comment(row.get("COMMENT"), ea_hint=True)
                if (
                    r.normalize_text(classified.get("normalizedTemplate")).casefold() != expected_template
                    or r.normalize_text(classified.get("classification")) != expected_category
                ):
                    continue
                evidence = ea_match_evidence(seed, source_identity, row.get("MAGIC"))
                if not evidence:
                    continue
                account = r.normalize_text(row.get("LOGIN"))
                meta = metadata.get(account) or r.account_money_meta(source_name=source.get("name"))
                scale = r.numeric_value(meta.get("moneyScale")) or 1.0
                gross = r.numeric_value(row.get("PROFIT")) * scale
                commission = r.numeric_value(row.get("COMMISSION")) * scale
                swap = r.numeric_value(row.get("SWAPS")) * scale
                taxes = r.numeric_value(row.get("TAXES")) * scale
                records.append({
                    **source_identity,
                    **evidence,
                    "signatureKey": seed["signatureKey"],
                    "account": account,
                    "comment": seed["comment"],
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
        limitations = ["MT4 动态格式回退按当前账号观察区间和稳定前缀执行只读查询"] if seeds else []
        return records, truncated, limitations

    def _dynamic_discovery_cache_key(self, source: dict, seed: dict) -> tuple:
        expert = 0 if seed.get("classification") == "possible_copy_route" else _integer(seed.get("expertId"))
        return (
            _text(source.get("host")), _text(source.get("schema")),
            _text(seed.get("normalizedTemplate")).casefold(), expert,
            _text(seed.get("scopeStart")), _text(seed.get("scopeEnd")),
        )

    def _dynamic_discovery_patterns(self, source: dict, stable_prefix: str) -> list[str]:
        if (
            _text(source.get("schema")) != "sass_crm_ac_mt5_live"
            or not re.fullmatch(r"@\d+@", stable_prefix)
        ):
            return [f"{_sql_like_prefix(stable_prefix)}%"]
        two_digit = [f"{stable_prefix}{value:02d}%" for value in range(100)]
        one_digit = [f"{stable_prefix}{value}@%" for value in range(10)]
        return [*two_digit, *one_digit]

    def _query_dynamic_pattern_batch(
        self,
        source: dict,
        patterns: list[str],
        seed: dict,
        shard_limit: int = 5000,
    ) -> tuple[list[dict], list[str]]:
        r = self.runtime
        last_error: Exception | None = None
        route = seed.get("classification") == "possible_copy_route"
        expert_id = _integer(seed.get("expertId"))
        scope_start, scope_end, _selected_scope = self._seed_scope_bounds([seed])
        for _attempt in range(2):
            try:
                rows: list[dict] = []
                truncated: list[str] = []
                with r.mysql_trade_connect(source) as conn:
                    with conn.cursor() as cur:
                        def query_pattern(pattern: str, depth: int = 0) -> None:
                            expert_clause = "" if route or expert_id <= 0 else " and ExpertID = %s"
                            parameters: list[object] = [pattern]
                            if expert_clause:
                                parameters.append(expert_id)
                            time_clause = ""
                            if scope_start:
                                time_clause += " and Time >= %s"
                                parameters.append(scope_start)
                            if scope_end:
                                time_clause += " and Time <= %s"
                                parameters.append(scope_end)
                            parameters.append(shard_limit + 1)
                            cur.execute(
                                f"""
                                    select Login, PositionID, Comment, ExpertID
                                    from `{source['schema']}`.`{source['table']}`
                                    where Comment like %s escape '!'{expert_clause}{time_clause}
                                      and Action in (0,1) and Entry = 0 and PositionID <> 0
                                    limit %s
                                """,
                                parameters,
                            )
                            shard_rows = cur.fetchall()
                            if len(shard_rows) <= shard_limit:
                                rows.extend(shard_rows)
                                return
                            if depth >= 8 or not pattern.endswith("%"):
                                truncated.append(pattern)
                                return
                            base = pattern[:-1]
                            children = [f"{base}{digit}%" for digit in range(10)]
                            if base.startswith("@"):
                                children.append(f"{base}@%")
                            for child in children:
                                query_pattern(child, depth + 1)

                        for pattern in patterns:
                            query_pattern(pattern)
                return rows, truncated
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"动态 EA 分片查询失败: {last_error}") from last_error

    def _discover_dynamic_positions_many(
        self,
        source: dict,
        seeds: list[dict],
    ) -> dict[tuple[str, int], set[tuple[str, str]]]:
        r = self.runtime
        requested = {
            r.normalize_text(seed.get("signatureKey")): seed
            for seed in seeds
            if r.normalize_text(seed.get("stablePrefix")) and r.normalize_text(seed.get("normalizedTemplate"))
        }
        results: dict[str, set[tuple[str, str]]] = {}
        missing: list[dict] = []
        now = time.monotonic()
        with _DYNAMIC_DISCOVERY_CACHE_LOCK:
            for signature_key, seed in requested.items():
                cached = _DYNAMIC_DISCOVERY_CACHE.get(self._dynamic_discovery_cache_key(source, seed))
                if cached and now - cached[0] <= _DYNAMIC_DISCOVERY_CACHE_TTL:
                    results[signature_key] = set(cached[1])
                else:
                    missing.append(seed)

        for seed in missing:
            stable_prefix = r.normalize_text(seed.get("stablePrefix"))
            patterns = self._dynamic_discovery_patterns(source, stable_prefix)
            worker_count = min(12, len(patterns))
            batches = [patterns[index::worker_count] for index in range(worker_count)]
            raw_rows: list[dict] = []
            truncated_patterns: list[str] = []
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="ea-dynamic-shard") as executor:
                futures = [
                    executor.submit(self._query_dynamic_pattern_batch, source, batch, seed)
                    for batch in batches
                ]
                for future in as_completed(futures):
                    rows, truncated = future.result()
                    raw_rows.extend(rows)
                    truncated_patterns.extend(truncated)
            if truncated_patterns:
                raise RuntimeError(f"动态 EA 分片仍超过安全上限: {', '.join(truncated_patterns[:3])}")

            discovered: set[tuple[str, str]] = set()
            template = r.normalize_text(seed.get("normalizedTemplate")).casefold()
            category = r.normalize_text(seed.get("classification"))
            for row in raw_rows:
                comment = r.normalize_text(row.get("Comment"))
                classified = classify_ea_comment(comment, ea_hint=True)
                if (
                    r.normalize_text(classified.get("normalizedTemplate")).casefold() != template
                    or r.normalize_text(classified.get("classification")) != category
                ):
                    continue
                key = (r.normalize_text(row.get("Login")), r.normalize_text(row.get("PositionID")))
                if key[0] and key[1] and key[1] != "0":
                    discovered.add(key)
            signature_key = r.normalize_text(seed.get("signatureKey"))
            with _DYNAMIC_DISCOVERY_CACHE_LOCK:
                results[signature_key] = discovered
                cache_key = self._dynamic_discovery_cache_key(source, seed)
                _DYNAMIC_DISCOVERY_CACHE[cache_key] = (time.monotonic(), frozenset(discovered))
        return results

    def _normalized_expert_sequence_events(self, rows: list[dict]) -> list[dict]:
        r = self.runtime
        events: dict[str, dict] = {}
        for row in rows:
            if not r.is_ea_trade(row) or r.is_copy_trade(row):
                continue
            opening_comment = row.get("open_comment")
            if opening_comment is None:
                opening_comment = row.get("comment")
            if ea_comment_parts(opening_comment):
                continue
            expert_id = _integer(row.get("expert_id"))
            opened = r.parse_trade_time(row.get("open_time_msc") or row.get("open_time"))
            ticket = r.normalize_text(row.get("ticket"))
            trade_type = r.normalize_text(row.get("type")).casefold()
            action = 0 if trade_type == "buy" else 1 if trade_type == "sell" else _integer(row.get("action"))
            symbol = r.normalize_text(row.get("symbol"))
            if expert_id <= 0 or not opened or not ticket or not symbol or action not in {0, 1}:
                continue
            events.setdefault(ticket, {
                "account": r.normalize_text(row.get("account")),
                "positionId": ticket,
                "expertId": expert_id,
                "openTime": opened,
                "symbol": symbol,
                "action": action,
            })
        ordered = sorted(events.values(), key=lambda event: event["openTime"], reverse=True)
        if not ordered:
            return []
        cutoff = ordered[0]["openTime"] - timedelta(days=_EXPERT_SEQUENCE_MAX_DAYS)
        ordered = [event for event in ordered if event["openTime"] >= cutoff][:_EXPERT_SEQUENCE_MAX_EVENTS]
        return sorted(ordered, key=lambda event: event["openTime"])

    def _raw_mt5_expert_event(self, row: dict) -> dict | None:
        r = self.runtime
        if ea_comment_parts(row.get("Comment")):
            return None
        expert_id = _integer(row.get("ExpertID"))
        opened = r.parse_trade_time(row.get("TimeMsc") or row.get("Time"))
        account = r.normalize_text(row.get("Login"))
        position_id = r.normalize_text(row.get("PositionID"))
        symbol = r.normalize_text(row.get("Symbol"))
        action = _integer(row.get("Action"))
        if expert_id <= 0 or not opened or not account or not position_id or position_id == "0" or not symbol:
            return None
        if action not in {0, 1}:
            return None
        return {
            "account": account,
            "positionId": position_id,
            "expertId": expert_id,
            "openTime": opened,
            "symbol": symbol,
            "action": action,
        }

    def _query_mt5_expert_sequence(
        self,
        source: dict,
        rows: list[dict],
        current_account: str,
        row_limit: int = 50000,
    ) -> list[dict]:
        r = self.runtime
        seed_events = self._normalized_expert_sequence_events(rows)
        distinct_seed_ids = sorted({event["expertId"] for event in seed_events})
        if len(distinct_seed_ids) < _EXPERT_SEQUENCE_MIN_SHARED:
            return []
        start = seed_events[0]["openTime"] - timedelta(seconds=_EXPERT_SEQUENCE_TIME_TOLERANCE_SECONDS)
        end = seed_events[-1]["openTime"] + timedelta(seconds=_EXPERT_SEQUENCE_TIME_TOLERANCE_SECONDS)

        discovered_rows: dict[tuple[str, str], dict] = {}
        with r.mysql_trade_connect(source) as conn:
            with conn.cursor() as cur:
                for expert_batch in _batches(distinct_seed_ids):
                    placeholders = ",".join(["%s"] * len(expert_batch))
                    cur.execute(
                        f"""
                        select Deal, Login, PositionID, Time, TimeMsc, Action, Symbol, Comment, ExpertID
                        from `{source['schema']}`.`{source['table']}`
                        where Time >= %s and Time <= %s
                          and Action in (0,1) and Entry = 0 and PositionID <> 0
                          and ExpertID in ({placeholders})
                        order by TimeMsc, Deal
                        limit %s
                        """,
                        [start, end, *expert_batch, row_limit + 1],
                    )
                    batch_rows = cur.fetchall()
                    if len(batch_rows) > row_limit:
                        raise RuntimeError("无备注 ExpertID 候选超过安全上限，已停止归组")
                    for row in batch_rows:
                        key = (r.normalize_text(row.get("Login")), r.normalize_text(row.get("PositionID")))
                        if key[0] and key[1] and key[1] != "0":
                            discovered_rows[key] = row
                routed_accounts = self._routed_accounts(
                    cur, source, {account for account, _position in discovered_rows}
                )
                discovered_rows = {
                    key: row for key, row in discovered_rows.items() if key[0] in routed_accounts
                }
                candidate_accounts = sorted(routed_accounts)
                all_candidate_rows: dict[tuple[str, str], dict] = {}
                for account_batch in _batches([int(account) for account in candidate_accounts if account.isdigit()], 100):
                    placeholders = ",".join(["%s"] * len(account_batch))
                    cur.execute(
                        f"""
                        select Deal, Login, PositionID, Time, TimeMsc, Action, Symbol, Comment, ExpertID
                        from `{source['schema']}`.`{source['table']}`
                        where Login in ({placeholders}) and Time >= %s and Time <= %s
                          and Action in (0,1) and Entry = 0 and PositionID <> 0 and ExpertID <> 0
                        order by Login, TimeMsc, Deal
                        limit %s
                        """,
                        [*account_batch, start, end, row_limit + 1],
                    )
                    batch_rows = cur.fetchall()
                    if len(batch_rows) > row_limit:
                        raise RuntimeError("无备注 ExpertID 账户交易超过安全上限，已停止归组")
                    for row in batch_rows:
                        key = (r.normalize_text(row.get("Login")), r.normalize_text(row.get("PositionID")))
                        if key[0] in routed_accounts and key[1] and key[1] != "0":
                            all_candidate_rows[key] = row

        candidate_events: dict[str, list[dict]] = defaultdict(list)
        for row in all_candidate_rows.values():
            event = self._raw_mt5_expert_event(row)
            if event:
                candidate_events[event["account"]].append(event)

        qualified: dict[str, dict] = {}
        for account, account_events in candidate_events.items():
            result = ea_expert_sequence_match(seed_events, account_events)
            if result:
                qualified[account] = result
        if current_account not in qualified or len(qualified) < 2:
            return []

        shared_ids = set(qualified[current_account]["sharedExpertIds"])
        for result in qualified.values():
            shared_ids.intersection_update(result["sharedExpertIds"])
        if len(shared_ids) < _EXPERT_SEQUENCE_MIN_SHARED:
            return []

        source_identity = self._source_identity(source)
        signature_key = f"expert-sequence:{source_identity['server'].casefold()}:{current_account}"
        seed = {
            "comment": "无备注 ExpertID 序列",
            "signatureKey": signature_key,
            "signatureType": "expert-sequence",
            "commentFamily": "",
            "expertId": "",
            "classification": "possible_copy_route",
            "classificationLabel": "可能是跟单路由",
            "countedAsEa": False,
            "normalizedComment": "无备注 ExpertID 序列",
            "normalizedTemplate": "无备注 ExpertID 序列",
            "stablePrefix": "",
            "classificationEvidence": "开仓备注为空；多个完整 ExpertID 重复，且交易时间、品种和方向高度一致",
            "dynamicEligible": False,
            "classificationSource": "builtin",
            "ruleVersion": _DYNAMIC_RULE_VERSION,
            "originDatabase": source_identity["database"],
            "originPlatform": source_identity["platform"],
            "originServer": source_identity["server"],
            "originSource": source_identity["source"],
            "sharedExpertIds": sorted(shared_ids),
            "expertSequence": {
                "minimumShared": _EXPERT_SEQUENCE_MIN_SHARED,
                "minimumOverlap": _EXPERT_SEQUENCE_MIN_OVERLAP,
                "timeToleranceSeconds": _EXPERT_SEQUENCE_TIME_TOLERANCE_SECONDS,
                "sharedAcrossAllAccounts": len(shared_ids),
            },
        }
        positions: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
        for account, result in qualified.items():
            clue = (
                f"同服务器：共享 {result['sharedCount']} 个完整 ExpertID，"
                f"双向覆盖 {result['seedOverlap']:.0%}/{result['candidateOverlap']:.0%}，"
                f"开仓时间差不超过 {_EXPERT_SEQUENCE_TIME_TOLERANCE_SECONDS:g} 秒且品种/方向一致"
            )
            for match in result["matches"]:
                event = match["candidate"]
                key = (account, event["positionId"])
                positions[key][signature_key] = {
                    "seed": seed,
                    "evidence": {
                        "matchClue": clue,
                        "matchScope": "same-server-expert-sequence",
                        "matchedExpertId": event["expertId"],
                    },
                }
        records = self._mt5_records_for_positions(source, positions)
        return self._build_groups(
            [seed],
            records,
            current_account,
            source=source,
            limitations=[
                "仅在没有有效开仓 Comment 时启用；完整 ExpertID、时间、品种和方向共同匹配",
                "结果标记为可能是跟单路由，不计入 EA 汇总",
            ],
        )

    def _mt5_records_for_positions(self, source: dict, positions: dict[tuple[str, str], dict[str, dict]]) -> list[dict]:
        r = self.runtime
        source_identity = self._source_identity(source)
        deals_by_login: dict[str, list[dict]] = defaultdict(list)
        metadata: dict[str, dict] = {}
        position_ids = sorted({int(key[1]) for key in positions if key[1].isdigit()})
        with r.mysql_trade_connect(source) as conn:
            with conn.cursor() as cur:
                for batch in _batches(position_ids, _MT5_POSITION_QUERY_BATCH_SIZE):
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
                for match in positions.get(key, {}).values():
                    seed = match["seed"]
                    evidence = match["evidence"]
                    gross = r.numeric_value(trade.get("profit"))
                    commission = r.numeric_value(trade.get("commission")) + r.numeric_value(trade.get("fee"))
                    swap = r.numeric_value(trade.get("swap"))
                    taxes = r.numeric_value(trade.get("taxes"))
                    records.append({
                        **source_identity,
                        **evidence,
                        "signatureKey": seed["signatureKey"],
                        "account": account,
                        "comment": seed["comment"],
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
        return records

    def _query_mt5(self, source: dict, seeds: list[dict], row_limit: int) -> tuple[list[dict], bool, list[str]]:
        r = self.runtime
        exact_seeds = [item for item in seeds if item.get("signatureType") != "dynamic-template"]
        dynamic_seeds = [item for item in seeds if item.get("signatureType") == "dynamic-template"]
        positions: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
        truncated = False
        source_identity = self._source_identity(source)

        query_comments = ea_comment_query_values([item["comment"] for item in exact_seeds])
        if query_comments:
            scope_start, scope_end, _selected_scope = self._seed_scope_bounds(exact_seeds)
            time_clause = ""
            parameters: list[object] = [*query_comments]
            if scope_start:
                time_clause += " and Time >= %s"
                parameters.append(scope_start)
            if scope_end:
                time_clause += " and Time <= %s"
                parameters.append(scope_end)
            parameters.append(row_limit + 1)
            seed_sql = f"""
                select Deal, Login, PositionID, Comment, ExpertID
                from `{source['schema']}`.`{source['table']}`
                where Comment in ({','.join(['%s'] * len(query_comments))})
                  and Action in (0,1) and Entry = 0 and PositionID <> 0{time_clause}
                order by Deal
                limit %s
            """
            exact_by_key: dict[str, list[dict]] = defaultdict(list)
            for item in exact_seeds:
                exact_by_key[item["comment"].casefold()].append(item)
            with r.mysql_trade_connect(source) as conn:
                with conn.cursor() as cur:
                    cur.execute(seed_sql, parameters)
                    seed_rows = cur.fetchall()
                    routed_accounts = self._routed_accounts(
                        cur, source, {r.normalize_text(row.get("Login")) for row in seed_rows}
                    )
                    seed_rows = [
                        row for row in seed_rows
                        if r.normalize_text(row.get("Login")) in routed_accounts
                    ]
            truncated = len(seed_rows) > row_limit
            for row in seed_rows[:row_limit]:
                key = (r.normalize_text(row.get("Login")), r.normalize_text(row.get("PositionID")))
                for comment in ea_comment_parts(row.get("Comment")):
                    for seed in exact_by_key.get(comment.casefold(), []):
                        evidence = ea_match_evidence(seed, source_identity, row.get("ExpertID"))
                        if key[0] and key[1] and evidence:
                            positions[key][seed["signatureKey"]] = {"seed": seed, "evidence": evidence}

        discovered_positions = self._discover_dynamic_positions_many(source, dynamic_seeds)
        for seed in dynamic_seeds:
            signature = r.normalize_text(seed.get("signatureKey"))
            for key in discovered_positions.get(signature, set()):
                evidence = ea_match_evidence(seed, source_identity, seed.get("expertId"))
                if evidence:
                    positions[key][seed["signatureKey"]] = {"seed": seed, "evidence": evidence}

        if not positions:
            return [], truncated, []
        return self._mt5_records_for_positions(source, positions), truncated, []

    def _build_groups(
        self,
        seeds: list[dict],
        records: list[dict],
        current_account: str,
        *,
        source: dict | None = None,
        truncated: bool = False,
        limitations: list[str] | None = None,
    ) -> list[dict]:
        r = self.runtime
        unique_seeds: list[dict] = []
        seen_signatures: set[str] = set()
        for seed in seeds:
            signature = r.normalize_text(seed.get("signatureKey")).casefold()
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            unique_seeds.append(seed)
        seeds = unique_seeds
        members = self._summarize_records(records, current_account)
        by_signature: dict[str, list[dict]] = defaultdict(list)
        for member in members:
            by_signature[member["signatureKey"]].append(member)
        groups = []
        for seed in seeds:
            group_members = by_signature.get(seed["signatureKey"], [])
            if not group_members:
                group_members = [
                    member for member in members
                    if member["comment"].casefold() == seed["comment"].casefold()
                ]
            platforms = sorted({r.normalize_text(item.get("platform")) for item in group_members if r.normalize_text(item.get("platform"))})
            servers = sorted({r.normalize_text(item.get("server")) for item in group_members if r.normalize_text(item.get("server"))})
            databases = sorted({r.normalize_text(item.get("database")) for item in group_members if r.normalize_text(item.get("database"))})
            current_member = next((member for member in group_members if member["isCurrentAccount"]), None)
            current_summary = {}
            if current_member:
                current_summary = {
                    "currentOrders": current_member["orders"],
                    "currentVolume": current_member["volume"],
                    "currentNetProfit": current_member["netProfit"],
                    "firstTime": current_member["firstTime"],
                    "lastTime": current_member["lastTime"],
                }
            group = {
                **seed,
                **current_summary,
                "platform": platforms[0] if len(platforms) == 1 else "跨平台" if platforms else r.normalize_text((source or {}).get("platform")),
                "server": servers[0] if len(servers) == 1 else "跨库" if servers else r.normalize_text((source or {}).get("server") or (source or {}).get("name")),
                "database": databases[0] if len(databases) == 1 else " / ".join(databases),
                "platforms": platforms,
                "servers": servers,
                "databases": databases,
                "members": group_members,
                "totals": ea_comment_totals(group_members),
                "matchRule": (
                    "无有效开仓 Comment 时，同服务器至少共享 5 个完整 ExpertID，双向覆盖率至少 80%，且开仓时间、品种和方向一致；仅标记为可能是跟单路由。"
                    if seed.get("signatureType") == "expert-sequence"
                    else (
                        "同平台所有服务器按完整 Comment 相同聚合；ExpertID/MAGIC 仅作为每笔订单的辅助证据。"
                        if seed.get("signatureType") != "dynamic-template"
                        else (
                            "疑似跟单路由按结构模板匹配，不计入 EA 汇总。"
                            if seed.get("classification") == "possible_copy_route"
                            else "动态 Comment 按结构模板与 ExpertID/MAGIC 匹配；每个账户保留实际匹配线索。"
                        )
                    )
                ),
                "truncated": truncated,
                "limitations": list(limitations or []),
            }
            group["peerAccounts"] = max(0, group["totals"]["accounts"] - (1 if current_member else 0))
            if current_member and group["peerAccounts"] == 0:
                group["limitations"].append("当前账号已使用此 Comment，尚未找到其他账号")
            if group["totals"]["accounts"] >= 2 or current_member:
                groups.append(group)
        groups.sort(key=lambda group: (-group["totals"]["accounts"], -group["totals"]["orders"], group["comment"].casefold()))
        return groups[:20]

    def query_source(
        self,
        source: dict,
        rows: list[dict],
        current_account: str,
        row_limit: int = 50000,
        seeds: list[dict] | None = None,
    ) -> list[dict]:
        seeds = seeds if seeds is not None else self._seed_comments(self._source_rows(rows, source))
        if seeds and not all(_text(seed.get("originServer")) for seed in seeds):
            seeds = self._annotate_seeds(source, seeds)
        if not seeds:
            return []
        if source.get("kind") == "mt5_deals":
            records, truncated, limitations = self._query_mt5(source, seeds, row_limit)
        else:
            records, truncated, limitations = self._query_mt4(source, seeds, row_limit)
        return self._build_groups(
            seeds,
            records,
            current_account,
            source=source,
            truncated=truncated,
            limitations=limitations,
        )

    def _merge_seeds(self, seeds: list[dict]) -> list[dict]:
        r = self.runtime
        merged: dict[str, dict] = {}
        for seed in seeds:
            signature = r.normalize_text(seed.get("signatureKey"))
            # Exact Comments are global across every configured MT4/MT5
            # source. Dynamic templates remain platform/server-scoped because
            # their variable suffix is not a complete Comment identity.
            origin_scope = "" if seed.get("signatureType") == "exact-comment" else r.normalize_text(seed.get("originServer")).casefold()
            platform_scope = "" if seed.get("signatureType") == "exact-comment" else r.normalize_text(seed.get("originPlatform")).casefold()
            key = "|".join([
                platform_scope,
                origin_scope,
                signature,
            ])
            if key not in merged:
                merged[key] = dict(seed)
                continue
            item = merged[key]
            for field in ("currentOrders", "currentVolume", "currentNetProfit"):
                item[field] = r.numeric_value(item.get(field)) + r.numeric_value(seed.get(field))
            first = r.normalize_text(seed.get("firstTime"))
            last = r.normalize_text(seed.get("lastTime"))
            if first:
                item["firstTime"] = min(filter(None, [r.normalize_text(item.get("firstTime")), first]), default=first)
            if last:
                item["lastTime"] = max(r.normalize_text(item.get("lastTime")), last)
        for item in merged.values():
            item["currentOrders"] = _integer(item.get("currentOrders"))
            item["currentVolume"] = r.rounded(item.get("currentVolume"), 4)
            item["currentNetProfit"] = r.rounded(item.get("currentNetProfit"))
        return list(merged.values())

    def _dynamic_target_sources(self, origin_sources: list[dict]) -> list[dict]:
        candidates = [
            source for source in self.runtime.MYSQL_SOURCES
            if source.get("kind") == "mt5_deals" and _text(source.get("schema")) in _DYNAMIC_PRIMARY_SCHEMAS
        ]
        candidates.extend(source for source in origin_sources if source.get("kind") == "mt5_deals")
        unique: dict[tuple[str, str, str], dict] = {}
        for source in candidates:
            key = (_text(source.get("host")), _text(source.get("schema")), _text(source.get("table")))
            unique.setdefault(key, source)
        return list(unique.values())

    def _platform_target_sources(self, platform: str, origin_sources: list[dict]) -> list[dict]:
        platform = _text(platform).upper()
        candidates = list(origin_sources)
        candidates.extend(
            source for source in self.runtime.MYSQL_SOURCES
            if _text(source.get("platform")).upper() == platform
            and source.get("kind") in {"mt5_deals", "mt4_trades"}
        )
        unique: dict[tuple[str, str, str, str, str], dict] = {}
        for source in candidates:
            route = source.get("account_route") if isinstance(source.get("account_route"), dict) else {}
            key = (
                _text(source.get("host")), _text(source.get("schema")), _text(source.get("table")),
                _text(route.get("schema")), _text(route.get("mt_server_code")),
            )
            unique.setdefault(key, source)
        return list(unique.values())

    def _exact_target_sources(self) -> list[dict]:
        """All routed MT4/MT5 sources for an exact full-Comment lookup."""

        r = self.runtime
        unique: dict[tuple[str, str, str, str, str], dict] = {}
        for source in r.MYSQL_SOURCES:
            if source.get("kind") not in {"mt5_deals", "mt4_trades"}:
                continue
            route = source.get("account_route") if isinstance(source.get("account_route"), dict) else {}
            key = (
                _text(source.get("host")), _text(source.get("schema")), _text(source.get("table")),
                _text(route.get("schema")), _text(route.get("mt_server_code")),
            )
            unique.setdefault(key, source)
        return list(unique.values())

    def payload(self, login: str, filters: dict | None = None) -> dict:
        r = self.runtime
        filters = filters or {}
        login = r.normalize_text(login)
        if not login or not re.fullmatch(r"\d+", login):
            raise ValueError("账号格式无效")
        platform = r.normalize_text(filters.get("platform")).upper()
        server = r.normalize_text(filters.get("server"))
        start = r.normalize_text(filters.get("start"))
        end = r.normalize_text(filters.get("end"))
        rows = r.query_db_trades(
            login, platform=platform, server=server, start=start, end=end, limit=50000,
        )
        sources = [source for source in r.MYSQL_SOURCES if r.source_allowed(source, platform=platform, server=server)]
        all_source_seeds = []
        for source in sources:
            seeds = self._annotate_seeds(source, self._seed_comments(self._source_rows(rows, source)))
            all_source_seeds.append((source, [{**seed, "scopeStart": start, "scopeEnd": end} for seed in seeds]))
        commentless_sources = [
            (source, self._source_rows(rows, source))
            for source, seeds in all_source_seeds
            if not seeds and source.get("kind") == "mt5_deals"
        ]
        source_seeds = [(source, seeds) for source, seeds in all_source_seeds if seeds]
        groups: list[dict] = []
        errors: list[str] = []
        seeds_by_platform: dict[str, list[dict]] = defaultdict(list)
        origins_by_platform: dict[str, list[dict]] = defaultdict(list)
        for source, seeds in source_seeds:
            source_platform = r.normalize_text(source.get("platform")).upper()
            seeds_by_platform[source_platform].extend(seeds)
            origins_by_platform[source_platform].append(source)
        # One exact lookup receives every seed.  Its complete Comment key is
        # deliberately platform-agnostic, so a selected MT4 or MT5 account
        # searches the complete configured MT4/MT5 source set exactly once.
        all_exact_seeds = self._merge_seeds([
            seed
            for seeds in seeds_by_platform.values()
            for seed in seeds
        ])
        exact_by_platform = {"ALL": all_exact_seeds} if all_exact_seeds else {}
        exact_requests = [
            (source_platform, target, seeds)
            for source_platform, seeds in exact_by_platform.items()
            for target in self._exact_target_sources()
        ]
        request_count = len(exact_requests)
        exact_results = {
            source_platform: {"records": [], "truncated": False, "limitations": [], "failed": False}
            for source_platform in exact_by_platform
        }
        with ThreadPoolExecutor(
            max_workers=min(_GLOBAL_COMMENT_QUERY_MAX_WORKERS, request_count or 1),
            thread_name_prefix="ea-comment",
        ) as executor:
            futures = {}
            for source_platform, target, seeds in exact_requests:
                query = self._query_mt5 if target.get("kind") == "mt5_deals" else self._query_mt4
                futures[executor.submit(query, target, seeds, 50000)] = (source_platform, target)
            for future in as_completed(futures):
                source_platform, source = futures[future]
                try:
                    records, truncated, limitations = future.result()
                    exact_results[source_platform]["records"].extend(records)
                    exact_results[source_platform]["truncated"] |= truncated
                    exact_results[source_platform]["limitations"].extend(limitations)
                except Exception as exc:
                    exact_results[source_platform]["failed"] = True
                    errors.append(f"{source.get('name')}: {exc}")
        exact_groups_by_platform: dict[str, list[dict]] = {}
        for source_platform, result in exact_results.items():
            exact_groups = self._build_groups(
                exact_by_platform[source_platform],
                result["records"],
                login,
                truncated=result["truncated"],
                limitations=list(dict.fromkeys(result["limitations"])),
            )
            exact_groups_by_platform[source_platform] = exact_groups
            groups.extend(exact_groups)

        # Dynamic recognition is a strict fallback. An exact provider error blocks it so that
        # incomplete exact data cannot be mistaken for an absent peer group.
        fallback_by_platform: dict[str, list[dict]] = {}
        for source_platform, seeds in exact_by_platform.items():
            if exact_results[source_platform]["failed"]:
                continue
            matched = {r.normalize_text(group.get("signatureKey")) for group in exact_groups_by_platform[source_platform]}
            fallback = [
                ea_dynamic_identity(seed)
                for seed in seeds
                if r.normalize_text(seed.get("signatureKey")) not in matched and bool(seed.get("dynamicEligible"))
            ]
            fallback = self._merge_seeds(fallback)
            if fallback:
                fallback_by_platform[source_platform] = fallback[:20]

        dynamic_results = {
            source_platform: {"records": [], "truncated": False, "limitations": [], "failed": False}
            for source_platform in fallback_by_platform
        }
        dynamic_requests = []
        for source_platform, seeds in fallback_by_platform.items():
            targets = self._exact_target_sources()
            dynamic_requests.extend((source_platform, target, seeds) for target in targets)
        with ThreadPoolExecutor(
            max_workers=min(_GLOBAL_COMMENT_QUERY_MAX_WORKERS, len(dynamic_requests) or 1),
            thread_name_prefix="ea-format",
        ) as executor:
            futures = {}
            for source_platform, target, seeds in dynamic_requests:
                query = self._query_mt5 if target.get("kind") == "mt5_deals" else self._query_mt4_dynamic
                futures[executor.submit(query, target, seeds, 50000)] = (source_platform, target)
            for future in as_completed(futures):
                source_platform, source = futures[future]
                try:
                    records, truncated, limitations = future.result()
                    dynamic_results[source_platform]["records"].extend(records)
                    dynamic_results[source_platform]["truncated"] |= truncated
                    dynamic_results[source_platform]["limitations"].extend(limitations)
                except Exception as exc:
                    dynamic_results[source_platform]["failed"] = True
                    errors.append(f"{source.get('name')} 动态格式: {exc}")
        for source_platform, result in dynamic_results.items():
            if result["failed"]:
                continue
            groups.extend(self._build_groups(
                fallback_by_platform[source_platform],
                result["records"],
                login,
                truncated=result["truncated"],
                limitations=list(dict.fromkeys([
                    *result["limitations"],
                    "仅在精确 Comment 未找到有效同类账户后启用动态格式回退",
                ])),
            ))

        # A separate conservative fallback handles EA executions whose authoritative opening
        # Comment is empty. It is same-server only and never promotes the result to an EA family.
        with ThreadPoolExecutor(
            max_workers=min(4, len(commentless_sources) or 1), thread_name_prefix="ea-expert-sequence"
        ) as executor:
            futures = {
                executor.submit(self._query_mt5_expert_sequence, source, source_rows, login): source
                for source, source_rows in commentless_sources
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    groups.extend(future.result())
                except Exception as exc:
                    errors.append(f"{source.get('name')} 无备注 ExpertID 序列: {exc}")
        source_order = {r.normalize_text(source.get("name")): index for index, source in enumerate(r.MYSQL_SOURCES)}
        groups.sort(key=lambda group: (
            not bool(group.get("countedAsEa")),
            source_order.get(r.normalize_text(group.get("server")), len(source_order)),
            -group["totals"]["accounts"],
            -group["totals"]["orders"],
            group["comment"].casefold(),
        ))
        ea_groups = [group for group in groups if group.get("countedAsEa")]
        route_groups = [group for group in groups if group.get("classification") == "possible_copy_route"]
        return {
            "ok": True,
            "account": login,
            "detected": bool(groups),
            "groups": groups,
            "eaSummary": ea_group_summary(ea_groups),
            "possibleCopyRouteSummary": ea_group_summary(route_groups),
            "errors": errors[:8],
            "definition": "先按完整 Comment 精确查询；仅在精确查询成功但没有有效同类账户时启用动态格式识别。没有有效开仓 Comment 时，可按同服务器完整 ExpertID 序列及交易一致性保守关联。平台事件、强平、出入金和纯联系方式不参与识别；疑似跟单路由保留明细但不计入 EA 组数或 EA 盈亏。净盈亏包含手续费、Fee、利息和税费。",
            "refreshedAt": r.now_text(),
        }
