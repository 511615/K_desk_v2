from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime
from typing import Any

LegacyCall = Callable[..., dict[str, Any]]


RELATION_TYPES = {
    "same_crm_user": "同 CRM 客户",
    "login_ip": "登录 IP",
    "ea_feature": "EA / 路由特征",
    "copy_order": "跟单订单",
    "copy_group": "跟单组",
    "rebate": "返佣记录",
}


class AccountRelationshipNetworkService:
    """Compose existing account evidence into a graph without judging risk."""

    def __init__(self, legacy_call: LegacyCall, *, source_timeout_seconds: float = 6.0) -> None:
        if source_timeout_seconds <= 0:
            raise ValueError("source_timeout_seconds must be positive")
        self._legacy_call = legacy_call
        self._source_timeout_seconds = source_timeout_seconds

    def build(self, login: str, filters: dict[str, str]) -> dict[str, Any]:
        return self.build_with_budget(login, filters, remaining_seconds=self._source_timeout_seconds)

    def build_with_budget(
        self,
        login: str,
        filters: dict[str, str],
        *,
        remaining_seconds: float,
    ) -> dict[str, Any]:
        """Read one account's evidence without exceeding the caller's remaining deadline."""
        source_timeout_seconds = min(self._source_timeout_seconds, max(float(remaining_seconds), 0.001))
        requests = {
            "sameName": ("account_risk_panels_payload", login, filters),
            "loginIps": ("account_login_ips_payload", login),
            "copyOrigins": ("account_copy_origins_payload", login, filters),
            "copyGroups": ("account_copy_group_profit_payload", login, filters),
            "eaGroups": ("account_ea_comment_profit_payload", login, filters),
        }
        payloads: dict[str, dict[str, Any]] = {}
        coverage: list[dict[str, str]] = []
        executor = ThreadPoolExecutor(max_workers=len(requests), thread_name_prefix="relation-network")
        try:
            futures = {
                executor.submit(self._legacy_call, *args): source
                for source, args in requests.items()
            }
            completed, pending = wait(futures, timeout=source_timeout_seconds)
            for future in completed:
                source = futures[future]
                try:
                    payload = future.result()
                    payloads[source] = payload if isinstance(payload, dict) else {}
                    coverage.append({"source": source, "status": "available", "reason": ""})
                except Exception as exc:
                    payloads[source] = {}
                    coverage.append({"source": source, "status": "failed", "reason": str(exc)})
            for future in pending:
                source = futures[future]
                future.cancel()
                payloads[source] = {}
                coverage.append({
                    "source": source, "status": "timeout",
                    "reason": f"来源查询超过 {source_timeout_seconds:g} 秒预算",
                })
        finally:
            # Do not wait for a slow legacy database call. It is read-only and can complete in its
            # own thread, while this account request returns its verified partial evidence promptly.
            executor.shutdown(wait=False, cancel_futures=True)

        builder = _EvidenceGraphBuilder(login, filters)
        builder.add_same_name(payloads.get("sameName", {}))
        builder.add_login_ips(payloads.get("loginIps", {}))
        builder.add_ea_groups(payloads.get("eaGroups", {}))
        builder.add_copy_origins(payloads.get("copyOrigins", {}))
        builder.add_copy_groups(payloads.get("copyGroups", {}))
        builder.add_rebate(payloads.get("sameName", {}))

        coverage.sort(key=lambda item: item["source"])
        failed = [item for item in coverage if item["status"] == "failed"]
        return {
            "ok": True,
            "account": login,
            "filters": dict(filters),
            "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "relationTypes": [
                {"id": relation_id, "label": label}
                for relation_id, label in RELATION_TYPES.items()
            ],
            "entities": builder.entities,
            "relationships": builder.relationships,
            "summary": {
                "entityCount": len(builder.entities),
                "relationshipCount": len(builder.relationships),
                "evidenceCount": sum(len(item["evidence"]) for item in builder.relationships),
            },
            "coverage": coverage,
            "limitations": [
                "关系网络仅罗列已读取到的账户、IP、EA、跟单与返佣事实，不提供风险评分、关系强弱或风险结论。",
                "登录 IP 仅展示该账户当前与本地历史观察记录；本版本不将其推断为跨账户同 IP 关系。",
                *[
                    f"{item['source']} 查询失败：{item['reason']}"
                    for item in failed
                    if item["reason"]
                ],
            ],
        }


