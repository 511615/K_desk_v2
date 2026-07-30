from __future__ import annotations

from typing import Protocol

from kdesk.domain.position_risk import TARGET_TYPES, analyze_position_risk


class PositionRiskRepository(Protocol):
    def load_account_context(self, account: str, filters: dict) -> dict: ...
    def load_peer_accounts(self, account: str, context: dict, event: dict) -> dict: ...


class PositionRiskService:
    def __init__(self, repository: PositionRiskRepository):
        self.repository = repository

    def analyze(self, account: str, filters: dict, *, stage: str = "deep", type_ids: list[str] | None = None) -> dict:
        selected = [value for value in (type_ids or list(TARGET_TYPES)) if value in TARGET_TYPES]
        context = self.repository.load_account_context(str(account), filters)
        analysis = analyze_position_risk(context, stage=stage, type_ids=selected)
        best = analysis.get("bestResult") or {}
        event = (best.get("evidence") or {}).get("bestEvent") or {}
        if event:
            peers = self.repository.load_peer_accounts(str(account), context, event)
            if isinstance(peers, list):
                peers = {"sameDirectionAccounts": peers, "oppositeDirectionAccounts": []}
            if peers:
                context["peerEvidence"] = peers
                analysis = analyze_position_risk(context, stage=stage, type_ids=selected)
        analysis["account"] = str(account)
        analysis["source"] = {
            key: (context.get("profile") or {}).get(key)
            for key in ("platform", "server", "currency", "moneyScale", "leverage")
        }
        return analysis
