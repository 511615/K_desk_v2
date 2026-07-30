from __future__ import annotations

from kdesk.domain.position_risk import canonical_symbol, number, parse_datetime


class CrossAccountHedgeService:
    """Query cross-account opposite orders without applying other Toxic rules."""

    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _target_orders(context: dict, filters: dict) -> tuple[list[dict], dict]:
        requested_start = parse_datetime(context.get("analysisStart") or filters.get("start"))
        requested_end = parse_datetime(context.get("analysisEnd") or filters.get("end"))
        requested_symbol = canonical_symbol(filters.get("symbol"))
        targets: list[dict] = []
        seen: set[tuple[str, str, str, str]] = set()
        open_positions = 0
        outside_filter = 0

        for trade in context.get("trades") or []:
            closed = parse_datetime(trade.get("closeTime"))
            if bool(trade.get("isOpen")) or not closed:
                open_positions += 1
                continue
            symbol = str(trade.get("symbol") or "")
            if requested_symbol and canonical_symbol(symbol) != requested_symbol:
                outside_filter += 1
                continue
            entries = list(trade.get("entryOrders") or []) or [{
                "orderId": trade.get("ticket") or trade.get("id"),
                "dealId": "",
                "time": trade.get("openTime"),
                "volume": trade.get("volume"),
            }]
            for entry in entries:
                opened = parse_datetime(entry.get("time") or trade.get("openTime"))
                if not opened:
                    outside_filter += 1
                    continue
                if requested_start and opened < requested_start:
                    outside_filter += 1
                    continue
                if requested_end and opened > requested_end:
                    outside_filter += 1
                    continue
                order_id = str(entry.get("orderId") or trade.get("ticket") or trade.get("id") or "")
                position_id = str(trade.get("id") or trade.get("ticket") or order_id)
                deal_id = str(entry.get("dealId") or "")
                opened_text = opened.strftime("%Y-%m-%d %H:%M:%S")
                key = (order_id, position_id, deal_id, opened_text)
                if key in seen:
                    continue
                seen.add(key)
                targets.append({
                    "orderId": order_id,
                    "positionId": position_id,
                    "dealId": deal_id,
                    "symbol": symbol,
                    "direction": str(trade.get("direction") or "").lower(),
                    "volume": number(entry.get("volume") or trade.get("volume")),
                    "openTime": opened_text,
                    "closeTime": closed.strftime("%Y-%m-%d %H:%M:%S"),
                    "_oppositeOnly": True,
                })
        targets.sort(key=lambda row: (row["openTime"], row["orderId"]))
        return targets, {
            "openPositionCount": open_positions,
            "filteredOrderCount": outside_filter,
        }

    @staticmethod
    def _account_rows(matches: list[dict], account_ids: list[str]) -> list[dict]:
        grouped: dict[tuple[str, str, str, str], dict] = {}
        for match in matches:
            key = (
                str(match.get("platform") or ""),
                str(match.get("server") or ""),
                str(match.get("account") or ""),
                str(match.get("database") or ""),
            )
            row = grouped.setdefault(key, {
                "platform": key[0], "server": key[1], "account": key[2], "database": key[3],
                "matchCount": 0, "targetLots": 0.0, "peerLots": 0.0,
            })
            row["matchCount"] += 1
            row["targetLots"] += number(match.get("targetVolume"))
            row["peerLots"] += number(match.get("volume"))
        rows = list(grouped.values())
        represented = {row["account"] for row in rows}
        rows.extend({
            "platform": "", "server": "", "account": str(account), "database": "",
            "matchCount": 0, "targetLots": 0.0, "peerLots": 0.0,
        } for account in account_ids if str(account) not in represented)
        for row in rows:
            row["targetLots"] = round(number(row["targetLots"]), 4)
            row["peerLots"] = round(number(row["peerLots"]), 4)
        return sorted(rows, key=lambda row: (-int(row["matchCount"]), row["platform"], row["server"], row["account"]))

    def analyze(self, account: str, filters: dict, *, stage: str = "deep") -> dict:
        context = self.repository.load_account_context(str(account), filters)
        targets, target_stats = self._target_orders(context, filters)
        event = {
            "start": targets[0]["openTime"] if targets else "",
            "end": max((row["closeTime"] for row in targets), default=""),
            "heavyOrders": targets,
        }
        peer_evidence = self.repository.load_peer_accounts(str(account), context, event)
        matches = list(peer_evidence.get("oppositeDirectionMatches") or [])
        accounts = [str(value) for value in peer_evidence.get("oppositeDirectionAccounts") or []]
        match_total = int(number(peer_evidence.get("oppositeDirectionMatchTotal"), len(matches)))
        coverage = dict(peer_evidence.get("peerSearchCoverage") or {})
        account_rows = self._account_rows(matches, accounts)
        found = match_total > 0
        coverage_status = str(coverage.get("status") or "数据不足")
        source_total = int(number(coverage.get("physicalSourceTotal")))
        scanned_total = int(number(coverage.get("scannedSourceCount")))

        if found:
            summary = f"发现 {len(accounts)} 个疑似对锁账号，共 {match_total} 组反向同步开平仓订单。"
        elif coverage_status == "完成":
            summary = f"已检查 {len(targets)} 笔已平仓目标订单，未发现满足条件的跨账户对锁订单。"
        elif not targets:
            summary = "没有可验证同步平仓的目标订单，无法查询跨账户对锁。"
        else:
            summary = "已完成的数据源中未发现对锁订单，但仍有数据源未完成，不能作为全平台无对锁结论。"

        query = {
            "available": bool(targets),
            "account": str(account),
            "scope": coverage.get("scope") or "AC/DBG 全平台 MT4 + MT5",
            "rule": "同品种、反方向、手数相似度至少80%，且双方开仓和平仓时间差都不超过5秒",
            "targetOrderCount": len(targets),
            "openPositionCount": target_stats["openPositionCount"],
            "filteredOrderCount": target_stats["filteredOrderCount"],
            "accountCount": len(accounts),
            "matchTotal": match_total,
            "accounts": account_rows,
            "matches": matches,
            "detailLimit": int(number(peer_evidence.get("peerMatchDetailLimit"), 500)),
            "detailsTruncated": bool(peer_evidence.get("peerMatchesTruncated")) and match_total > len(matches),
            "lotSimilarityThreshold": number(peer_evidence.get("oppositeLotSimilarityThreshold"), 0.8),
            "coverage": coverage,
            "source": {
                key: (context.get("profile") or {}).get(key)
                for key in ("platform", "server", "currency", "moneyScale")
            },
        }
        confidence = 95 if coverage_status == "完成" else 65 if scanned_total else 0
        limitations = ["反向同步开平仓只能作为疑似平台内对锁证据，不等于已经确认套利关系。"]
        if coverage_status != "完成":
            limitations.append("查询覆盖不完整，未匹配结果不能解释为全平台不存在对锁。")
        if query["detailsTruncated"]:
            limitations.append(f"完整账号与订单对总数已保留，订单明细最多展示 {query['detailLimit']} 组。")
        result = {
            "type": "internal_lock_arbitrage",
            "label": "平台内多账户对锁",
            "score": 100.0 if found else 0.0,
            "level": "发现疑似对锁" if found else ("未发现" if coverage_status == "完成" else "数据不足"),
            "stage": stage,
            "confidence": confidence,
            "summary": summary,
            "metrics": [
                {"label": "已检查目标订单", "value": len(targets)},
                {"label": "疑似对锁账号", "value": len(accounts)},
                {"label": "反向同步订单对", "value": match_total},
                {"label": "数据源覆盖", "value": f"{scanned_total}/{source_total}"},
            ],
            "triggeredRules": [query["rule"]] if found else [],
            "evidenceOrders": sorted({str(row.get("targetOrderId") or "") for row in matches if row.get("targetOrderId")}),
            "limitations": limitations,
            "requiresTick": False,
            "analysis": [
                {"title": "查询规则", "text": query["rule"]},
                {"title": "查询范围", "text": f"{query['scope']}，已完成 {scanned_total}/{source_total} 个物理交易源。"},
                {"title": "查询结论", "text": summary},
            ],
            "evidence": {"hedgeQuery": query},
        }
        return {"result": result, "evidence": query}
