# Test strategy

## Gates

- Fast: governance/document checks, Python compile, Ruff and focused tests.
- Full: Fast plus all pytest/legacy tests, frontend Vitest and production build, OpenAPI and
  architecture checks.
- Release: Full plus explicitly configured read-only live contracts, version/release readiness and
  production health acceptance, including the Playwright legacy-detail route test.

## Representative server matrix

| Logical server | Stable sample |
| --- | ---: |
| AC GB MT5 | 637557 |
| AC CN MT5 | 36460 |
| AC CN MT5 live3 | 241003021 |
| AC CN MT4 | 5002693 |
| AC GB MT4 | 5010772 |
| DBG MT4 CN1 | 7798437 |
| DBG MT4 CN2 | 8325931 |
| DBG CN MT5 | 2014191 |
| DBG MT4 VN3 | 113167 |
| DBG GB MT5 | 3067746 |

Contracts cover routing, MT4/MT5, USD/USC, empty orders, old aliases and shared login `10002`.
Expected live values are maintained in an ignored local contract fixture because account data is
not committed to GitHub. Active-account fields may be declared volatile: they must remain present
and numeric, while stable routing and accounting fields retain exact/tolerance comparisons.

## Release acceptance

Both readiness endpoints, account 302360 legacy detail HTML, account 7798437 finance, Live3,
rebate, copy/EA, Toxic job recovery, K-line generation and rollback rehearsal must pass. Remote
tests are read-only and never mutate MT or CRM state.
