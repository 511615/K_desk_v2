from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from kdesk.domain.bonus_arbitrage import BonusAnalysisCancelled, detect_bonus_arbitrage


class BonusArbitrageRepository(Protocol):
    def load_account_context(self, login: str, filters: dict) -> dict: ...


class BonusArbitrageService:
    def __init__(self, repository: BonusArbitrageRepository):
        self.repository = repository

    def analyze(
        self,
        login: str,
        filters: dict,
        *,
        stage: str = "deep",
        cancelled: Callable[[], bool] | None = None,
    ) -> dict:
        if cancelled and cancelled():
            raise BonusAnalysisCancelled("赠金套利分析已取消")
        context = self.repository.load_account_context(login, filters)
        if cancelled and cancelled():
            raise BonusAnalysisCancelled("赠金套利分析已取消")
        return detect_bonus_arbitrage(
            context.get("profile") or {},
            context.get("events") or [],
            context.get("trades") or [],
            context.get("peers") or [],
            stage=stage,
            cancelled=cancelled,
        )
