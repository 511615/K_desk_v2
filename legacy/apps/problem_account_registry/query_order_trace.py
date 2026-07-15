from __future__ import annotations

import argparse
import json

import app
from order_trace import MT5OrderTraceQuery, OrderTraceRequest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only MT5 order/request trace")
    parser.add_argument("--server", required=True)
    parser.add_argument("--login", required=True, type=int)
    parser.add_argument("--ticket", required=True, type=int)
    parser.add_argument("--event-time", required=True)
    parser.add_argument("--symbol", default="")
    parser.add_argument("--lots", type=float, default=0)
    parser.add_argument("--price", type=float, default=0)
    parser.add_argument("--dealer-id", type=int, default=0)
    parser.add_argument("--order-kind", default="")
    parser.add_argument("--command", default="")
    parser.add_argument("--window-seconds", type=int, default=30)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = next(
        (item for item in app.MYSQL_SOURCES if item.get("name") == args.server),
        None,
    )
    if source is None:
        raise SystemExit(f"Unknown server: {args.server}")
    request = OrderTraceRequest.from_mapping(
        {
            "login": args.login,
            "ticket": args.ticket,
            "event_time": args.event_time,
            "symbol": args.symbol,
            "lots": args.lots,
            "price": args.price,
            "dealer_id": args.dealer_id,
            "order_kind": args.order_kind,
            "command": args.command,
        }
    )
    result = MT5OrderTraceQuery(source, app.mysql_trade_connect).run(
        request,
        window_seconds=args.window_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
