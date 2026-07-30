from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("K_DESK_ROOT", Path(__file__).resolve().parents[2]))
SOURCE_ROOT = (Path(__file__).resolve().parents[3] / "src").resolve()
if SOURCE_ROOT.exists():
    sys.path.insert(0, str(SOURCE_ROOT))
LEGACY_RISK_ROOT = Path(r"D:\risk")
DEFAULT_PYDEPS = LEGACY_RISK_ROOT / "pydeps" if (LEGACY_RISK_ROOT / "pydeps").exists() else PROJECT_ROOT / "pydeps"
PYDEPS = Path(os.environ.get("TRADE_KLINE_PYDEPS", DEFAULT_PYDEPS))
if PYDEPS.exists():
    sys.path.insert(0, str(PYDEPS))

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from build_enhanced_trade_kline_from_cache import build_html, safe_name
from fused_trade_kline_features import enhance_trade_kline_html
from kdesk.application.kline_generation import generation_result, missing_same_source_failure, symbol_failure
from kdesk.domain.kline import (
    canonical_symbol,
    confidence_for,
    endpoint_check,
    symbol_candidates,
    validation_metrics,
    validation_passes,
)
from kdesk.infrastructure.quote_sources import QuoteSourceRegistry


DEFAULT_OUT_DIR = LEGACY_RISK_ROOT / "output_data" if LEGACY_RISK_ROOT.exists() else PROJECT_ROOT / "outputs" / "kline"
OUT_DIR = Path(os.environ.get("TRADE_KLINE_OUT_DIR", DEFAULT_OUT_DIR))
TERMINAL = os.environ.get("TRADE_KLINE_TERMINAL", r"C:\Program Files\AC Capital Market MT5 Terminal\terminal64.exe")
TIMEFRAME_LABEL = "M1"
MT5_TIMEFRAME = mt5.TIMEFRAME_M1


class SymbolValidationError(RuntimeError):
    def __init__(self, message: str, *, stage: str, code: str, metrics: dict | None = None):
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.metrics = metrics or {}


def utc(ts):
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    return ts.replace(tzinfo=timezone.utc)


def copy_rates_range_retry(symbol: str, timeframe: int, start, end, *, attempts: int = 4, delay: float = 0.6, warn: bool = True):
    """MT5 can return an empty result while a symbol's history is still syncing."""
    mt5.symbol_select(symbol, True)
    last_error = None
    for attempt in range(1, attempts + 1):
        rates = mt5.copy_rates_range(symbol, timeframe, start, end)
        if rates is not None and len(rates):
            return rates
        last_error = mt5.last_error()
        if attempt < attempts:
            time.sleep(delay * attempt)
    if warn:
        print(f"INFO: no M1 rates for {symbol} {start} -> {end}; last_error={last_error}")
    return rates


def clean_number(value):
    if pd.isna(value):
        return None
    text = str(value).replace("\xa0", " ").strip()
    if not text:
        return None
    text = text.replace(" ", "").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def extract_account_meta(table: pd.DataFrame) -> dict:
    text = " ".join(str(v).replace("\xa0", " ") for v in table.head(12).to_numpy().ravel())
    account_block = ""
    m = re.search(r"\b\d{4,}\s*\(([^)]*)\)", text)
    if m:
        account_block = m.group(1)
    parts = [p.strip() for p in account_block.split(",") if p.strip()]
    currency = parts[0].upper() if parts else ""
    leverage_match = re.search(r"\b1\s*:\s*(\d+)\b", account_block or text)
    leverage = int(leverage_match.group(1)) if leverage_match else None
    is_cent = currency in {"USC", "CENT", "CENTS", "US CENT", "US CENTS"}
    money_scale = 0.01 if is_cent else 1.0
    display_currency = "USD" if currency == "USC" else currency
    return {
        "currency": currency,
        "displayCurrency": display_currency,
        "moneyScale": money_scale,
        "isCentAccount": is_cent,
        "leverage": leverage,
        "note": f"{currency} cent account; money fields divided by 100 for USD display" if is_cent else "",
    }


