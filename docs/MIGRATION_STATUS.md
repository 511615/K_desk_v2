# Migration status

The modular v2 service is the active production system on ports `8777/8766`. The old standalone
directory is retained only as a rollback source. Ledger and durable jobs are native v2; account
analytics and the legacy account detail HTML still run through `LegacyBridge`.

Remaining evolution is incremental: finance/routing, trade metrics, automation, Toxic and K-line
internals move into application/domain one vertical feature at a time. Migration is complete only
when contract parity is proven; production compatibility is never traded for extraction speed.