class _EvidenceGraphBuilder:
    def __init__(self, login: str, filters: dict[str, str]) -> None:
        self.login = str(login)
        self.filters = filters
        self.entities: list[dict[str, Any]] = []
        self.relationships: list[dict[str, Any]] = []
        self._entity_ids: set[str] = set()
        self._relationship_ids: set[str] = set()
        self.subject_id = self.add_entity(
            "account",
            self.login,
            platform=_text(filters.get("platform")),
            server=_text(filters.get("server")),
            is_subject=True,
        )

    def add_entity(
        self,
        entity_type: str,
        label: str,
        *,
        platform: str = "",
        server: str = "",
        detail: str = "",
        is_subject: bool = False,
        key: str = "",
    ) -> str:
        stable_key = key or "|".join((entity_type, label, platform, server))
        entity_id = f"{entity_type}:{stable_key}"
        if entity_id in self._entity_ids:
            return entity_id
        self._entity_ids.add(entity_id)
        self.entities.append({
            "id": entity_id,
            "type": entity_type,
            "label": label,
            "platform": platform,
            "server": server,
            "detail": detail,
            "isSubject": is_subject,
        })
        return entity_id

    def add_relationship(
        self,
        relation_type: str,
        source: str,
        target: str,
        label: str,
        evidence: list[str],
        *,
        key: str = "",
    ) -> None:
        relation_id = key or "|".join((relation_type, source, target, label))
        if relation_id in self._relationship_ids:
            return
        self._relationship_ids.add(relation_id)
        self.relationships.append({
            "id": relation_id,
            "type": relation_type,
            "typeLabel": RELATION_TYPES[relation_type],
            "source": source,
            "target": target,
            "label": label,
            "evidence": [item for item in evidence if item],
        })

    def add_same_name(self, payload: dict[str, Any]) -> None:
        panels = _mapping(payload.get("riskPanels"))
        if not panels.get("available"):
            return
        for row in _items(panels.get("sameName")):
            account = _text(row.get("account"))
            platform = _text(row.get("platform"))
            server = _text(row.get("server"))
            if not account or (account == self.login and platform == _text(self.filters.get("platform")) and server == _text(self.filters.get("server"))):
                continue
            account_id = self.add_entity(
                "account",
                account,
                platform=platform,
                server=server,
                detail=_account_detail(row),
            )
            self.add_relationship(
                "same_crm_user",
                self.subject_id,
                account_id,
                "同一 CRM 用户账户",
                [
                    "CRM mt_users_account 查询返回相同 user_id。",
                    _route_text(platform, server),
                    _money_evidence("综合盈利", row.get("comprehensiveProfit"), row.get("currency")),
                    _money_evidence("返佣", row.get("rebate"), row.get("currency")),
                ],
            )

    def add_login_ips(self, payload: dict[str, Any]) -> None:
        for row in _items(payload.get("records")):
            ip = _text(row.get("ip"))
            if not ip:
                continue
            platform = _text(row.get("platform"))
            server = _text(row.get("server"))
            ip_id = self.add_entity(
                "ip",
                ip,
                platform=platform,
                server=server,
                detail=_text(_mapping(row.get("geo")).get("country")),
            )
            self.add_relationship(
                "login_ip",
                self.subject_id,
                ip_id,
                "登录 IP 观察",
                [
                    _route_text(platform, server),
                    _text(row.get("lastAccessAt")) and f"数据库最后访问：{_text(row.get('lastAccessAt'))}",
                    _text(row.get("firstSeenAt")) and f"本地首次观察：{_text(row.get('firstSeenAt'))}",
                    _text(row.get("lastSeenAt")) and f"本地最后观察：{_text(row.get('lastSeenAt'))}",
                ],
            )

    def add_ea_groups(self, payload: dict[str, Any]) -> None:
        for group in _items(payload.get("groups")):
            comment = _text(group.get("comment")) or "未命名 EA 特征"
            platform = _text(group.get("platform")) or _text(self.filters.get("platform"))
            servers = [_text(item) for item in _items(group.get("servers")) if _text(item)]
            server = " / ".join(servers) or _text(group.get("server")) or _text(self.filters.get("server"))
            classification = _text(group.get("classificationLabel")) or _text(group.get("classification"))
            group_id = self.add_entity(
                "ea_feature",
                comment,
                platform=platform,
                server=server,
                detail=classification,
                key=f"{comment}|{platform}|{server}",
            )
            self.add_relationship(
                "ea_feature",
                self.subject_id,
                group_id,
                classification or "EA / 路由特征",
                [
                    _text(group.get("classificationEvidence")),
                    _text(group.get("matchRule")) and f"匹配规则：{_text(group.get('matchRule'))}",
                    _text(group.get("expertId")) and f"查询账号标识：{_text(group.get('expertId'))}",
                ],
                key=f"ea-subject|{group_id}",
            )
            for member in _items(group.get("members")):
                account = _text(member.get("account"))
                if not account:
                    continue
                member_platform = _text(member.get("platform")) or platform
                member_server = _text(member.get("server")) or server
                account_id = self.add_entity(
                    "account",
                    account,
                    platform=member_platform,
                    server=member_server,
                    detail=_account_detail(member),
                )
                self.add_relationship(
                    "ea_feature",
                    group_id,
                    account_id,
                    "EA 特征匹配",
                    [
                        _text(member.get("matchClue")),
                        *[_text(item) for item in _items(member.get("matchClues"))],
                        _count_evidence("平仓订单", member.get("orders")),
                        _money_evidence("净盈亏", member.get("netProfit"), member.get("currency")),
                    ],
                    key=f"ea-member|{group_id}|{account_id}",
                )

    def add_copy_origins(self, payload: dict[str, Any]) -> None:
        for origin in _items(payload.get("origins")):
            account = _text(origin.get("account"))
            if not account:
                continue
            platform = _text(origin.get("platform"))
            server = _text(origin.get("server"))
            source_id = self.add_entity(
                "account",
                account,
                platform=platform,
                server=server,
                detail="跟单单主",
            )
            self.add_relationship(
                "copy_order",
                self.subject_id,
                source_id,
                "匹配单主",
                [
                    _route_text(platform, server),
                    _count_evidence("匹配订单", origin.get("matchedOrders")),
                    _count_evidence("当前账号跟单订单", origin.get("orders")),
                    _money_evidence("当前账号跟单净盈亏", origin.get("netProfit"), origin.get("currency")),
                ],
                key=f"copy-subject|{source_id}",
            )
            for follower in _items(origin.get("followers")):
                follower_login = _text(follower.get("account"))
                if not follower_login:
                    continue
                follower_platform = _text(follower.get("platform")) or platform
                follower_server = _text(follower.get("server")) or server
                follower_id = self.add_entity(
                    "account",
                    follower_login,
                    platform=follower_platform,
                    server=follower_server,
                    detail="跟单账户",
                )
                self.add_relationship(
                    "copy_order",
                    source_id,
                    follower_id,
                    "单主跟单关系",
                    [
                        _count_evidence("跟单订单", follower.get("orders")),
                        _money_evidence("跟单净盈亏", follower.get("netProfit"), follower.get("currency")),
                        _text(follower.get("firstTime")) and f"首次记录：{_text(follower.get('firstTime'))}",
                        _text(follower.get("lastTime")) and f"最后记录：{_text(follower.get('lastTime'))}",
                    ],
                    key=f"copy-follower|{source_id}|{follower_id}",
                )

    def add_copy_groups(self, payload: dict[str, Any]) -> None:
        for group in _items(payload.get("groups")):
            tag = _text(group.get("signalTag")) or "跟单组"
            platform = _text(group.get("platform")) or _text(self.filters.get("platform"))
            server = _text(group.get("server")) or _text(self.filters.get("server"))
            group_id = self.add_entity(
                "copy_group",
                tag,
                platform=platform,
                server=server,
                detail="Signal 跟单组",
                key=f"{tag}|{platform}|{server}",
            )
            self.add_relationship(
                "copy_group",
                self.subject_id,
                group_id,
                "Signal 跟单组",
                [
                    _route_text(platform, server),
                    _count_evidence("账户数", _mapping(group.get("totals")).get("accounts")),
                ],
                key=f"copy-group-subject|{group_id}",
            )
            for member in _items(group.get("members")):
                account = _text(member.get("account"))
                if not account:
                    continue
                account_id = self.add_entity(
                    "account",
                    account,
                    platform=platform,
                    server=server,
                    detail="跟单组成员",
                )
                self.add_relationship(
                    "copy_group",
                    group_id,
                    account_id,
                    "跟单组成员",
                    [
                        _count_evidence("平仓订单", member.get("closedOrders")),
                        _count_evidence("持仓订单", member.get("openOrders")),
                        _money_evidence("综合交易盈亏", member.get("combinedNetProfit"), member.get("currency")),
                        _money_evidence("产生返佣", member.get("rebate"), member.get("currency")),
                    ],
                    key=f"copy-group-member|{group_id}|{account_id}",
                )

    def add_rebate(self, payload: dict[str, Any]) -> None:
        panels = _mapping(payload.get("riskPanels"))
        finance = _mapping(panels.get("finance"))
        if not finance or "rebate" not in finance:
            return
        currency = _text(finance.get("displayCurrency")) or _text(finance.get("currency"))
        rebate_id = self.add_entity(
            "rebate",
            "账户返佣",
            detail=_money_evidence("金额", finance.get("rebate"), currency),
            key=self.login,
        )
        self.add_relationship(
            "rebate",
            self.subject_id,
            rebate_id,
            "CRM 返佣记录",
            [
                _money_evidence("返佣金额", finance.get("rebate"), currency),
                _count_evidence("返佣明细行", finance.get("rebateRows")),
                "仅汇总当前账户所属 CRM 路由的 rebate_task_detail 记录。",
            ],
        )


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _route_text(platform: str, server: str) -> str:
    route = " / ".join(item for item in (platform, server) if item)
    return f"数据路由：{route}" if route else "数据路由：当前账户筛选"


def _count_evidence(label: str, value: Any) -> str:
    if value in (None, ""):
        return ""
    return f"{label}：{value}"


def _money_evidence(label: str, value: Any, currency: Any = "") -> str:
    if value in (None, ""):
        return ""
    unit = _text(currency)
    return f"{label}：{value}{(' ' + unit) if unit else ''}"


def _account_detail(row: dict[str, Any]) -> str:
    currency = _text(row.get("currency"))
    net_profit = row.get("netProfit", row.get("comprehensiveProfit"))
    return _money_evidence("净盈亏", net_profit, currency)
