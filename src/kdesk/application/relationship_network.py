from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime
from typing import Any

LegacyCall = Callable[..., dict[str, Any]]


RELATION_TYPES = {
    "same_crm_user": "同名账户",
    "crm_owner": "CRM \u8d26\u6237\u5f52\u5c5e",
    "direct_ib": "\u76f4\u5c5e IB",
    "ib_owned_account": "IB \u81ea\u8eab\u4ea4\u6613\u8d26\u6237",
    "ib_direct_account": "\u76f4\u5c5e IB \u81ea\u8eab\u4ea4\u6613\u8d26\u6237",
    "ib_identity": "IB \u8eab\u4efd\u786e\u8ba4",
    "ib_direct_rebate": "IB \u76f4\u63a5\u8fd4\u4f63\u4eba\u5458",
    "top_ib_group": "\u9876\u7ea7 IB \u7fa4\u7ec4\uff08\u805a\u5408\uff09",
    "login_ip": "登录 IP",
    "client_id": "CID",
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
        self._source_executors = {
            source: ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"relationship-{source}")
            for source in ("sameName", "copyOrigins", "copyGroups", "eaGroups", "crmIb")
        }

    def close(self) -> None:
        for executor in self._source_executors.values():
            executor.shutdown(wait=False, cancel_futures=True)

    def build(self, login: str, filters: dict[str, str]) -> dict[str, Any]:
        return self.build_with_budget(login, filters, remaining_seconds=self._source_timeout_seconds)

    def build_with_budget(
        self,
        login: str,
        filters: dict[str, str],
        *,
        remaining_seconds: float,
        include_ib_aggregate: bool = True,
        include_automation: bool = True,
    ) -> dict[str, Any]:
        """Read one account's evidence without exceeding the caller's remaining deadline."""
        source_timeout_seconds = min(self._source_timeout_seconds, max(float(remaining_seconds), 0.001))
        relationship_filters = {**filters, "_relationship": "1"}
        requests = {
            # The account dashboard payload includes full trade history and is intentionally
            # not suitable for every node in an unbounded graph expansion.  This relationship
            # path needs only the CRM account mapping, which the dedicated source returns.
            "sameName": ("account_relationship_core_payload", login, relationship_filters),
            "crmIb": (
                "account_crm_ib_relationship_payload",
                login,
                {**relationship_filters, "includeIbAggregate": include_ib_aggregate},
            ),
        }
        if include_automation:
            requests.update({
                "copyOrigins": ("account_copy_origins_payload", login, relationship_filters),
                "copyGroups": ("account_copy_group_profit_payload", login, relationship_filters),
                "eaGroups": ("account_ea_comment_profit_payload", login, relationship_filters),
            })
        payloads: dict[str, dict[str, Any]] = {}
        coverage: list[dict[str, str]] = []
        futures = {
            self._source_executors[source].submit(self._legacy_call, *args): source
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
        if not include_automation:
            coverage.extend([
                {
                    "source": "eaGroups", "status": "skipped",
                    "reason": "同当前 LastIP 群组已由代表账户完成 EA 关系读取，避免对同一会话群组重复加载完整订单特征",
                },
                {
                    "source": "copyOrigins", "status": "skipped",
                    "reason": "同当前 LastIP 群组已由代表账户完成跟单关系读取，避免对同一会话群组重复加载完整订单特征",
                },
                {
                    "source": "copyGroups", "status": "skipped",
                    "reason": "同当前 LastIP 群组已由代表账户完成跟单组读取，避免对同一会话群组重复加载完整订单特征",
                },
            ])

        builder = _EvidenceGraphBuilder(login, filters)
        builder.add_same_name(payloads.get("sameName", {}))
        builder.add_crm_ib_relationship(payloads.get("crmIb", {}))
        builder.add_ea_groups(payloads.get("eaGroups", {}))
        builder.add_copy_origins(payloads.get("copyOrigins", {}))
        builder.add_copy_groups(payloads.get("copyGroups", {}))
        builder.add_rebate(payloads.get("sameName", {}))
        builder.finalize_display_metadata()

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
        self._entity_by_id: dict[str, dict[str, Any]] = {}
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
        database_status: str = "",
        is_subject: bool = False,
        key: str = "",
    ) -> str:
        stable_key = key or "|".join((entity_type, label, platform, server))
        entity_id = f"{entity_type}:{stable_key}"
        if entity_id in self._entity_ids:
            existing = self._entity_by_id[entity_id]
            if entity_type == "account" and database_status and not _text(existing.get("databaseStatus")):
                existing["databaseStatus"] = database_status
            return entity_id
        self._entity_ids.add(entity_id)
        entity = {
            "id": entity_id,
            "type": entity_type,
            "label": label,
            "platform": platform,
            "server": server,
            "detail": detail,
            "isSubject": is_subject,
        }
        if entity_type == "account":
            entity["databaseStatus"] = database_status
        self.entities.append(entity)
        self._entity_by_id[entity_id] = entity
        return entity_id

    def set_database_status(self, entity_id: str, database_status: Any) -> None:
        status = _text(database_status)
        if status and entity_id in self._entity_by_id:
            self._entity_by_id[entity_id]["databaseStatus"] = status

    def add_relationship(
        self,
        relation_type: str,
        source: str,
        target: str,
        label: str,
        evidence: list[str],
        *,
        key: str = "",
        metrics: dict[str, Any] | None = None,
        display_anchor_id: str = "",
        display_group_key: str = "",
        display_member_count: int | None = None,
        display_member_id: str = "",
    ) -> None:
        relation_id = key or "|".join((relation_type, source, target, label))
        if relation_id in self._relationship_ids:
            return
        self._relationship_ids.add(relation_id)
        relationship = {
            "id": relation_id,
            "type": relation_type,
            "typeLabel": RELATION_TYPES[relation_type],
            "source": source,
            "target": target,
            "label": label,
            "evidence": [item for item in evidence if item],
            "metrics": metrics if isinstance(metrics, dict) else {},
        }
        if display_anchor_id:
            relationship["display_anchor_id"] = display_anchor_id
        if display_group_key:
            relationship["display_group_key"] = display_group_key
        if display_member_count is not None:
            relationship["display_member_count"] = max(int(display_member_count), 0)
        if display_member_id:
            relationship["display_member_id"] = display_member_id
        self.relationships.append(relationship)

    def finalize_display_metadata(self) -> None:
        """Attach stable, structural display-group fields without changing graph edges."""
        account_component_types = {"same_crm_user", "same_name", "login_ip", "client_id"}
        for relation_type in account_component_types:
            rows = [
                edge for edge in self.relationships
                if edge["type"] == relation_type
                and self._entity_by_id.get(edge["source"], {}).get("type") == "account"
                and self._entity_by_id.get(edge["target"], {}).get("type") == "account"
            ]
            components: list[set[str]] = []
            for edge in rows:
                endpoints = {edge["source"], edge["target"]}
                connected = [component for component in components if component & endpoints]
                merged = set().union(endpoints, *connected)
                components = [component for component in components if component not in connected]
                components.append(merged)
            for component in components:
                anchor = min(component)
                group_key = f"{relation_type}|{anchor}|undirected"
                for edge in rows:
                    if {edge["source"], edge["target"]} <= component:
                        edge.setdefault("display_anchor_id", anchor)
                        edge.setdefault("display_group_key", group_key)
                        edge.setdefault("display_member_count", len(component))
        for edge in self.relationships:
            source, target = edge["source"], edge["target"]
            source_type = self._entity_by_id.get(source, {}).get("type")
            target_type = self._entity_by_id.get(target, {}).get("type")
            anchor = edge.get("display_anchor_id") or (
                source if source_type in {"ib_user", "ea_feature", "copy_group", "relation_group", "ib_group", "rebate"}
                else target if target_type in {"ib_user", "ea_feature", "copy_group", "relation_group", "ib_group", "rebate"}
                else source
            )
            anchor_entity = self._entity_by_id.get(anchor, {})
            route = "|".join(filter(None, (_text(anchor_entity.get("platform")), _text(anchor_entity.get("server")))))
            edge.setdefault("display_anchor_id", anchor)
            edge.setdefault("display_group_key", f"{edge['type']}|{anchor}|{route or 'all-routes'}")
        groups: dict[str, set[str]] = {}
        for edge in self.relationships:
            key = _text(edge.get("display_group_key"))
            members = groups.setdefault(key, set())
            for endpoint in (edge["source"], edge["target"]):
                if self._entity_by_id.get(endpoint, {}).get("type") == "account":
                    members.add(endpoint)
        for edge in self.relationships:
            edge.setdefault("display_member_count", len(groups.get(_text(edge.get("display_group_key")), set())))

    def add_same_name(self, payload: dict[str, Any]) -> None:
        panels = _mapping(payload.get("riskPanels"))
        self.set_database_status(self.subject_id, panels.get("databaseStatus"))
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
                database_status=_text(row.get("databaseStatus")),
            )
            self.add_relationship(
                "same_crm_user",
                self.subject_id,
                account_id,
                "同名账户",
                [
                    "这些交易账户登记在同一客户名下。",
                    _money_evidence("综合盈利", row.get("comprehensiveProfit"), row.get("currency")),
                    _money_evidence("返佣", row.get("rebate"), row.get("currency")),
                ],
                metrics={
                    "comprehensiveProfit": row.get("comprehensiveProfit"),
                    "rebate": row.get("rebate"),
                    "currency": _text(row.get("currency")),
                },
            )

    def add_crm_ib_relationship(self, payload: dict[str, Any]) -> None:
        """Add exact CRM routes and a bounded, expandable direct-rebate IB branch."""
        def anomaly_evidence(member: dict[str, Any], ib_user_id: str) -> list[str]:
            status = _text(member.get("databaseStatus")) or "B"
            rebate = _decimal_text(member.get("rebateAmount")) or "0"
            trade_profit = _decimal_text(member.get("tradeProfit")) or "0"
            combined = _decimal_text(member.get("combinedProfit")) or "0"
            share = _float(member.get("rebateShare")) * 100
            raw_reasons = member.get("inclusionReasons")
            reasons = "、".join(
                _text(item) for item in raw_reasons if _text(item)
            ) if isinstance(raw_reasons, list) else ""
            return [
                f"直属 IB：{ib_user_id}",
                f"纳入原因：{reasons or '返佣异常筛选'}",
                f"数据库状态：{status}",
                f"实际交易盈亏：{trade_profit} USD",
                f"返佣：{rebate} USD",
                f"综合盈利：{combined} USD",
                f"返佣占综合盈利：{share:.1f}%",
                _number_text(member.get("rebateOrderCount")) and f"返佣关联成交：{_number_text(member.get('rebateOrderCount'))} 笔",
                _text(member.get("lastRebateAt")) and f"最近返佣记录：{_text(member.get('lastRebateAt'))}",
            ]

        def anomaly_metrics(member: dict[str, Any], total: Any) -> dict[str, Any]:
            return {
                "databaseStatus": _text(member.get("databaseStatus")) or "B",
                "tradeProfit": member.get("tradeProfit"),
                "rebateAmount": member.get("rebateAmount"),
                "combinedProfit": member.get("combinedProfit"),
                "rebateShare": member.get("rebateShare"),
                "rebateOrderCount": member.get("rebateOrderCount"),
                "lastRebateAt": _text(member.get("lastRebateAt")),
                "inclusionReasons": [
                    _text(item) for item in member.get("inclusionReasons", [])
                    if _text(item)
                ] if isinstance(member.get("inclusionReasons"), list) else [],
                "currency": _text(member.get("currency")) or "USD",
                "knownMembers": _int(total),
            }

        for record in _items(payload.get("records")):
            crm_user_id = _text(record.get("crmUserId"))
            if not crm_user_id:
                continue
            route = _route_text(_text(record.get("platform")), _text(record.get("server")))
            crm_user_id_entity = self.add_entity(
                "crm_user",
                f"CRM \u7528\u6237 {crm_user_id}",
                detail="\u5f53\u524d\u4ea4\u6613\u8d26\u6237\u5f52\u5c5e\u7528\u6237",
                key=f"{_text(record.get('crmSchema'))}|{crm_user_id}",
            )
            self.add_relationship(
                "crm_owner",
                self.subject_id,
                crm_user_id_entity,
                "CRM \u8d26\u6237\u5f52\u5c5e",
                [route, f"CRM \u7528\u6237\uff1a{crm_user_id}"],
                key=f"crm-owner|{self.subject_id}|{crm_user_id_entity}",
            )

            # A CRM user may itself be an IB.  Unlike a top-IB aggregate, these are
            # concrete direct rebate payees.  The legacy source reads them in one
            # indexed grouped query and the returned account nodes can enter normal
            # IP/EA/copy/CRM/rebate discovery when their propagated score qualifies.
            own_ib_members = _items(record.get("ownIbDirectRebateAccounts"))
            if bool(record.get("ownIbDirectRebateChecked")):
                own_total = _int(record.get("ownIbTotalAccounts"))
                own_abnormal = _int(record.get("ownIbAbnormalAccounts"))
                own_ib_entity = self.add_entity(
                    "ib_user",
                    f"IB {crm_user_id}",
                    detail=(
                        f"该账户所属 CRM 用户也是 IB；异常 {own_abnormal} / 直属返佣账户共 {own_total} 个"
                        f"；筛选期 {_text(record.get('ibAnomalyPeriodStart'))} 至 {_text(record.get('ibAnomalyPeriodEnd'))}"
                        + ("（结果达到安全上限，未完整展开）" if bool(record.get("ownIbDirectRebateTruncated")) else "")
                    ),
                    key=f"{_text(record.get('crmSchema'))}|{crm_user_id}",
                )
                self.add_relationship(
                    "ib_identity",
                    self.subject_id,
                    own_ib_entity,
                    "IB 身份确认",
                    [
                        f"当前交易账户所属 CRM 用户 {crm_user_id} 也是 IB。",
                        "IB 身份节点不衰减传播分；其直接返佣人员按独立返佣关系继续计算。",
                    ],
                    key=f"ib-identity|{self.subject_id}|{own_ib_entity}",
                )
                for member in own_ib_members:
                    account = _text(member.get("account"))
                    platform = _text(member.get("platform"))
                    server = _text(member.get("server"))
                    if not account or not platform or not server:
                        continue
                    account_id = self.add_entity(
                        "account",
                        account,
                        platform=platform,
                        server=server,
                        detail="IB 直属返佣账户；因返佣主导盈利或数据库状态 P 及以上而纳入",
                        database_status=_text(member.get("databaseStatus")),
                    )
                    if account_id == self.subject_id:
                        continue
                    self.add_relationship(
                        "ib_direct_rebate",
                        own_ib_entity,
                        account_id,
                        "IB 异常直属返佣账户",
                        [*anomaly_evidence(member, crm_user_id), _route_text(platform, server)],
                        key=f"ib-anomalous-rebate|{own_ib_entity}|{account_id}",
                        metrics=anomaly_metrics(member, own_total),
                        display_anchor_id=own_ib_entity,
                        display_group_key=f"ib_direct_rebate|{own_ib_entity}|outbound",
                        display_member_count=own_total,
                    )

            direct_ib_user_id = _text(record.get("directIbUserId"))
            direct_ib_entity = ""
            if direct_ib_user_id:
                direct_ib_entity = self.add_entity(
                    "ib_user",
                    f"IB {direct_ib_user_id}",
                    detail=(
                        f"CRM 直属上级；异常 {_int(record.get('directIbAbnormalAccounts'))} / "
                        f"直属返佣账户共 {_int(record.get('directIbTotalAccounts'))} 个"
                        f"；筛选期 {_text(record.get('ibAnomalyPeriodStart'))} 至 {_text(record.get('ibAnomalyPeriodEnd'))}"
                        + ("（候选读取达到安全上限）" if bool(record.get("directIbAnomalyTruncated")) else "")
                    ),
                    key=f"{_text(record.get('crmSchema'))}|{direct_ib_user_id}",
                )
                self.add_relationship(
                    "direct_ib",
                    crm_user_id_entity,
                    direct_ib_entity,
                    "CRM \u76f4\u5c5e\u4e0a\u7ea7",
                    [f"\u76f4\u5c5e IB CRM \u7528\u6237\uff1a{direct_ib_user_id}"],
                    key=f"direct-ib|{crm_user_id_entity}|{direct_ib_entity}",
                )
                for member in _items(record.get("directIbAccounts")):
                    account = _text(member.get("account"))
                    platform = _text(member.get("platform"))
                    server = _text(member.get("server"))
                    if not account or not platform or not server:
                        continue
                    account_id = self.add_entity(
                        "account",
                        account,
                        platform=platform,
                        server=server,
                        detail="\u76f4\u5c5e IB \u81ea\u8eab\u4ea4\u6613\u8d26\u6237",
                    )
                    self.add_relationship(
                        "ib_owned_account",
                        direct_ib_entity,
                        account_id,
                        "IB \u81ea\u8eab\u4ea4\u6613\u8d26\u6237",
                        [
                            _route_text(platform, server),
                            f"\u8be5\u4ea4\u6613\u8d26\u6237\u5f52\u5c5e\u76f4\u5c5e IB CRM \u7528\u6237\uff1a{direct_ib_user_id}",
                        ],
                        key=f"ib-owned-account|{direct_ib_entity}|{account_id}",
                    )
                    if account_id != self.subject_id:
                        self.add_relationship(
                            "ib_direct_account",
                            self.subject_id,
                            account_id,
                            "\u76f4\u5c5e IB \u81ea\u8eab\u4ea4\u6613\u8d26\u6237",
                            [
                                f"CRM \u7528\u6237 {crm_user_id} \u2192 \u76f4\u5c5e IB {direct_ib_user_id} \u2192 \u8be5 IB \u81ea\u8eab\u4ea4\u6613\u8d26\u6237",
                                _route_text(platform, server),
                            ],
                            key=f"direct-ib-account|{self.subject_id}|{account_id}|{direct_ib_user_id}",
                        )

                # Do not fan out every member below the direct IB.  Only members
                # selected by the auditable rebate-dominance rule or P+ status are
                # materialised, and their route remains A -> CRM -> IB -> member.
                for member in _items(record.get("directIbAnomalousRebateAccounts")):
                    account = _text(member.get("account"))
                    platform = _text(member.get("platform"))
                    server = _text(member.get("server"))
                    if not account or not platform or not server:
                        continue
                    account_id = self.add_entity(
                        "account",
                        account,
                        platform=platform,
                        server=server,
                        detail="直属 IB 下异常返佣账户；因返佣主导盈利或数据库状态 P 及以上而纳入",
                        database_status=_text(member.get("databaseStatus")),
                    )
                    if account_id == self.subject_id:
                        continue
                    self.add_relationship(
                        "ib_direct_rebate",
                        direct_ib_entity,
                        account_id,
                        "IB 异常直属返佣账户",
                        [*anomaly_evidence(member, direct_ib_user_id), _route_text(platform, server)],
                        key=f"ib-anomalous-rebate|{direct_ib_entity}|{account_id}",
                        metrics=anomaly_metrics(member, record.get("directIbTotalAccounts")),
                        display_anchor_id=direct_ib_entity,
                        display_group_key=f"ib_direct_rebate|{direct_ib_entity}|outbound",
                        display_member_count=_int(record.get("directIbTotalAccounts")),
                    )

            top_ib_user_id = _text(record.get("topIbUserId"))
            if top_ib_user_id and bool(record.get("topIbAggregateAvailable", True)):
                account_count = _number_text(record.get("topIbAccountCount"))
                client_count = _number_text(record.get("topIbClientCount"))
                others = max(_int(record.get("topIbAccountCount")) - 1, 0)
                group_entity = self.add_entity(
                    "ib_group",
                    f"\u9876\u7ea7 IB {top_ib_user_id}",
                    detail=f"\u805a\u5408\u7fa4\u7ec4\uff1a{account_count or '\u672a\u77e5'} \u4e2a\u4ea4\u6613\u8d26\u6237\uff1b\u9ed8\u8ba4\u4e0d\u5c55\u5f00",
                    key=f"{_text(record.get('crmSchema'))}|{top_ib_user_id}",
                )
                self.add_relationship(
                    "top_ib_group",
                    self.subject_id,
                    group_entity,
                    "\u9876\u7ea7 IB \u7fa4\u7ec4\uff08\u805a\u5408\uff09",
                    [
                        f"\u9876\u7ea7 IB CRM \u7528\u6237\uff1a{top_ib_user_id}",
                        account_count and f"\u5f53\u524d CRM \u4e0b\u4ea4\u6613\u8d26\u6237\uff1a{account_count} \u4e2a\uff08\u5176\u4ed6 {others} \u4e2a\uff09",
                        client_count and f"\u5f53\u524d CRM \u4e0b\u5ba2\u6237\uff1a{client_count} \u4e2a",
                        "\u7fa4\u7ec4\u6210\u5458\u9ed8\u8ba4\u4e0d\u5c55\u5f00\uff1b\u987b\u53e6\u6709\u72ec\u7acb IP\u3001EA\u3001\u8ddf\u5355\u3001\u5b9e\u540d\u6216\u4ea4\u6613\u540c\u6b65\u8bc1\u636e\u624d\u8fdb\u5165\u8d26\u6237\u56fe\u3002",
                    ],
                    key=f"top-ib-group|{self.subject_id}|{group_entity}",
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
                metrics={"expertId": _text(group.get("expertId")), "matchRule": _text(group.get("matchRule"))},
                display_anchor_id=group_id,
                display_group_key=f"ea_feature|{group_id}|outbound",
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
                    metrics={
                        "orders": member.get("orders"), "closedOrders": member.get("orders"),
                        "netProfit": member.get("netProfit"), "currency": _text(member.get("currency")),
                        "expertIds": _items(member.get("expertIds")), "matchClue": _text(member.get("matchClue")),
                    },
                    display_anchor_id=group_id,
                    display_group_key=f"ea_feature|{group_id}|outbound",
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
                metrics={
                    "matchedOrders": origin.get("matchedOrders"), "orders": origin.get("orders"),
                    "netProfit": origin.get("netProfit"), "currency": _text(origin.get("currency")),
                },
                display_anchor_id=source_id,
                display_group_key=f"copy_order|{source_id}|outbound",
                display_member_id=self.subject_id,
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
                    metrics={
                        "orders": follower.get("orders"), "matchedOrders": follower.get("matchedOrders"),
                        "matchedSourceOrders": follower.get("matchedSourceOrders"), "lots": follower.get("lots") or follower.get("volume"),
                        "netProfit": follower.get("netProfit"), "currency": _text(follower.get("currency")),
                        "firstTime": _text(follower.get("firstTime")), "lastTime": _text(follower.get("lastTime")),
                    },
                    display_anchor_id=source_id,
                    display_group_key=f"copy_order|{source_id}|outbound",
                    display_member_id=follower_id,
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
                metrics={"knownMembers": _mapping(group.get("totals")).get("accounts")},
                display_anchor_id=group_id,
                display_group_key=f"copy_group|{group_id}|outbound",
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
                    metrics={
                        "closedOrders": member.get("closedOrders"), "openOrders": member.get("openOrders"),
                        "closedLots": member.get("closedLots"), "combinedNetProfit": member.get("combinedNetProfit"),
                        "rebate": member.get("rebate"), "currency": _text(member.get("currency")),
                    },
                    display_anchor_id=group_id,
                    display_group_key=f"copy_group|{group_id}|outbound",
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
            metrics={"rebateAmount": finance.get("rebate"), "rebateRows": finance.get("rebateRows"), "currency": currency},
            display_anchor_id=rebate_id,
            display_group_key=f"rebate|{rebate_id}|outbound",
        )


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _number_text(value: Any) -> str:
    return str(_int(value)) if value not in (None, "") else ""


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _decimal_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return f"{_float(value):.2f}"


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