def apply_account_money_scale(trades: pd.DataFrame, meta: dict) -> pd.DataFrame:
    out = trades.copy()
    scale = float(meta.get("moneyScale") or 1.0)
    money_cols = ["Commission", "Taxes", "Swap", "Profit"]
    if scale != 1.0:
        for col in money_cols:
            if col in out.columns:
                out[col] = out[col].astype(float) * scale
    out["Account Currency"] = meta.get("currency") or ""
    out["Display Currency"] = meta.get("displayCurrency") or meta.get("currency") or ""
    out["Money Scale"] = scale
    out["Is Cent Account"] = bool(meta.get("isCentAccount"))
    out["Money Unit Note"] = meta.get("note") or ""
    return out


def extract_account(table: pd.DataFrame, statement: Path) -> str:
    text = " ".join(str(v) for v in table.head(3).to_numpy().ravel())
    m = re.search(r"Account:\s*(\d+)", text, re.I)
    if m:
        return m.group(1)
    account_rows = table[table.apply(lambda row: row.astype(str).str.contains("账户", regex=False).any(), axis=1)]
    if not account_rows.empty:
        row_text = " ".join(str(v).replace("\xa0", " ") for v in account_rows.iloc[0].tolist())
        m = re.search(r"\b(\d{4,})\b", row_text)
        if m:
            return m.group(1)
    m = re.search(r"(?:Statement|ReportHistory)[_ -]?(\d+)", statement.stem, re.I)
    if m:
        return m.group(1)
    return statement.stem


def unique_headers(headers):
    seen = {}
    out = []
    for h in headers:
        h = str(h).strip()
        seen[h] = seen.get(h, 0) + 1
        out.append(h if seen[h] == 1 else f"{h}.{seen[h] - 1}")
    return out


def parse_statement(statement: Path) -> tuple[str, pd.DataFrame]:
    table = pd.read_html(statement)[0]
    account = extract_account(table, statement)
    account_meta = extract_account_meta(table)
    header_idx = None
    for idx, row in table.iterrows():
        values = [str(v).strip() for v in row.tolist()]
        if "Ticket" in values and "Open Time" in values and "Close Time" in values:
            header_idx = idx
            break
    if header_idx is None:
        return parse_chinese_report_history(table, account, statement, account_meta)

    headers = unique_headers(table.iloc[header_idx].tolist())
    trades = table.iloc[header_idx + 1 :].copy()
    trades.columns = headers
    trades = trades[trades["Type"].isin(["buy", "sell"])].copy()
    for col in ["Open Time", "Close Time"]:
        trades[col] = pd.to_datetime(trades[col], format="%Y.%m.%d %H:%M:%S", errors="coerce")
    for col in ["Ticket", "Volume", "Price", "Price.1", "S / L", "T / P", "S/L", "T/P", "Commission", "Taxes", "Swap", "Profit"]:
        if col in trades.columns:
            trades[col] = trades[col].map(clean_number)

    trades = trades.rename(columns={"Price": "Open Price", "Price.1": "Close Price"})
    trades["S/L"] = trades["S / L"] if "S / L" in trades.columns else trades["S/L"] if "S/L" in trades.columns else None
    trades["T/P"] = trades["T / P"] if "T / P" in trades.columns else trades["T/P"] if "T/P" in trades.columns else None
    if "Comment" not in trades.columns:
        trades["Comment"] = ""
    trades["Item"] = trades["Item"].astype(str).str.upper()
    trades["Holding Seconds"] = (trades["Close Time"] - trades["Open Time"]).dt.total_seconds()
    cols = [
        "Ticket",
        "Open Time",
        "Close Time",
        "Type",
        "Volume",
        "Item",
        "Open Price",
        "Close Price",
        "Commission",
        "Taxes",
        "Swap",
        "Profit",
        "S/L",
        "T/P",
        "Comment",
        "Holding Seconds",
    ]
    for col in cols:
        if col not in trades.columns:
            trades[col] = None
    trades = trades[cols].dropna(subset=["Open Time", "Close Time", "Open Price", "Close Price"])
    trades = trades.sort_values("Open Time").reset_index(drop=True)
    trades = apply_account_money_scale(trades, account_meta)
    return account, trades


