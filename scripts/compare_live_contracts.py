from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DYNAMIC_KEYS = {
    "refreshedAt",
    "updatedAt",
    "equity",
    "marginFree",
    "marginLevel",
    "holdingProfit",
    "comprehensiveProfit",
    "charts",
    "history",
    "record",
}

SECTIONS = {
    "detail": ("database", "metrics"),
    "risk-finance": ("riskPanels", "finance"),
    "risk-frequency": ("riskPanels", "highFrequency"),
    "automation-copy": ("copy",),
    "automation-ea": ("ea",),
}


def fetch(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def at(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = payload
    for key in path:
        value = value[key]
    return value


def compare(left: Any, right: Any, prefix: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        mismatches: list[str] = []
        for key in sorted(set(left) | set(right)):
            if key in DYNAMIC_KEYS:
                continue
            path = f"{prefix}.{key}" if prefix else key
            if key not in left or key not in right:
                mismatches.append(path)
            else:
                mismatches.extend(compare(left[key], right[key], path))
        return mismatches
    if isinstance(left, list) and isinstance(right, list):
        return [] if left == right else [prefix]
    return [] if left == right else [prefix]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("account")
    parser.add_argument("--platform", default="")
    parser.add_argument("--server", default="")
    parser.add_argument("--production", default="http://127.0.0.1:8777")
    parser.add_argument("--development", default="http://127.0.0.1:8877")
    parser.add_argument("--output", default="runtime/dev/reports/contract-comparison.json")
    args = parser.parse_args()
    query = urllib.parse.urlencode({"platform": args.platform, "server": args.server})
    encoded = urllib.parse.quote(args.account, safe="")
    paths = {
        "detail": f"/api/accounts/by-login/{encoded}/detail?{query}",
        "risk-finance": f"/api/accounts/by-login/{encoded}/risk-panels?{query}",
        "risk-frequency": f"/api/accounts/by-login/{encoded}/risk-panels?{query}",
        "automation-copy": f"/api/accounts/by-login/{encoded}/automation-analysis?{query}",
        "automation-ea": f"/api/accounts/by-login/{encoded}/automation-analysis?{query}",
    }
    cache: dict[tuple[str, str], dict[str, Any]] = {}
    results = []
    for name, path in paths.items():
        prod = cache.setdefault(("prod", path), fetch(args.production + path))
        dev = cache.setdefault(("dev", path), fetch(args.development + path))
        mismatches = compare(at(prod, SECTIONS[name]), at(dev, SECTIONS[name]), name)
        results.append({"section": name, "mismatches": mismatches})
    report = {"account": args.account, "ok": all(not item["mismatches"] for item in results), "results": results}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
