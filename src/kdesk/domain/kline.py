from __future__ import annotations

import math
import re
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

SYMBOL_ALIASES: dict[str, tuple[str, ...]] = {
    "CHINA50": ("CN50Roll",),
    "CN50": ("CN50Roll",),
    "HKG50": ("HKG50Roll",),
    "HK50": ("HKG50Roll",),
    "NAS100": ("NAS100Roll",),
    "UT100": ("NAS100Roll",),
    "US30": ("US30Roll",),
    "SPX500": ("SPX500Roll",),
    "UK100": ("UK100Roll",),
    "GER40": ("GER40Roll",),
    "JPN225": ("JPN225Roll",),
    "AUS200": ("AUS200Roll",),
    "UKOIL": ("UKOILRoll",),
    "USOIL": ("USOILRoll",),
    "NGAS": ("NGASRoll",),
}

KNOWN_SUFFIXES = ("ECN", "PRO")


def canonical_symbol(value: str) -> str:
    token = re.sub(r"\s+", "", str(value or "")).upper()
    if "." in token:
        token = token.split(".", 1)[0].rstrip("_-")
    changed = True
    while changed and token:
        changed = False
        for suffix in KNOWN_SUFFIXES:
            if token.endswith(suffix):
                token = token[: -len(suffix)].rstrip("._-")
                changed = True
                break
    return token.removesuffix("ROLL")


def symbol_candidates(
    report_symbol: str,
    available_symbols: Iterable[str],
    configured_aliases: dict[str, str | Sequence[str]] | None = None,
) -> list[str]:
    raw = str(report_symbol or "").strip()
    raw_upper = raw.upper()
    base = canonical_symbol(raw)
    aliases: list[str] = list(SYMBOL_ALIASES.get(base, ()))
    for key, values in (configured_aliases or {}).items():
        if canonical_symbol(key) != base:
            continue
        aliases.extend([values] if isinstance(values, str) else [str(item) for item in values])

    preferred = [raw, raw_upper, base, f"{base}Roll", *aliases]
    preferred.extend(f"{item}{suffix}" for item in [base, f"{base}Roll", *aliases] for suffix in (".ECN", ".PRO", ".E"))
    preference = {item.upper(): index for index, item in enumerate(preferred) if item}

    scored: list[tuple[tuple[int, int, int, str], str]] = []
    for name in dict.fromkeys(str(item) for item in available_symbols if str(item).strip()):
        upper = name.upper()
        normalized = canonical_symbol(name)
        alias_match = any(canonical_symbol(alias) == normalized for alias in aliases)
        if upper not in preference and normalized != base and not alias_match:
            continue
        exact_rank = preference.get(upper, 10_000)
        family_rank = 0 if normalized == base else 1
        suffix_rank = 0 if upper == raw_upper else 1 if upper.endswith(".ECN") else 2
        scored.append(((exact_rank, family_rank, suffix_rank, len(name), upper), name))
    return [name for _, name in sorted(scored)]


def alignment_offsets(initial_passed: bool) -> tuple[int, ...]:
    if initial_passed:
        return (0, -3)
    return (0, -3, -4, -2, -1, 1, 2, 3, 4)


@dataclass(frozen=True, slots=True)
class EndpointCheck:
    inside: bool
    distance: float
    tolerance: float

    @property
    def normalized_distance(self) -> float:
        return self.distance / max(self.tolerance, 1e-12)


def endpoint_check(price: float, low: float, high: float, *, point: float, spread_points: float = 0.0) -> EndpointCheck:
    low, high = sorted((float(low), float(high)))
    price = float(price)
    distance = 0.0 if low <= price <= high else min(abs(price - low), abs(price - high))
    tolerance = max(abs(float(point)), abs(float(spread_points)) * abs(float(point)), (high - low) / 2, 1e-12)
    return EndpointCheck(inside=distance == 0, distance=distance, tolerance=tolerance)


