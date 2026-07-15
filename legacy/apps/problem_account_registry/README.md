# Problem Account Registry

Local web ledger for maintaining verified problem accounts.

## Service

```text
http://127.0.0.1:8776
```

Start only this service:

```powershell
powershell -ExecutionPolicy Bypass -File apps\problem_account_registry\start_account_registry_web.ps1
```

Open from this folder:

```text
open_account_registry_web.cmd
```

## Data File

The ledger Excel file is read from:

```text
local_data\problem_account_registry\problematic_accounts.xlsx
```

The web UI writes CRUD changes and version history back to this local Excel file.

## Main Features

- Add, edit, delete, and search accounts.
- Default sort by effective time from newest to oldest.
- Keep version history after edits.
- Show a vertical history timeline for each account.
- Export daily journal as Word: `journal_MMDD.docx`.
- Link accounts to generated K-line charts when matching charts exist.

## Safety Boundary

This app only reads and writes the local ledger file. It does not connect to MT4/MT5 Manager and must not modify any server-side account or trade state.

## Read-only MT5 order trace

`query_order_trace.py` checks a ticket in the final MT5 deal export first, then
falls back to the same account and a narrow time window. It can correlate a
later final deal and evaluate current account/symbol constraints. It reports
constraint-based reasons separately from an authoritative rejection log.

```text
python query_order_trace.py --server "AC GB MT5" --login 616901 \
  --ticket 349892678 --event-time "2026-07-15 03:08:09" \
  --symbol XAUUSD.CS --lots 0.06 --price 4037.22 --dealer-id 99 \
  --order-kind "Pending Order" --command "Open Order"
```

Result statuses are `executed_exact`, `rejected_logged`,
`resubmitted_or_replaced`, and `not_found`. The AC MT5 export currently has no
request/dealer journal or retcode table, so only an injected authoritative log
may produce `rejected_logged`.

## Account log query

The workbench has a read-only account log panel backed directly by the existing
MySQL trade exports. It queries `mt5_deals` and `mt4_trades` for the entered
account and exact local time range, then returns the raw database records from
every configured source. Queries are limited to 31 days and never modify MT4,
MT5, CRM, or local ledger state.
