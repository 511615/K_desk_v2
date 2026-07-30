from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class QuoteSource:
    id: str
    terminal: str
    servers: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    aliases: dict[str, str | list[str]] = field(default_factory=dict)
    price_corrections: dict[str, float] = field(default_factory=dict)
    allowed_hour_offsets: tuple[int, ...] = tuple(range(-4, 5))

    def describes_server(self, server: str) -> bool:
        target = server.strip().casefold()
        return bool(target) and any(item.strip().casefold() == target for item in self.servers)


@dataclass(frozen=True, slots=True)
class QuoteRoute:
    platform: str
    server: str
    preferred: tuple[str, ...]
    fallback: tuple[str, ...]

    def matches(self, platform: str, server: str) -> bool:
        return self.platform.casefold() in {"", platform.casefold()} and self.server.casefold() in {"", server.casefold()}


class QuoteSourceRegistry:
    def __init__(self, sources: list[QuoteSource], routes: list[QuoteRoute]):
        self.sources = {source.id: source for source in sources}
        self.routes = routes

    @classmethod
    def load(cls, default_terminal: str, path: str | Path | None = None) -> QuoteSourceRegistry:
        configured = path or os.environ.get("KDESK_KLINE_QUOTE_SOURCES", "")
        payload: dict = {}
        if configured:
            config_path = Path(configured)
            if config_path.is_file():
                payload = json.loads(config_path.read_text(encoding="utf-8"))
        sources = []
        for item in payload.get("providers", []):
            if not isinstance(item, dict) or not item.get("id") or not item.get("terminal"):
                continue
            sources.append(
                QuoteSource(
                    id=str(item["id"]),
                    terminal=str(item["terminal"]),
                    servers=tuple(str(value) for value in item.get("servers", [])),
                    platforms=tuple(str(value) for value in item.get("platforms", [])),
                    aliases=dict(item.get("aliases") or {}),
                    price_corrections={str(key): float(value) for key, value in (item.get("priceCorrections") or {}).items()},
                    allowed_hour_offsets=tuple(int(value) for value in item.get("allowedHourOffsets", range(-4, 5))),
                )
            )
        if not sources:
            sources = [QuoteSource(id="default", terminal=default_terminal)]
        routes = [
            QuoteRoute(
                platform=str(item.get("platform") or ""),
                server=str(item.get("server") or ""),
                preferred=tuple(str(value) for value in item.get("preferred", [])),
                fallback=tuple(str(value) for value in item.get("fallback", [])),
            )
            for item in payload.get("routes", [])
            if isinstance(item, dict)
        ]
        return cls(sources, routes)

    def candidates(self, platform: str = "", server: str = "") -> list[tuple[QuoteSource, bool]]:
        def platform_allowed(source: QuoteSource) -> bool:
            return not platform or not source.platforms or any(item.casefold() == platform.casefold() for item in source.platforms)

        for route in self.routes:
            if route.matches(platform, server):
                ordered = [(source_id, False) for source_id in route.preferred]
                ordered.extend((source_id, True) for source_id in route.fallback)
                return [
                    (self.sources[source_id], fallback)
                    for source_id, fallback in ordered
                    if source_id in self.sources and platform_allowed(self.sources[source_id])
                ]
        same = [source for source in self.sources.values() if source.describes_server(server) and platform_allowed(source)]
        if same:
            return [(source, False) for source in same]
        if len(self.sources) == 1 and next(iter(self.sources)) == "default":
            # The legacy Terminal remains the universal read-only quote fallback.
            return [(next(iter(self.sources.values())), bool(server))]
        # Without an explicit route, providers are candidates for uploaded reports only.
        if not server:
            return [(source, False) for source in self.sources.values() if platform_allowed(source)]
        return []

    def provider_summary(self) -> list[dict]:
        return [
            {
                "id": source.id,
                "servers": list(source.servers),
                "platforms": list(source.platforms),
            }
            for source in self.sources.values()
        ]
