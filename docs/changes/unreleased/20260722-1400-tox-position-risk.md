---
change_id: 20260722-1400-tox-position-risk
features: ["TOX-POSITION-001", "TOX-POSITION-SCAN-001", "ACC-DETAIL-001", "JOB-RECOVERY-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Add account-relative heavy-position timing detection

## Before and after

Weekend detection previously treated any Friday trade held 30 hours as suspicious. Opening detection
treated any ten-minute order burst as opening betting. Both could flag ordinary small positions and did
not use historical equity, configured leverage, economic stress or the account's normal exposure. The
native model now establishes an economically heavy directional position first and only then classifies
weekend, opening or combined timing. A fourth platform-discovery tab runs the same deep rule.

## Impact

The existing two Toxic type IDs remain compatible and only their result rows are replaced. Three new
durable endpoints and one discovery job kind are additive. Remote data access remains SELECT-only.
Opening checks no longer request Tick data. No SQLite or remote schema migration is required.

## Documentation updated

Added `TOX-POSITION-001` and `TOX-POSITION-SCAN-001`; updated account detail, job recovery, business
rules, routing, ports/APIs, test strategy and operations documents.

## Verification

Focused Python tests cover economic gating, leverage, losses, combined timing, staggered additions,
scan orchestration, Worker replacement and API persistence. Frontend helper tests and the production
Vue build cover filtering, routed links and component compilation. Full governance verification is run
before release. Read-only replay classified 632185 as a 100-point weekend heavy-position event with
five same-symbol/direction peers inside five seconds, while 639631 remained capped at 39 because its
estimated margin/equity and stress/equity were only 0.3% and 0.8%. A three-day AC GB platform replay
scanned 480 candidates in 7.7 seconds, deep-checked ten accounts with no failures and ranked 632185
first after switching candidate priority from cumulative turnover to peak five-minute event risk.

## Deployment and rollback

Restart interactive and discovery workers plus the account service to load the new modules and frontend
asset. Rollback removes the new job handler/endpoints/tab and restores the two copied legacy heuristics;
existing job rows remain inert and require no migration.
