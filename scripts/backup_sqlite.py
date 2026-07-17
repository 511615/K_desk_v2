from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a consistent online SQLite backup")
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    destination = Path(args.destination).resolve()
    if not source.is_file():
        raise SystemExit(f"SQLite source does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=10) as source_connection:
        with sqlite3.connect(destination, timeout=10) as destination_connection:
            source_connection.backup(destination_connection)
            result = destination_connection.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise SystemExit(f"Backup integrity check failed: {result}")
    print(destination)


if __name__ == "__main__":
    main()
