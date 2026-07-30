from __future__ import annotations

from collections.abc import Sequence

from kdesk.domain.kline import partial_result


def symbol_failure(
    symbol: str,
    *,
    stage: str,
    code: str,
    quote_sources: Sequence[str],
    reason: str,
    metrics: dict | None = None,
    attempts: Sequence[dict] = (),
) -> dict:
    return {
        "symbol": str(symbol),
        "stage": str(stage),
        "code": str(code),
        "quoteSources": list(quote_sources),
        "metrics": dict(metrics or {}),
        "reason": str(reason),
        "attempts": list(attempts),
    }


def missing_same_source_failure(
    symbol: str,
    *,
    platform: str,
    server: str,
    configured_providers: Sequence[dict],
) -> dict:
    requested = " / ".join(value for value in (str(platform).strip(), str(server).strip()) if value) or "未指定服务器"
    return symbol_failure(
        symbol,
        stage="source",
        code="NO_SAME_SOURCE_PROVIDER",
        quote_sources=(),
        metrics={
            "requestedPlatform": str(platform),
            "requestedServer": str(server),
            "configuredProviders": list(configured_providers),
        },
        reason=(
            f"{requested} 未配置同服务器只读报价源；请在 KDESK_KLINE_QUOTE_SOURCES 中配置该服务器的 provider，"
            "或在 route 中显式声明允许的 fallback"
        ),
    )


def generation_result(*, chart: str, symbols: Sequence[dict], failures: Sequence[dict], quote_sources: Sequence[dict]) -> dict:
    additive = partial_result(symbols, failures, quote_sources)
    has_symbols = bool(symbols)
    return {
        "chart": chart if has_symbols else "",
        "status": "done" if has_symbols else "failed",
        "message": "部分品种生成完成" if additive["partial"] else "生成完成" if has_symbols else "全部品种报价校验失败",
        **additive,
    }
