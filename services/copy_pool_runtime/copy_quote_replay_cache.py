"""Shared, validated UTC-day quote partitions for pure delay replay."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable, Protocol

import numpy as np

from copy_delay_replay_domain import QuoteTick


QUOTE_TICK_DTYPE = np.dtype([("time_msc", "<i8"), ("bid", "<f8"), ("ask", "<f8")], align=True)
if QUOTE_TICK_DTYPE.itemsize != 24:
    raise RuntimeError("Quote Tick cache records must be exactly 24 bytes")


class QuotePartitionProvider(Protocol):
    def fetch_utc_day(self, provider: str, product: str, start_utc: datetime, end_utc: datetime) -> Iterable[QuoteTick]: ...


@dataclass
class QuotePartition:
    provider: str
    product: str
    utc_date: date
    ticks: np.ndarray
    metadata: dict[str, object]

    def close(self) -> None:
        mapping = getattr(self.ticks, "_mmap", None)
        if mapping is not None and not getattr(mapping, "closed", False):
            mapping.close()

    def __enter__(self) -> "QuotePartition":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


@dataclass
class QuoteRange:
    """A bounded, cache-only quote range with explicit coverage evidence.

    ``ticks`` may contain the validated portions of a partially cached range,
    but consumers must require ``complete`` before using it for a factor.  The
    referenced partitions remain open until ``close`` so mmap ownership is
    explicit and safe for callers that inspect the evidence.
    """

    provider: str
    product: str
    start_utc: datetime
    end_utc: datetime
    ticks: np.ndarray
    partitions: tuple[QuotePartition, ...]
    missing_dates: tuple[date, ...]
    incomplete_dates: tuple[date, ...]

    @property
    def complete(self) -> bool:
        return not self.missing_dates and not self.incomplete_dates

    def close(self) -> None:
        for partition in self.partitions:
            partition.close()

    def __enter__(self) -> "QuoteRange":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


def _utc_day(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("datetime cache dates must include a timezone")
        return value.astimezone(timezone.utc).date()
    return value if isinstance(value, date) else date.fromisoformat(value)


def _day_bounds(value: date) -> tuple[datetime, datetime, int, int]:
    start = datetime.combine(value, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end, int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _utc_range(start_utc: datetime, end_utc: datetime) -> tuple[datetime, datetime]:
    if start_utc.tzinfo is None or end_utc.tzinfo is None:
        raise ValueError("Quote range bounds must include a timezone")
    start = start_utc.astimezone(timezone.utc)
    end = end_utc.astimezone(timezone.utc)
    if start >= end:
        raise ValueError("Quote range must have start_utc before end_utc")
    return start, end


def _range_days(start_utc: datetime, end_utc: datetime) -> tuple[date, ...]:
    """Return UTC days intersecting the half-open range [start_utc, end_utc)."""
    last = (end_utc - timedelta(microseconds=1)).date()
    days: list[date] = []
    current = start_utc.date()
    while current <= last:
        days.append(current)
        current += timedelta(days=1)
    return tuple(days)


def _safe(value: str) -> str:
    if not value or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-" for character in value):
        raise ValueError("provider and product cache keys must be simple ASCII identifiers")
    return value


def _checksum(ticks: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(ticks).tobytes()).hexdigest()


def _validate(ticks: np.ndarray, start_ms: int, end_ms: int) -> None:
    if ticks.dtype != QUOTE_TICK_DTYPE or ticks.dtype.itemsize != 24:
        raise ValueError("Quote Tick cache dtype must be int64/float64/float64, 24 bytes")
    if len(ticks) and (np.any(ticks["time_msc"] < start_ms) or np.any(ticks["time_msc"] >= end_ms)):
        raise ValueError("Quote Tick cache violates its half-open UTC-day boundary")
    if len(ticks) > 1 and np.any(ticks["time_msc"][1:] < ticks["time_msc"][:-1]):
        raise ValueError("Quote Tick cache must be sorted without dropping same-millisecond ticks")
    if not (np.isfinite(ticks["bid"]).all() and np.isfinite(ticks["ask"]).all()):
        raise ValueError("Quote Tick cache contains non-finite quotes")
    if np.any(ticks["bid"] <= 0) or np.any(ticks["ask"] < ticks["bid"]):
        raise ValueError("Quote Tick cache contains invalid bid/ask values")


def _to_array(rows: Iterable[QuoteTick], start_ms: int, end_ms: int) -> np.ndarray:
    indexed: list[tuple[int, QuoteTick]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, QuoteTick):
            raise TypeError("Quote provider must return QuoteTick records")
        if start_ms <= row.time_msc < end_ms:
            indexed.append((index, row))
    indexed.sort(key=lambda item: (item[1].time_msc, item[0]))
    data = np.empty(len(indexed), dtype=QUOTE_TICK_DTYPE)
    for index, (_source_index, row) in enumerate(indexed):
        data[index] = (row.time_msc, row.bid, row.ask)
    _validate(data, start_ms, end_ms)
    return data


class QuoteReplayCache:
    """Day partitions are cache evidence only; they never certify a customer factor by themselves."""

    _locks_guard = threading.Lock()
    _partition_locks: dict[Path, threading.Lock] = {}

    def __init__(self, root: str | Path, provider: QuotePartitionProvider):
        self.root = Path(root)
        self.provider = provider

    @classmethod
    def _lock_for(cls, data_path: Path) -> threading.Lock:
        with cls._locks_guard:
            return cls._partition_locks.setdefault(data_path.resolve(), threading.Lock())

    def paths(self, provider: str, product: str, utc_date: date | datetime | str) -> tuple[Path, Path]:
        day = _utc_day(utc_date)
        stem = f"{_safe(provider)}__{_safe(product)}__{day.isoformat()}"
        return self.root / f"{stem}.npy", self.root / f"{stem}.json"

    def load_day(self, provider: str, product: str, utc_date: date | datetime | str, *, mmap: bool = True) -> QuotePartition:
        day = _utc_day(utc_date)
        data_path, metadata_path = self.paths(provider, product, day)
        start, end, start_ms, end_ms = _day_bounds(day)
        with self._lock_for(data_path):
            data_exists = data_path.exists()
            metadata_exists = metadata_path.exists()
            if data_exists or metadata_exists:
                if not data_exists or not metadata_exists:
                    raise ValueError("Quote Tick cache partition is incomplete; use rebuild_day")
                return self._read(provider, product, day, data_path, metadata_path, start_ms, end_ms, mmap)
            ticks = _to_array(self.provider.fetch_utc_day(provider, product, start, end), start_ms, end_ms)
            metadata = self._metadata(provider, product, day, ticks)
            self._write(data_path, metadata_path, ticks, metadata)
            return self._read(provider, product, day, data_path, metadata_path, start_ms, end_ms, mmap)

    def load_range(self, provider: str, product: str, start_utc: datetime, end_utc: datetime, *, mmap: bool = True) -> QuoteRange:
        """Load existing UTC-day partitions without fetching or silently filling gaps.

        A missing pair of files is reported in ``missing_dates``.  A partial
        partition or a partition that fails its commit/metadata/checksum
        validation is reported in ``incomplete_dates``.  This lets factor
        callers fail closed without losing the evidence needed for diagnosis.
        """
        start, end = _utc_range(start_utc, end_utc)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        partitions: list[QuotePartition] = []
        missing: list[date] = []
        incomplete: list[date] = []
        try:
            for day in _range_days(start, end):
                data_path, metadata_path = self.paths(provider, product, day)
                with self._lock_for(data_path):
                    data_exists = data_path.exists()
                    metadata_exists = metadata_path.exists()
                    if not data_exists and not metadata_exists:
                        missing.append(day)
                        continue
                    if not data_exists or not metadata_exists:
                        incomplete.append(day)
                        continue
                    try:
                        _day_start, _day_end, day_start_ms, day_end_ms = _day_bounds(day)
                        partitions.append(self._read(provider, product, day, data_path, metadata_path, day_start_ms, day_end_ms, mmap))
                    except ValueError:
                        incomplete.append(day)

            slices = [
                partition.ticks[(partition.ticks["time_msc"] >= start_ms) & (partition.ticks["time_msc"] < end_ms)]
                for partition in partitions
            ]
            non_empty = [values for values in slices if len(values)]
            if non_empty:
                # Partitions are read in UTC-day order.  Stable sort preserves
                # their source order for any same-millisecond values.
                ticks = np.concatenate(non_empty).astype(QUOTE_TICK_DTYPE, copy=False)
                ticks = ticks[np.argsort(ticks["time_msc"], kind="stable")]
            else:
                ticks = np.empty(0, dtype=QUOTE_TICK_DTYPE)
            return QuoteRange(
                provider=provider,
                product=product,
                start_utc=start,
                end_utc=end,
                ticks=ticks,
                partitions=tuple(partitions),
                missing_dates=tuple(missing),
                incomplete_dates=tuple(incomplete),
            )
        except Exception:
            for partition in partitions:
                partition.close()
            raise

    def rebuild_day(self, provider: str, product: str, utc_date: date | datetime | str, *, mmap: bool = True) -> QuotePartition:
        """Explicit recovery of one exact provider/product/day partition after corruption or interruption."""
        day = _utc_day(utc_date)
        data_path, metadata_path = self.paths(provider, product, day)
        with self._lock_for(data_path):
            data_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
        return self.load_day(provider, product, day, mmap=mmap)

    def _metadata(self, provider: str, product: str, day: date, ticks: np.ndarray) -> dict[str, object]:
        return {
            "schema": "copy_quote_replay_cache/v2",
            "commitId": uuid.uuid4().hex,
            "provider": provider,
            "product": product,
            "utcDate": day.isoformat(),
            "count": int(len(ticks)),
            "minTimeMsc": int(ticks["time_msc"][0]) if len(ticks) else None,
            "maxTimeMsc": int(ticks["time_msc"][-1]) if len(ticks) else None,
            "checksum": _checksum(ticks),
            "dtype": [[name, value] for name, value in ticks.dtype.descr],
            "recordBytes": 24,
            "factorReady": False,
            "quotePartitionReady": True,
        }

    def _read(self, provider: str, product: str, day: date, data_path: Path, metadata_path: Path, start_ms: int, end_ms: int, mmap: bool) -> QuotePartition:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            ticks = np.load(data_path, mmap_mode="r" if mmap else None, allow_pickle=False)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"Unreadable quote cache partition: {error}") from error
        expected = {
            "schema": "copy_quote_replay_cache/v2",
            "provider": provider,
            "product": product,
            "utcDate": day.isoformat(),
            "recordBytes": 24,
            "factorReady": False,
            "quotePartitionReady": True,
        }
        if not isinstance(metadata.get("commitId"), str) or not metadata["commitId"]:
            self._close_array(ticks)
            raise ValueError("Quote Tick cache has no completed commit marker")
        if any(metadata.get(key) != value for key, value in expected.items()):
            self._close_array(ticks)
            raise ValueError("Quote Tick cache metadata does not match the requested partition")
        try:
            _validate(ticks, start_ms, end_ms)
            expected_dtype = [[name, value] for name, value in QUOTE_TICK_DTYPE.descr]
            minimum = int(ticks["time_msc"][0]) if len(ticks) else None
            maximum = int(ticks["time_msc"][-1]) if len(ticks) else None
            if (
                metadata.get("count") != int(len(ticks))
                or metadata.get("dtype") != expected_dtype
                or metadata.get("minTimeMsc") != minimum
                or metadata.get("maxTimeMsc") != maximum
                or metadata.get("checksum") != _checksum(ticks)
            ):
                raise ValueError("Quote Tick cache checksum or count validation failed")
        except Exception:
            self._close_array(ticks)
            raise
        return QuotePartition(provider, product, day, ticks, metadata)

    @staticmethod
    def _close_array(ticks: np.ndarray) -> None:
        mapping = getattr(ticks, "_mmap", None)
        if mapping is not None and not getattr(mapping, "closed", False):
            mapping.close()

    def _write(self, data_path: Path, metadata_path: Path, ticks: np.ndarray, metadata: dict[str, object]) -> None:
        data_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_id = uuid.uuid4().hex
        data_tmp = data_path.with_name(data_path.name + f".{temporary_id}.tmp")
        metadata_tmp = metadata_path.with_name(metadata_path.name + f".{temporary_id}.tmp")
        try:
            with data_tmp.open("xb") as handle:
                np.save(handle, ticks, allow_pickle=False)
            metadata_tmp.write_text(json.dumps(metadata, ensure_ascii=True, sort_keys=True), encoding="utf-8")
            os.replace(data_tmp, data_path)
            # Metadata is the commit marker and is intentionally replaced last.
            os.replace(metadata_tmp, metadata_path)
        finally:
            data_tmp.unlink(missing_ok=True)
            metadata_tmp.unlink(missing_ok=True)
