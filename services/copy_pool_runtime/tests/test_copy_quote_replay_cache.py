from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import numpy as np

from copy_delay_replay_domain import QuoteTick
from copy_quote_replay_cache import QUOTE_TICK_DTYPE, QuoteReplayCache


class Provider:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def fetch_utc_day(self, provider, product, start_utc, end_utc):
        self.calls += 1
        return self.rows


class QuoteReplayCacheTests(unittest.TestCase):
    def test_cold_warm_concurrent_load_stably_sorts_and_releases_mmap(self) -> None:
        day = date(2026, 7, 28)
        start = int(datetime(2026, 7, 28, tzinfo=timezone.utc).timestamp() * 1000)
        provider = Provider((QuoteTick(start + 2, 102, 103), QuoteTick(start, 100, 101), QuoteTick(start + 2, 101, 102)))
        with tempfile.TemporaryDirectory() as root:
            cache = QuoteReplayCache(root, provider)
            with ThreadPoolExecutor(max_workers=2) as pool:
                partitions = list(pool.map(lambda _index: cache.load_day("demo", "XAUUSD", day), range(2)))
            self.assertEqual(provider.calls, 1)
            self.assertEqual(partitions[0].ticks.dtype, QUOTE_TICK_DTYPE)
            self.assertEqual(partitions[0].ticks.dtype.itemsize, 24)
            self.assertEqual(partitions[0].ticks["bid"].tolist(), [100.0, 102.0, 101.0])
            self.assertFalse(partitions[0].metadata["factorReady"])
            self.assertTrue(partitions[0].metadata["quotePartitionReady"])
            for partition in partitions:
                partition.close()
            with cache.load_day("demo", "XAUUSD", day, mmap=False) as warm:
                self.assertEqual(provider.calls, 1)
                self.assertEqual(warm.ticks["time_msc"].tolist(), [start, start + 2, start + 2])

    def test_half_open_corruption_fails_closed_then_exact_rebuild_recovers(self) -> None:
        day = date(2026, 7, 28)
        start = int(datetime(2026, 7, 28, tzinfo=timezone.utc).timestamp() * 1000)
        provider = Provider((QuoteTick(start, 100, 101), QuoteTick(start + 86_400_000, 200, 201)))
        with tempfile.TemporaryDirectory() as root:
            cache = QuoteReplayCache(root, provider)
            with cache.load_day("demo", "XAUUSD", day, mmap=False) as partition:
                self.assertEqual(partition.ticks["time_msc"].tolist(), [start])
            data_path, metadata_path = cache.paths("demo", "XAUUSD", day)
            damaged = np.load(data_path, allow_pickle=False)
            damaged["bid"][0] = 100.5
            with data_path.open("wb") as handle:
                np.save(handle, damaged, allow_pickle=False)
            with self.assertRaisesRegex(ValueError, "checksum"):
                cache.load_day("demo", "XAUUSD", day, mmap=False)
            with cache.rebuild_day("demo", "XAUUSD", day, mmap=False) as rebuilt:
                self.assertEqual(rebuilt.ticks["bid"].tolist(), [100.0])
            self.assertEqual(provider.calls, 2)
            metadata_path.unlink()
            with self.assertRaisesRegex(ValueError, "incomplete"):
                cache.load_day("demo", "XAUUSD", day, mmap=False)

    def test_invalid_quotes_are_rejected_before_commit(self) -> None:
        day = date(2026, 7, 28)
        start = int(datetime(2026, 7, 28, tzinfo=timezone.utc).timestamp() * 1000)
        with tempfile.TemporaryDirectory() as root:
            cache = QuoteReplayCache(root, Provider((QuoteTick(start, 2, 1),)))
            with self.assertRaisesRegex(ValueError, "invalid bid/ask"):
                cache.load_day("demo", "XAUUSD", day)

    def test_load_range_merges_same_millisecond_without_dedup_and_reports_coverage(self) -> None:
        day_one = date(2026, 7, 28)
        day_two = day_one + timedelta(days=1)
        start_one = int(datetime(2026, 7, 28, tzinfo=timezone.utc).timestamp() * 1000)
        start_two = start_one + 86_400_000
        with tempfile.TemporaryDirectory() as root:
            cache = QuoteReplayCache(root, Provider((QuoteTick(start_one, 10, 11),)))
            cache.load_day("demo", "XAUUSD", day_one, mmap=False).close()
            cache.provider = Provider((QuoteTick(start_two + 1, 20, 21), QuoteTick(start_two + 1, 19, 20)))
            cache.load_day("demo", "XAUUSD", day_two, mmap=False).close()

            with cache.load_range(
                "demo",
                "XAUUSD",
                datetime(2026, 7, 28, 12, tzinfo=timezone.utc),
                datetime(2026, 7, 30, tzinfo=timezone.utc),
            ) as quote_range:
                self.assertTrue(quote_range.complete)
                self.assertEqual(quote_range.ticks["bid"].tolist(), [20.0, 19.0])
                self.assertEqual(quote_range.ticks["time_msc"].tolist(), [start_two + 1, start_two + 1])
                partitions = quote_range.partitions
            self.assertTrue(all(getattr(partition.ticks._mmap, "closed", False) for partition in partitions))

            data_path, _metadata_path = cache.paths("demo", "XAUUSD", day_two)
            data_path.unlink()
            with cache.load_range(
                "demo",
                "XAUUSD",
                datetime(2026, 7, 28, tzinfo=timezone.utc),
                datetime(2026, 7, 30, tzinfo=timezone.utc),
            ) as quote_range:
                self.assertFalse(quote_range.complete)
                self.assertEqual(quote_range.missing_dates, ())
                self.assertEqual(quote_range.incomplete_dates, (day_two,))

    def test_load_range_marks_checksum_failure_as_incomplete_without_fetching(self) -> None:
        day = date(2026, 7, 28)
        start = int(datetime(2026, 7, 28, tzinfo=timezone.utc).timestamp() * 1000)
        provider = Provider((QuoteTick(start, 100, 101),))
        with tempfile.TemporaryDirectory() as root:
            cache = QuoteReplayCache(root, provider)
            cache.load_day("demo", "XAUUSD", day, mmap=False).close()
            data_path, _metadata_path = cache.paths("demo", "XAUUSD", day)
            damaged = np.load(data_path, allow_pickle=False)
            damaged["bid"][0] = 100.5
            with data_path.open("wb") as handle:
                np.save(handle, damaged, allow_pickle=False)

            with cache.load_range(
                "demo",
                "XAUUSD",
                datetime(2026, 7, 28, tzinfo=timezone.utc),
                datetime(2026, 7, 29, tzinfo=timezone.utc),
            ) as quote_range:
                self.assertFalse(quote_range.complete)
                self.assertEqual(quote_range.missing_dates, ())
                self.assertEqual(quote_range.incomplete_dates, (day,))
                self.assertEqual(len(quote_range.ticks), 0)
            self.assertEqual(provider.calls, 1)


if __name__ == "__main__":
    unittest.main()
