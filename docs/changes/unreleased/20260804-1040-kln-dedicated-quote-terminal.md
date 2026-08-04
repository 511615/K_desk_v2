---
change_id: 20260804-1040-kln-dedicated-quote-terminal
features: ["KLN-DB-001", "JOB-RECOVERY-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# KLN-DB-001: Use a dedicated production quote Terminal

## Before and after

Production K-line work inherited the legacy interactive Terminal path. That Terminal could remain
as a Windows process while its MT5 API IPC channel was unavailable, causing every quote request to
fail with `-10005 IPC timeout`.

The production launcher now selects a dedicated local read-only quote Terminal. Operators can
override its path with `KDESK_KLINE_QUOTE_TERMINAL`; the launcher rejects a missing executable before
starting services.

## Impact

This changes only the local M1 quote-provider process used by K-line jobs. Order and CRM databases
remain read-only, no MT4/MT5 Manager operation is performed, and existing 8777/8766 APIs, job IDs
and artifact paths are unchanged.

## Documentation updated

Updated the K-line feature and operations runbook with the dedicated-Terminal selection, override
and IPC failure behavior. The deployment configuration is covered by a K-line regression test.

## Deployment and rollback

Restart the production K_desk processes so the account service and interactive worker inherit the
new quote Terminal path. Rollback restores the prior launcher; runtime jobs and chart artifacts need
no migration.

## Verification

The regression test asserts that the production launcher sets `TRADE_KLINE_TERMINAL` from an
override or the isolated Terminal path. A read-only generation probe for account 7002805 / AC CN
MT4 validates the selected Terminal with 100% M1 envelope coverage before deployment.
