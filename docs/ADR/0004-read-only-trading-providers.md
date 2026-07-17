# ADR-0004: Trading providers are read-only

- Status: Accepted
- Date: 2026-07-17

MySQL and MT adapters expose query/export methods only. MT4/MT5 Manager state changes are prohibited
by policy, code scanning and review.