def parse_chinese_report_history(table: pd.DataFrame, account: str, statement: Path, account_meta: dict | None = None) -> tuple[str, pd.DataFrame]:
    """Parse MT5 Chinese ReportHistory position-summary rows.

    Pandas expands the HTML colspan/rowspan layout into repeated and shifted
    columns. The closed-position section has stable useful columns:
    0 open time, 1 position/ticket, 2 symbol, 3 type, 12 volume,
    13 open price, 16 close time, 17 close price, 18 commission,
    19 swap, 20 profit.
    """
    if table.shape[1] < 21:
        raise RuntimeError(f"Unsupported ReportHistory table shape {table.shape}: {statement}")

    raw = table.copy()
    rows = raw[raw.iloc[:, 3].isin(["buy", "sell"])].copy()
    parsed = pd.DataFrame(
        {
            "Ticket": rows.iloc[:, 1].map(clean_number),
            "Open Time": pd.to_datetime(rows.iloc[:, 0], format="%Y.%m.%d %H:%M:%S", errors="coerce"),
            "Close Time": pd.to_datetime(rows.iloc[:, 16], format="%Y.%m.%d %H:%M:%S", errors="coerce"),
            "Type": rows.iloc[:, 3].astype(str),
            "Volume": rows.iloc[:, 12].map(clean_number),
            "Item": rows.iloc[:, 2].astype(str).str.upper(),
            "Open Price": rows.iloc[:, 13].map(clean_number),
            "Close Price": rows.iloc[:, 17].map(clean_number),
            "Commission": rows.iloc[:, 18].map(clean_number),
            "Taxes": 0.0,
            "Swap": rows.iloc[:, 19].map(clean_number),
            "Profit": rows.iloc[:, 20].map(clean_number),
            "S/L": rows.iloc[:, 14].map(clean_number),
            "T/P": rows.iloc[:, 15].map(clean_number),
            "Comment": "",
        }
    )
    parsed["Holding Seconds"] = (parsed["Close Time"] - parsed["Open Time"]).dt.total_seconds()
    cols = [
        "Ticket",
        "Open Time",
        "Close Time",
        "Type",
        "Volume",
        "Item",
        "Open Price",
        "Close Price",
        "Commission",
        "Taxes",
        "Swap",
        "Profit",
        "S/L",
        "T/P",
        "Comment",
        "Holding Seconds",
    ]
    parsed = parsed[cols].dropna(subset=["Open Time", "Close Time", "Open Price", "Close Price", "Volume"])
    parsed = parsed[parsed["Item"].ne("NAN")]
    parsed = parsed.sort_values("Open Time").reset_index(drop=True)
    if parsed.empty:
        raise RuntimeError(f"No closed buy/sell positions parsed from Chinese ReportHistory: {statement}")
    parsed = apply_account_money_scale(parsed, account_meta or extract_account_meta(table))
    return account, parsed


def stem_for(account: str, trades: pd.DataFrame) -> str:
    start = trades["Open Time"].min().strftime("%Y%m%d_%H%M%S")
    end = trades["Close Time"].max().strftime("%Y%m%d_%H%M%S")
    return f"{account}_{start}_{end}"


def parse_filter_time(value: str | None):
    if not value:
        return None
    text = str(value).strip().replace("T", " ")
    if not text:
        return None
    return pd.to_datetime(text, errors="raise")