def execution_endpoint_check(
    price: float,
    low: float,
    high: float,
    *,
    point: float,
    spread_points: float = 0.0,
    trade_type: str,
    endpoint: str,
) -> EndpointCheck:
    """Compare an endpoint with its executable Bid/Ask M1 envelope.

    MT M1 OHLC values are Bid prices. A buy opens and a sell closes at Ask,
    whose upper envelope is the Bid high plus the recorded spread. The lower
    envelope remains the Bid low because a minute's spread value is sampled,
    not a historical minimum during spread changes.
    """
    side = str(trade_type or "").strip().casefold()
    event = str(endpoint or "").strip().casefold()
    ask_endpoint = (side == "buy" and event == "open") or (side == "sell" and event == "close")
    executable_high = float(high) + (abs(float(point)) * max(float(spread_points), 0.0) if ask_endpoint else 0.0)
    return endpoint_check(price, low, executable_high, point=point, spread_points=spread_points)


def validation_metrics(checks: Sequence[EndpointCheck]) -> dict:
    normalized = [item.normalized_distance for item in checks if math.isfinite(item.normalized_distance)]
    inside = sum(item.inside for item in checks)
    within_tolerance = sum(item.normalized_distance <= 1 for item in checks)
    matched = len(normalized)
    return {
        "matched": matched,
        "inside": inside,
        "insideRatio": inside / matched if matched else 0.0,
        "withinTolerance": within_tolerance,
        "allWithinTolerance": bool(matched) and within_tolerance == matched,
        "medianNormalizedDistance": statistics.median(normalized) if normalized else None,
        "maxNormalizedDistance": max(normalized) if normalized else None,
    }


def validation_passes(metrics: dict, *, fallback: bool) -> bool:
    matched = int(metrics.get("matched") or 0)
    if matched == 0:
        return False
    inside_ratio = float(metrics.get("insideRatio") or 0)
    median = metrics.get("medianNormalizedDistance")
    if median is None or float(median) > 2:
        return False
    if fallback:
        within_tolerance_ratio = int(metrics.get("withinTolerance") or 0) / matched
        maximum = metrics.get("maxNormalizedDistance")
        near_match = (
            inside_ratio >= 0.7
            and within_tolerance_ratio >= 0.9
            and float(median) <= 0.25
            and maximum is not None
            and float(maximum) <= 1.25
        )
        return inside_ratio >= 0.8 or bool(metrics.get("allWithinTolerance")) or near_match
    return inside_ratio >= 0.6


def confidence_for(metrics: dict, *, fallback: bool) -> float:
    if not metrics.get("matched"):
        return 0.0
    median = float(metrics.get("medianNormalizedDistance") or 0)
    score = float(metrics.get("insideRatio") or 0) * 0.75 + max(0.0, 1 - median / 4) * 0.25
    if fallback:
        score *= 0.9
    return round(min(max(score, 0.0), 1.0), 4)


def gap_segments(times: Sequence[datetime], *, break_minutes: int = 5, closed_minutes: int = 60) -> list[dict]:
    result: list[dict] = []
    for index, (left, right) in enumerate(zip(times, times[1:], strict=False)):
        minutes = (right - left).total_seconds() / 60
        if minutes <= break_minutes:
            continue
        result.append(
            {
                "afterIndex": index,
                "before": left,
                "after": right,
                "minutes": round(minutes, 3),
                "closed": minutes > closed_minutes,
            }
        )
    return result


def split_indices_at_gaps(times: Sequence[datetime], *, break_minutes: int = 5) -> list[tuple[int, int]]:
    if not times:
        return []
    starts = [0]
    for index, (left, right) in enumerate(zip(times, times[1:], strict=False), start=1):
        if (right - left).total_seconds() > break_minutes * 60:
            starts.append(index)
    return [(start, (starts[pos + 1] if pos + 1 < len(starts) else len(times))) for pos, start in enumerate(starts)]


def partial_result(symbols: Sequence[dict], failures: Sequence[dict], quote_sources: Sequence[dict]) -> dict:
    return {
        "partial": bool(symbols) and bool(failures),
        "symbols": list(symbols),
        "failures": list(failures),
        "quoteSources": list(quote_sources),
    }
