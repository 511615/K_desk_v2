# Project Instructions

## MT4 / MT5 Manager Safety Rule

- Strictly prohibit any operation in MT4 Manager or MT5 Manager other than data export.
- Allowed actions are limited to read-only inspection and exporting data required for analysis.
- All MT4/MT5 adapters in this project must expose read-only query methods only.

## Production Isolation

- `D:\risk\K_desk_ai_dev` and ports `8777` / `8766` are production until an explicit cutover.
- Development writes must remain under `D:\risk\K_desk_v2\runtime\dev`.
- Do not stop, modify, or reuse production writable data from development scripts.
