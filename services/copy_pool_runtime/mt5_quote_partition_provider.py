"""Read-only MT5 Tick source for quote-cache partition construction.

The provider deliberately receives an MT5-shaped object from its caller.  It
does not import MetaTrader5 and its implementation only invokes the five
read-only methods listed in ``_ALLOWED_METHODS``.  This keeps testing isolated
from a terminal and makes accidental order-routing dependencies conspicuous.
"""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol

from copy_delay_replay_domain import QuoteTick


EXPECTED_SERVER = "ACCMGlobal-Demo"
_ALLOWED_METHODS = frozenset({"initialize", "account_info", "symbol_info", "copy_ticks_range", "shutdown"})


class Mt5ReadOnlyApi(Protocol):
    def initialize(self) -> bool: ...

    def account_info(self) -> Any: ...

    def symbol_info(self, symbol: str) -> Any: ...

    def copy_ticks_range(self, symbol: str, start_utc: datetime, end_utc: datetime, flags: int) -> Iterable[Any] | None: ...

    def shutdown(self) -> None: ...


class TerminalBoundMt5Api:
    """Narrow facade that exposes no order methods from the MT5 module."""

    def __init__(self, mt5_module: Any, terminal_path: str | Path) -> None:
        self._module = mt5_module
        self._terminal_path = str(Path(terminal_path))

    def initialize(self) -> bool:
        return bool(self._module.initialize(path=self._terminal_path))

    def account_info(self) -> Any:
        return self._module.account_info()

    def symbol_info(self, symbol: str) -> Any:
        return self._module.symbol_info(symbol)

    def copy_ticks_range(
        self, symbol: str, start_utc: datetime, end_utc: datetime, flags: int
    ) -> Iterable[Any] | None:
        return self._module.copy_ticks_range(symbol, start_utc, end_utc, flags)

    def shutdown(self) -> None:
        self._module.shutdown()


def _field(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    if hasattr(value, field):
        return getattr(value, field)
    try:
        return value[field]
    except (KeyError, IndexError, TypeError):
        return None


class Mt5QuotePartitionProvider:
    """Fetch one UTC day from a verified Demo terminal and then shut it down."""

    def __init__(self, mt5_api: Mt5ReadOnlyApi, *, copy_ticks_all: int = 0, expected_server: str = EXPECTED_SERVER):
        if expected_server != EXPECTED_SERVER:
            raise ValueError(f"expected_server must be exactly {EXPECTED_SERVER}")
        self._mt5 = mt5_api
        self._copy_ticks_all = int(copy_ticks_all)
        self.expected_server = expected_server
        self._session_depth = 0

    def _open(self) -> None:
        if self._session_depth == 0:
            if self._mt5.initialize() is not True:
                raise RuntimeError("MT5 terminal initialization failed")
            account = self._mt5.account_info()
            if account is None or _field(account, "server") != EXPECTED_SERVER:
                self._mt5.shutdown()
                raise RuntimeError(f"MT5 account server must be exactly {EXPECTED_SERVER}")
        self._session_depth += 1

    def _close(self) -> None:
        if self._session_depth <= 0:
            return
        self._session_depth -= 1
        if self._session_depth == 0:
            self._mt5.shutdown()

    @contextmanager
    def session(self) -> Iterator["Mt5QuotePartitionProvider"]:
        self._open()
        try:
            yield self
        finally:
            self._close()

    def fetch_utc_day(self, provider: str, product: str, start_utc: datetime, end_utc: datetime) -> tuple[QuoteTick, ...]:
        del provider  # Cache namespace selection is owned by QuoteReplayCache.
        if start_utc.tzinfo is None or end_utc.tzinfo is None:
            raise ValueError("MT5 Tick bounds must include a timezone")
        start = start_utc.astimezone(timezone.utc)
        end = end_utc.astimezone(timezone.utc)
        if start >= end:
            raise ValueError("MT5 Tick bounds must be increasing")

        owns_session = self._session_depth == 0
        try:
            if owns_session:
                self._open()
            if self._mt5.symbol_info(product) is None:
                raise ValueError(f"MT5 product is unavailable: {product}")
            rows = self._mt5.copy_ticks_range(product, start, end, self._copy_ticks_all)
            if rows is None:
                return ()
            return tuple(
                QuoteTick(time_msc=int(_field(row, "time_msc")), bid=float(_field(row, "bid")), ask=float(_field(row, "ask")))
                for row in rows
            )
        finally:
            if owns_session:
                self._close()
