from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "apps" / "problem_account_registry"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import app  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


def account_meta(source: dict, login: str) -> dict:
    with app.mysql_trade_connect(source) as conn:
        with conn.cursor() as cur:
            if source.get("kind") == "mt5_deals":
                return app.query_mysql_mt5_account_meta(cur, source, login)
            meta = app.account_money_meta(source_name=source.get("name"))
            try:
                cur.execute(
                    f"select CURRENCY as Currency, `GROUP` as AccountGroup from `{source['schema']}`.`mt4_users_view` where LOGIN = %s limit 1",
                    (int(login),),
                )
                row = cur.fetchone() or {}
                if row:
                    meta = app.account_money_meta(row.get("Currency"), row.get("AccountGroup"), source.get("name"))
            except Exception:
                pass
            return meta


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    candidates_path = run_dir / "profit_prefilter_all.json"
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    source_map = {source["name"]: source for source in app.MYSQL_SOURCES}
    missing = [row for row in candidates if not row.get("currency")]
    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(account_meta, source_map[row["source"]], row["login"]): row
            for row in missing
        }
        for index, future in enumerate(as_completed(futures), start=1):
            row = futures[future]
            try:
                meta = future.result()
                scale = app.numeric_value(meta.get("moneyScale")) or 1.0
                row["currency"] = meta.get("displayCurrency") or meta.get("currency") or ""
                row["accountCurrency"] = meta.get("currency") or ""
                row["isCentAccount"] = bool(meta.get("isCentAccount"))
                row["moneyScale"] = scale
                row["periodNet"] = app.rounded(app.numeric_value(row.get("periodNetRaw")) * scale)
            except Exception as exc:
                failures.append({"source": row["source"], "login": row["login"], "error": str(exc)})
            if index % 50 == 0 or index == len(futures):
                print(f"currency audit {index}/{len(futures)}", flush=True)
    candidates.sort(key=lambda row: (-app.numeric_value(row.get("periodNet")), row["server"], app.mysql_int(row["login"])))
    corrected_top = candidates[:100]
    for rank, row in enumerate(corrected_top, start=1):
        row["correctedProfitRank"] = rank
    (run_dir / "currency_audit_all.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "currency_audit_top100.json").write_text(
        json.dumps(corrected_top, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "currency_audit_failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    original_top = json.loads((run_dir / "top100_profit.json").read_text(encoding="utf-8"))
    original_keys = {(row["source"], row["login"]) for row in original_top}
    corrected_keys = {(row["source"], row["login"]) for row in corrected_top}
    summary = {
        "audited": len(missing),
        "failures": len(failures),
        "centAccounts": sum(bool(row.get("isCentAccount")) for row in candidates),
        "top100Changed": original_keys != corrected_keys,
        "removed": sorted(original_keys - corrected_keys),
        "added": sorted(corrected_keys - original_keys),
    }
    (run_dir / "currency_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
