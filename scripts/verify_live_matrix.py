from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path


def fetch(base_url: str, path: str, query: dict[str, str]) -> dict:
    url = base_url.rstrip("/") + path + "?" + urllib.parse.urlencode(query)
    with urllib.request.urlopen(url, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def close_enough(actual: object, expected: object, tolerance: float) -> bool:
    if isinstance(expected, (int, float)):
        try:
            return abs(float(actual) - float(expected)) <= tolerance
        except (TypeError, ValueError):
            return False
    return actual == expected


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the local production API against the read-only server matrix")
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8777")
    args = parser.parse_args()
    fixture_path = Path(args.fixture)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    tolerance = float(payload.get("moneyTolerance", 0.01))
    results = []
    failures = []
    for sample in payload["samples"]:
        login = str(sample["account"])
        lookup = fetch(args.base_url, "/api/account-lookup", {"account": login})
        servers = [item.get("latestSource", {}).get("server") for item in lookup.get("databases", [])]
        route_ok = sample["server"] in servers
        item = {"account": login, "server": sample["server"], "routeOk": route_ok}
        if not route_ok:
            failures.append(f"{login}: expected server {sample['server']}, got {servers}")
        expected_finance = sample.get("finance") or {}
        volatile_fields = sample.get("volatileFields", [])
        if expected_finance or volatile_fields:
            finance = fetch(
                args.base_url,
                f"/api/accounts/by-login/{urllib.parse.quote(login, safe='')}/risk-panels",
                {"platform": sample["platform"], "server": sample["server"]},
            ).get("riskPanels", {}).get("finance", {})
            mismatches = [
                key for key, expected in expected_finance.items() if not close_enough(finance.get(key), expected, tolerance)
            ]
            volatile_missing = [
                key for key in volatile_fields if not isinstance(finance.get(key), (int, float))
            ]
            item["financeMismatches"] = mismatches
            item["volatileFields"] = volatile_fields
            failures.extend(f"{login}: finance mismatch {key}" for key in mismatches)
            failures.extend(f"{login}: volatile finance field is not numeric {key}" for key in volatile_missing)
        results.append(item)
    overlap = payload.get("sharedLogin")
    if overlap:
        lookup = fetch(args.base_url, "/api/account-lookup", {"account": str(overlap["account"])})
        actual = sorted(item.get("latestSource", {}).get("server") for item in lookup.get("databases", []))
        expected = sorted(overlap["servers"])
        if actual != expected:
            failures.append(f"shared login {overlap['account']}: expected {expected}, got {actual}")
    report = {"ok": not failures, "results": results, "failures": failures}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not failures else 1)


if __name__ == "__main__":
    main()