def filter_trades(trades: pd.DataFrame, symbols: str | None = None, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    out = trades.copy()
    if symbols:
        selected = {item.strip().upper() for item in re.split(r"[,;\s]+", symbols) if item.strip()}
        if selected:
            out = out[out["Item"].astype(str).str.upper().isin(selected)].copy()
    start_ts = parse_filter_time(start)
    end_ts = parse_filter_time(end)
    if start_ts is not None:
        out = out[out["Close Time"] >= start_ts].copy()
    if end_ts is not None:
        out = out[out["Open Time"] <= end_ts].copy()
    out = out.sort_values("Open Time").reset_index(drop=True)
    if out.empty:
        raise RuntimeError("No trades left after applying symbol/time filters.")
    return out


def statement_preview(account: str, trades: pd.DataFrame) -> dict:
    symbols = []
    for symbol, group in trades.groupby("Item", sort=True):
        symbols.append(
            {
                "symbol": str(symbol),
                "trades": int(len(group)),
                "open_start": group["Open Time"].min().strftime("%Y-%m-%d %H:%M:%S"),
                "close_end": group["Close Time"].max().strftime("%Y-%m-%d %H:%M:%S"),
                "profit": float(group["Profit"].fillna(0).sum()),
            }
        )
    return {
        "account": str(account),
        "trade_count": int(len(trades)),
        "start": trades["Open Time"].min().strftime("%Y-%m-%d %H:%M:%S"),
        "end": trades["Close Time"].max().strftime("%Y-%m-%d %H:%M:%S"),
        "symbols": symbols,
    }


def base_symbol(report_symbol: str) -> str:
    return str(report_symbol).split(".")[0].upper()


def mt5_symbol_candidates(report_symbol: str, configured_aliases: dict | None = None) -> list[str]:
    available = [info.name for info in (mt5.symbols_get() or [])]
    candidates = symbol_candidates(report_symbol, available, configured_aliases)
    if not candidates:
        raise SymbolValidationError(
            f"Terminal 中找不到品种 {report_symbol}",
            stage="mapping",
            code="SYMBOL_NOT_FOUND",
            metrics={"availableSymbols": len(available)},
        )
    return candidates


def mt5_symbol_for(report_symbol: str) -> str:
    return mt5_symbol_candidates(report_symbol)[0]


def sample_even(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    if len(df) <= n:
        return df.copy()
    idx = sorted({round(i * (len(df) - 1) / (n - 1)) for i in range(n)})
    return df.iloc[idx].copy()


def distance_to_bar(price: float, row) -> float:
    if row is None:
        return np.nan
    low = float(row["low"])
    high = float(row["high"])
    if low <= price <= high:
        return 0.0
    return min(abs(price - low), abs(price - high))


def _evaluate_alignment(mt5_symbol: str, sample: pd.DataFrame, hour_delta: int) -> tuple[dict, list[dict]]:
    info = mt5.symbol_info(mt5_symbol)
    point = float(getattr(info, "point", 0) or 0)
    checks = []
    evidence = []
    for _, trade in sample.iterrows():
        for time_column, price_column in (("Open Time", "Open Price"), ("Close Time", "Close Price")):
            trade_time = trade[time_column]
            if pd.isna(trade_time) or pd.isna(trade[price_column]):
                continue
            query_time = trade_time + timedelta(hours=hour_delta)
            rates = copy_rates_range_retry(
                mt5_symbol,
                MT5_TIMEFRAME,
                utc(query_time - timedelta(minutes=2)),
                utc(query_time + timedelta(minutes=2)),
                attempts=3,
                delay=0.35,
                warn=False,
            )
            if rates is None or not len(rates):
                continue
            target = int(utc(query_time.floor("min")).timestamp())
            bar = min(rates, key=lambda row: abs(int(row["time"]) - target))
            if abs(int(bar["time"]) - target) > 60:
                continue
            check = endpoint_check(
                float(trade[price_column]),
                float(bar["low"]),
                float(bar["high"]),
                point=point,
                spread_points=float(bar["spread"]),
            )
            checks.append(check)
            evidence.append(
                {
                    "ticket": str(trade.get("Ticket", "")),
                    "endpoint": "open" if time_column == "Open Time" else "close",
                    "inside": check.inside,
                    "distance": check.distance,
                    "normalizedDistance": check.normalized_distance,
                }
            )
    return validation_metrics(checks), evidence


def choose_by_m1_envelope(
    report_symbol: str,
    trades: pd.DataFrame,
    *,
    aliases: dict | None = None,
    fallback_source: bool = False,
    allowed_hour_offsets: tuple[int, ...] = tuple(range(-4, 5)),
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    sample = sample_even(trades.sort_values("Open Time"), min(5, len(trades)))
    rows = []
    candidates = mt5_symbol_candidates(report_symbol, aliases)
    initial_offsets = tuple(offset for offset in (0, -3) if offset in allowed_hour_offsets)
    if not initial_offsets:
        initial_offsets = tuple(allowed_hour_offsets[:2])
    for candidate in candidates:
        mt5.symbol_select(candidate, True)
        for hour_delta in initial_offsets:
            metrics, _ = _evaluate_alignment(candidate, sample, hour_delta)
            rows.append({"symbol": candidate, "hourDelta": hour_delta, **metrics})
    any_initial_pass = any(validation_passes(row, fallback=fallback_source) for row in rows)
    if not any_initial_pass:
        for candidate in candidates:
            for hour_delta in (offset for offset in (-4, -2, -1, 1, 2, 3, 4) if offset in allowed_hour_offsets):
                metrics, _ = _evaluate_alignment(candidate, sample, hour_delta)
                rows.append({"symbol": candidate, "hourDelta": hour_delta, **metrics})
    valid_rows = [row for row in rows if validation_passes(row, fallback=fallback_source)]
    ranked = sorted(
        valid_rows or rows,
        key=lambda row: (
            -float(row.get("insideRatio") or 0),
            float(row.get("medianNormalizedDistance")) if row.get("medianNormalizedDistance") is not None else float("inf"),
            -int(row.get("matched") or 0),
            candidates.index(row["symbol"]),
        ),
    )
    best = ranked[0]
    if not valid_rows:
        raise SymbolValidationError(
            f"{report_symbol} 的候选报价均未通过成交端点校验",
            stage="calibration",
            code="LOW_CONFIDENCE",
            metrics={"fallback": fallback_source, "best": best, "attempts": rows},
        )
    mt5_symbol = str(best["symbol"])
    hour_delta = int(best["hourDelta"])
    mode = "report_is_GMT" if hour_delta == 0 else "report_is_GMT+3" if hour_delta == -3 else f"report_offset_{hour_delta:+d}h"
    mapping = {
        "report_symbol": report_symbol,
        "mt5_symbol": mt5_symbol,
        "time_mode": mode,
        "hour_delta": hour_delta,
        "sample_count": int(len(sample)),
        "matched_count": int(best["matched"]),
        "inside_m1_range_ratio": float(best["insideRatio"]),
        "median_distance_to_m1_range": float(best["medianNormalizedDistance"]),
        "max_distance_to_m1_range": float(best["maxNormalizedDistance"]),
        "validation_status": "accepted",
        "confidence": confidence_for(best, fallback=fallback_source),
        "fallback_source": fallback_source,
    }
    align = pd.DataFrame(
        {
            "Report Symbol": report_symbol,
            "MT5 Symbol": row["symbol"],
            "Time Mode": "report_is_GMT" if row["hourDelta"] == 0 else f"report_offset_{row['hourDelta']:+d}h",
            "Hour Delta To MT5": row["hourDelta"],
            "Sample Count": len(sample),
            "Matched Count": row["matched"],
            "Inside M1 Range Count": row["inside"],
            "Inside M1 Range Ratio": row["insideRatio"],
            "Median Normalized Distance": row["medianNormalizedDistance"],
            "Max Normalized Distance": row["maxNormalizedDistance"],
            "Accepted": validation_passes(row, fallback=fallback_source),
        }
        for row in rows
    )
    return mapping, align, sample


def load_or_fetch_bars(
    stem: str,
    report_symbol: str,
    mt5_symbol: str,
    time_mode: str,
    hour_delta: int,
    trades: pd.DataFrame,
    *,
    provider_id: str = "default",
) -> pd.DataFrame:
    cache_path = OUT_DIR / f"{stem}_{safe_name(report_symbol)}_quote_cache_{safe_name(provider_id)}_{safe_name(mt5_symbol)}_{TIMEFRAME_LABEL}_{time_mode}.csv"
    legacy_cache_path = OUT_DIR / f"{stem}_{safe_name(report_symbol)}_quote_cache_{safe_name(mt5_symbol)}_{TIMEFRAME_LABEL}_{time_mode}.csv"
    query_start = trades["Open Time"].min() + timedelta(hours=hour_delta) - timedelta(minutes=30)
    query_end = trades["Close Time"].max() + timedelta(hours=hour_delta) + timedelta(minutes=30)
    display_delta = -hour_delta
    readable_cache = cache_path if cache_path.exists() else legacy_cache_path
    if readable_cache.exists():
        bars = pd.read_csv(readable_cache, parse_dates=["time"])
        expected_start = query_start + timedelta(hours=display_delta)
        expected_end = query_end + timedelta(hours=display_delta)
        if not bars.empty and bars["time"].min() <= expected_start + timedelta(minutes=5) and bars["time"].max() >= expected_end - timedelta(minutes=5):
            print(f"cache hit: {readable_cache} rows={len(bars)}")
            return bars
        print(f"cache ignored (range mismatch): {cache_path} rows={len(bars)}")
    frames = []
    mt5.symbol_select(mt5_symbol, True)
    time.sleep(0.3)
    cursor = query_start
    while cursor < query_end:
        chunk_end = min(cursor + timedelta(days=7), query_end)
        rates = copy_rates_range_retry(mt5_symbol, MT5_TIMEFRAME, utc(cursor), utc(chunk_end), attempts=4, delay=0.7)
        if rates is not None and len(rates):
            frames.append(pd.DataFrame(rates))
            print(f"{report_symbol}/{mt5_symbol} M1 {cursor:%Y-%m-%d} -> {chunk_end:%Y-%m-%d}: {len(rates)}")
        cursor = chunk_end
    if not frames:
        raise RuntimeError(f"No M1 bars fetched for {report_symbol} -> {mt5_symbol}")
    bars = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["time"]).sort_values("time")
    bars["time"] = pd.to_datetime(bars["time"], unit="s", utc=True).dt.tz_convert(None) + timedelta(hours=display_delta)
    bars.to_csv(cache_path, index=False, encoding="utf-8-sig")
    print(f"cache saved: {cache_path} rows={len(bars)}")
    return bars


def make_price_check_from_bars(report_symbol: str, sample: pd.DataFrame, bars: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    by_minute = {t: row for t, row in bars.set_index("time").iterrows()}
    rows = []
    for _, tr in sample.iterrows():
        minute = tr["Open Time"].floor("min").to_pydatetime()
        row = by_minute.get(minute)
        out = tr.to_dict()
        out.update({"MT5 Symbol": mapping["mt5_symbol"], "Time Mode": mapping["time_mode"]})
        if row is not None:
            out.update(
                {
                    "M1 Time": minute,
                    "M1 Open": float(row["open"]),
                    "M1 High": float(row["high"]),
                    "M1 Low": float(row["low"]),
                    "M1 Close": float(row["close"]),
                    "Open Price Distance To M1 Range": distance_to_bar(float(tr["Open Price"]), row),
                }
            )
        rows.append(out)
    return pd.DataFrame(rows)


def apply_display_price_alignment(report_symbol: str, bars: pd.DataFrame, sample: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    shift = float(mapping.get("configured_price_correction") or 0.0)
    mapping["display_price_shift"] = shift
    mapping["display_price_shift_applied"] = bool(shift)
    mapping["display_price_shift_source"] = "quote-source configuration" if shift else "none"
    if not shift:
        return bars
    out = bars.copy()
    for col in ["open", "high", "low", "close"]:
        out[col] = out[col].astype(float) + shift
    print(f"{report_symbol}: applied configured price correction {shift:.8f}")
    return out


def main() -> None:
    global OUT_DIR, TERMINAL
    parser = argparse.ArgumentParser(description="Generate cached MT5 buy/sell K-line chart from a statement HTML.")
    parser.add_argument("statement", nargs="?", help="Path to statement .htm/.html")
    parser.add_argument("--trades-csv", default="", help="Path to a normalized {stem}_trades.csv file.")
    parser.add_argument("--account", default="", help="Account id used with --trades-csv when it cannot be inferred from the file name.")
    parser.add_argument("--out-dir", default=str(OUT_DIR), help=f"Output/cache directory. Default: {OUT_DIR}")
    parser.add_argument("--terminal", default=TERMINAL, help="MT5 terminal64.exe path used for read-only M1 data fetch.")
    parser.add_argument("--quote-sources", default="", help="Optional local read-only quote-source registry JSON.")
    parser.add_argument("--platform", default="", help="Order platform used to select a same-source provider.")
    parser.add_argument("--server", default="", help="Order server used to select a same-source provider.")
    parser.add_argument("--mt5-timeout", type=int, default=10000, help="MT5 initialize timeout in milliseconds.")
    parser.add_argument("--symbols", default="", help="Comma/space separated report symbols to generate, for example XAUUSD.PRO,EURUSD.PRO.")
    parser.add_argument("--start", default="", help="Only include trades overlapping this report-time start, e.g. 2026-06-01 00:00.")
    parser.add_argument("--end", default="", help="Only include trades overlapping this report-time end, e.g. 2026-06-30 23:59.")
    parser.add_argument("--inspect", action="store_true", help="Parse statement and print JSON preview only; do not connect to MT5.")
    args = parser.parse_args()
    OUT_DIR = Path(args.out_dir)
    TERMINAL = args.terminal
    statement = Path(args.statement) if args.statement else None
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.trades_csv:
        source_trades_path = Path(args.trades_csv)
        all_trades = pd.read_csv(source_trades_path, parse_dates=["Open Time", "Close Time"])
        if "Holding Seconds" not in all_trades.columns:
            all_trades["Holding Seconds"] = (all_trades["Close Time"] - all_trades["Open Time"]).dt.total_seconds()
        stem_name = source_trades_path.name
        if stem_name.endswith("_trades.csv"):
            stem_name = stem_name[: -len("_trades.csv")]
        account = args.account.strip() or stem_name.split("_", 1)[0]
    else:
        if statement is None:
            parser.error("statement is required unless --trades-csv is provided")
        account, all_trades = parse_statement(statement)
    if args.inspect:
        print(json.dumps(statement_preview(account, all_trades), ensure_ascii=False, indent=2))
        return
    trades = filter_trades(all_trades, args.symbols, args.start, args.end)
    stem = stem_for(account, trades)
    trades_path = OUT_DIR / f"{stem}_trades.csv"
    trades.to_csv(trades_path, index=False, encoding="utf-8-sig")
    print(f"account={account} trades={len(trades)} / parsed={len(all_trades)} symbols={','.join(sorted(trades['Item'].unique()))}")
    print(f"range={trades['Open Time'].min()} -> {trades['Close Time'].max()}")
    print(f"trades_csv={trades_path}")

    registry = QuoteSourceRegistry.load(TERMINAL, args.quote_sources or None)
    mapping_by_symbol: dict[str, dict] = {}
    align_parts: list[pd.DataFrame] = []
    check_parts: list[pd.DataFrame] = []
    bars_by_symbol: dict[str, pd.DataFrame] = {}
    failures: list[dict] = []
    successful_symbols: list[dict] = []
    quote_sources: dict[str, dict] = {}
    symbol_groups = sorted(trades.groupby("Item", sort=True), key=lambda item: len(item[1]), reverse=True)
    for report_symbol, group in symbol_groups:
        group = group.sort_values("Open Time").reset_index(drop=True)
        platforms = sorted({str(value).strip() for value in group.get("Platform", pd.Series(dtype=str)).dropna() if str(value).strip()})
        servers = sorted({str(value).strip() for value in group.get("Server", pd.Series(dtype=str)).dropna() if str(value).strip()})
        order_platform = args.platform or (platforms[0] if len(platforms) == 1 else "")
        order_server = args.server or (servers[0] if len(servers) == 1 else "")
        mixed_sources = len(platforms) > 1 or len(servers) > 1
        source_candidates = [] if mixed_sources else registry.candidates(order_platform, order_server)
        attempted_sources: list[str] = []
        attempt_details: list[dict] = []
        accepted = False
        accepted_options: list[dict] = []
        for provider, configured_fallback in source_candidates:
            attempted_sources.append(provider.id)
            if not mt5.initialize(path=provider.terminal, timeout=args.mt5_timeout):
                attempt_details.append({"provider": provider.id, "stage": "source", "code": "MT5_INIT_FAILED", "reason": str(mt5.last_error())})
                continue
            try:
                account_info = mt5.account_info()
                terminal_server = str(getattr(account_info, "server", "") or "")
                actual_fallback = configured_fallback
                quote_sources[provider.id] = {
                    "id": provider.id,
                    "terminal": provider.terminal,
                    "server": terminal_server,
                    "requestedServer": order_server,
                    "fallback": actual_fallback,
                    "readOnly": True,
                }
                print(f"quote source={provider.id} server={terminal_server or '-'} fallback={actual_fallback}")
                mapping, align, sample = choose_by_m1_envelope(
                    report_symbol,
                    group,
                    aliases=provider.aliases,
                    fallback_source=actual_fallback,
                    allowed_hour_offsets=provider.allowed_hour_offsets,
                )
                mapping.update(
                    {
                        "provider": provider.id,
                        "provider_server": terminal_server,
                        "requested_server": order_server,
                        "tried_quote_sources": list(attempted_sources),
                    }
                )
                correction = provider.price_corrections.get(report_symbol)
                if correction is None:
                    correction = provider.price_corrections.get(canonical_symbol(report_symbol), 0.0)
                mapping["configured_price_correction"] = float(correction or 0.0)
                bars = load_or_fetch_bars(
                    stem,
                    report_symbol,
                    mapping["mt5_symbol"],
                    mapping["time_mode"],
                    mapping["hour_delta"],
                    group,
                    provider_id=provider.id,
                )
                mapping["cache_file"] = f"{stem}_{safe_name(report_symbol)}_quote_cache_{safe_name(provider.id)}_{safe_name(mapping['mt5_symbol'])}_{TIMEFRAME_LABEL}_{mapping['time_mode']}.csv"
                bars = apply_display_price_alignment(report_symbol, bars, sample, mapping)
                accepted_options.append(
                    {"mapping": mapping, "align": align, "sample": sample, "bars": bars, "server": terminal_server}
                )
                accepted = True
                if order_server:
                    break
            except SymbolValidationError as exc:
                attempt_details.append(
                    {"provider": provider.id, "stage": exc.stage, "code": exc.code, "reason": str(exc), "metrics": exc.metrics}
                )
            except Exception as exc:
                attempt_details.append({"provider": provider.id, "stage": "quotes", "code": "QUOTE_FETCH_FAILED", "reason": str(exc)})
            finally:
                mt5.shutdown()
        if accepted:
            selected = max(accepted_options, key=lambda item: float(item["mapping"].get("confidence") or 0))
            mapping = selected["mapping"]
            bars_by_symbol[report_symbol] = selected["bars"]
            mapping_by_symbol[report_symbol] = mapping
            align_parts.append(selected["align"].assign(Provider=mapping["provider"], ProviderServer=selected["server"]))
            check_parts.append(make_price_check_from_bars(report_symbol, selected["sample"], selected["bars"], mapping))
            successful_symbols.append(
                {
                    "symbol": report_symbol,
                    "mappedSymbol": mapping["mt5_symbol"],
                    "provider": mapping["provider"],
                    "server": selected["server"],
                    "confidence": mapping["confidence"],
                    "validationStatus": "accepted",
                }
            )
            print(f"{report_symbol}: {json.dumps(mapping, ensure_ascii=False)}")
            continue
        if not attempt_details and not mixed_sources:
            failure = missing_same_source_failure(
                report_symbol,
                platform=order_platform,
                server=order_server,
                configured_providers=registry.provider_summary(),
            )
            last = failure
        else:
            last = attempt_details[-1] if attempt_details else {
                "stage": "source",
                "code": "MIXED_ORDER_SOURCES",
                "reason": "同一品种包含多个订单服务器，无法选择唯一同源报价",
            }
            failure = symbol_failure(
                report_symbol,
                stage=last["stage"],
                code=last["code"],
                quote_sources=attempted_sources,
                metrics=last.get("metrics") or {},
                reason=last["reason"],
                attempts=attempt_details,
            )
        failures.append(failure)
        mapping_by_symbol[report_symbol] = {
            "report_symbol": report_symbol,
            "validation_status": "rejected",
            "tried_quote_sources": attempted_sources,
            "failure": failure,
        }
        print(f"WARNING: skipped {report_symbol}: {last['reason']}")

    align_path = OUT_DIR / f"{stem}_alignment_sample.csv"
    (pd.concat(align_parts, ignore_index=True) if align_parts else pd.DataFrame()).to_csv(align_path, index=False, encoding="utf-8-sig")
    checks_path = OUT_DIR / f"{stem}_m1_price_check_sample.csv"
    if check_parts:
        pd.concat(check_parts, ignore_index=True).to_csv(checks_path, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame().to_csv(checks_path, index=False, encoding="utf-8-sig")
    mapping_path = OUT_DIR / f"{stem}_mapping.json"
    mapping_path.write_text(json.dumps(mapping_by_symbol, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = OUT_DIR / f"{stem}_trade_kline.html"
    if bars_by_symbol:
        chart_trades = trades[trades["Item"].isin(bars_by_symbol)].copy()
        html = enhance_trade_kline_html(build_html(account, stem, chart_trades, bars_by_symbol, mapping_by_symbol), statement, chart_trades)
        html_path.write_text(html, encoding="utf-8")

    result = generation_result(
        chart=str(html_path) if html_path.exists() else "",
        symbols=successful_symbols,
        failures=failures,
        quote_sources=list(quote_sources.values()),
    )
    result_path = OUT_DIR / f"{stem}_kline_result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("outputs")
    print(align_path)
    print(checks_path)
    print(mapping_path)
    if html_path.exists():
        print(html_path)
    print(f"KLINE_RESULT {json.dumps(result, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
