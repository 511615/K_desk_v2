from __future__ import annotations

from pathlib import Path


def test_v2_source_contains_no_mt_trade_mutations() -> None:
    root = Path(__file__).resolve().parents[1] / "src"
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    forbidden = ("order_send(", "positions_close(", "trade_transaction(", "balance_operation(")
    assert not any(token in text for token in forbidden)
