---
change_id: 20260807-1615-kln-timeline-lower-panel-full-history
features: ["KLN-TIMELINE-001"]
change_type: ui-detail
status: unreleased
compatibility: compatible
---

# Show K-line funds replay in the lower panel and remove event pagination

## Before and after

The Balance/Credit curve was duplicated below the K-line, while the K-line `资金` control did not
serve as the sole visual entry point. The curve now appears only in the existing lower panel when
the user selects `资金` alongside Profit, hand-size and position.

The detailed event table used page buttons. It now provides one continuous full-history scroll;
buffered virtual rendering retains nearby rows only, so long account histories remain responsive.

## Impact

Only the standalone K-line artifact layout and browser rendering changed. The cached source replay,
timeline payload, routes, remote read-only boundaries, data interpretation and API compatibility are
unchanged. The white high-contrast appearance remains.

## Documentation updated

Updated `KLN-TIMELINE-001` current behaviour and `TEST_STRATEGY.md`.

## Verification

Targeted artifact tests cover the lower-panel funds switch, absence of a duplicate standalone curve,
the continuous virtual table and JavaScript parsing. Full project verification is required before
release.

## Deployment and rollback

Release through the standard production script. Rollback restores the preceding application release;
no cache or remote business data is changed by this presentation update.
