from __future__ import annotations

import sys
from pathlib import Path

try:
    from .account_timeline_features import inject_account_timeline
    from .position_fused_trade_kline import (
        fallback_position_meta,
        inject_fused_features,
        inject_position_meta,
        load_position_meta,
    )
except ImportError:  # script execution from the legacy tool directory
    from account_timeline_features import inject_account_timeline
    from position_fused_trade_kline import (
        fallback_position_meta,
        inject_fused_features,
        inject_position_meta,
        load_position_meta,
    )


def enhance_trade_kline_html(html: str, statement: Path | str | None = None, trades=None, timeline: dict | None = None) -> str:
    """Apply the position/no-quote fused chart layer used by the static prototype."""
    root = Path(__file__).resolve().parents[1]
    search_roots = [root, Path(r"D:\risk")]
    for item in search_roots:
        if item.exists() and str(item) not in sys.path:
            sys.path.insert(0, str(item))
    html = inject_fused_features(html)
    if statement is not None and trades is not None:
        statement_path = Path(statement)
        if statement_path.exists():
            try:
                meta = load_position_meta(statement_path, trades)
            except Exception as exc:
                meta = fallback_position_meta(trades, statement_path)
                meta["positionMetaWarning"] = str(exc)
            html = inject_position_meta(html, meta)
    if timeline is not None:
        html = inject_account_timeline(html, timeline)
    return html
