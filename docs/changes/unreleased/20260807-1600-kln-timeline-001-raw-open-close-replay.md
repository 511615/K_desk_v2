---
change_id: 20260807-1600-kln-timeline-raw-open-close-replay
features: ["KLN-TIMELINE-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Retain raw opening and closing ledger events in K-line funds replay

## Before and after

The prior K-line table folded a market Position's opening and closing Deals into one summary row.
That presentation hid the intermediate account states needed for a historical funds reconstruction.
The table now retains every funding event, order opening and order closing in factual chronological
order. Each row displays the Balance and Credit immediately after that source event.

## Impact

Only the generated K-line artifact's replay presentation and its pure timeline payload changed.
Existing generation routes, cache ownership, local-only artifact handling, checkbox location,
white high-contrast layout, remote read-only restrictions and K-line controls remain unchanged.
No remote data, MT4/MT5 state, database schema or API contract is modified.

## Documentation updated

Updated `KLN-TIMELINE-001` current behaviour and the K-line test strategy.

## Verification

Targeted timeline and artifact tests verify raw open/close ordering, post-event state fields,
header wording, white styling and JavaScript parsing. Full governance validation is required before
release.

## Deployment and rollback

Release through the standard production script. Rollback restores the previous application release;
cached source replay data remains read-only and is not mutated by this presentation correction.
