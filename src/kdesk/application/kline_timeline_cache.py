from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class KlineTimelineCache:
    """Durable, account-scoped cache for complete factual funds replays.

    Charts may slice the replay for a visual time range, but the cache always holds
    the complete account replay read from the routed, read-only source.  This keeps
    ordinary chart generation offline from the funds source after the first build.
    """

    _VERSION = 1

    def __init__(self, root: Path) -> None:
        self._root = root

    def path_for(self, account: str, platform: str, server: str) -> Path:
        identity = "\x1f".join((str(account).strip(), str(platform).strip(), str(server).strip()))
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return self._root / f"{digest}.json"

    def get_or_build(
        self,
        account: str,
        platform: str,
        server: str,
        build: Callable[[], dict[str, Any]],
        *,
        refresh: bool = False,
    ) -> tuple[dict[str, Any], str]:
        path = self.path_for(account, platform, server)
        if not refresh:
            cached = self._read(path)
            if cached is not None:
                return cached, "cache"

        replay = build()
        self._write(path, replay, account=account, platform=platform, server=server)
        return replay, "refreshed" if refresh else "built"

    def _read(self, path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("version") != self._VERSION:
            return None
        replay = payload.get("replay")
        if not isinstance(replay, dict):
            return None
        return replay

    def _write(self, path: Path, replay: dict[str, Any], *, account: str, platform: str, server: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self._VERSION,
            "cachedAt": datetime.now(UTC).isoformat(),
            "identity": {"account": str(account), "platform": str(platform), "server": str(server)},
            "replay": replay,
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)
