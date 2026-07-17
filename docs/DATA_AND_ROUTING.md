# Data ownership and server routing

## Local authority

Production state is under `runtime/prod`; development and tests use `runtime/dev` and
`runtime/test`. SQLite WAL, foreign keys and busy timeout are enabled. Core local entities are
accounts, account history, quick actions, login-IP observations, job runs, job events and Alembic
revision state. Excel files are import/export snapshots only.

## Remote read-only routing

| Logical server | CRM route | Trading schema | Compatibility alias |
| --- | --- | --- | --- |
| AC GB MT5 | `int_sass_crm_ac`, code 1 | `int_sass_crm_ac_mt5_live_new` | - |
| AC CN MT5 | `sass_crm_ac`, code 1 | `sass_crm_ac_mt5_live` | - |
| AC CN MT5 live3 | `sass_crm_ac`, code 3 | `sass_crm_ac_mt5_live3` | - |
| AC CN MT4 | `sass_crm_ac`, code 2 | `mt4_export_syc` | `AC MT4` |
| AC GB MT4 | `int_sass_crm_ac`, code 2 | `mt4_export_syc` | `AC MT4` resolved by account route |
| DBG CN MT5 | `crm_cn`, code 4 | `mt5_export_new` | `DBG MT5` |
| DBG GB MT5 | `crm_vn`, code 2 | `mt5_export_new` | `DBG MT5` resolved by account route |
| DBG MT4 CN1 | `crm_cn`, code 1 | `crm_cn_mt4_live1` | RiskDash live1 |
| DBG MT4 CN2 | `crm_cn`, code 3 | `crm_cn_mt4_live2` | RiskDash live2 |
| DBG MT4 VN3 | `crm_vn`, code 1 | `crm_vn_mt4_live3` | RiskDash live3 |

The same numeric login can exist on multiple logical servers. CRM schema and server code are part
of account identity. A shared physical trading schema must never be used to infer the CRM route.

## Units and time

MT4 volume is `VOLUME / 100`; MT5 volume is `Volume / 10000` or `VolumeExt / 100000000`.
Confirmed USC money values are multiplied by `0.01` for USD display; prices, volume, identifiers
and timestamps are never scaled. Database sessions use their server time; offsets are applied only
when an evidence-backed feature explicitly documents them.

## Safety

Remote adapters expose query/export only. Password, phone-password and API blob fields must never
be selected or logged. MT4/MT5 Manager state changes are prohibited.
