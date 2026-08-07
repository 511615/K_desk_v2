---
change_id: 20260807-1340-aut-pool-001-event-exact-reason-code
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Exact event-time no-copy reason codes

## Before and after

The event stream previously reduced a source entry to `active`, `monitor` or `risk_rejected` and the
UI guessed a combined spread, delay or external-position explanation when no decision reached it.
The Producer now persists a separate bounded `reason_code` at the moment it evaluates the entry.
The dashboard exposes it as `reasonCode`, and the UI displays the corresponding concrete Chinese
reason. Legacy events without the field state that historical detail was not saved and are never
reverse-engineered into an unsupported cause.

## Impact

This is an additive local snapshot/API observability change. It does not change pool membership,
weights, risk limits, MT order behavior or any database route. The event CSV header version advances,
so the Producer rotates the old file once through the existing schema-mismatch mechanism.

## Security and compatibility

Only an explicit reason-code allowlist reaches the API. The raw composite event reason and unknown
free text remain private. Older dashboard consumers can ignore `reasonCode`; older event rows remain
readable with an empty detail field.

## Documentation updated

AUT-POOL-001 now defines bounded event-time reasons and honest legacy fallback. Data routing records
the versioned CSV column, the API contract defines `reasonCode`, and the test strategy records the
Producer/backend/frontend regression matrix.

## Verification

Producer tests cover exact MT4/MT5 reason persistence and schema width. Backend tests cover bounded
projection and legacy compatibility. Frontend helper and mounted-page tests cover exact labels and
the removal of the unsupported combined fallback. Fast and Full verification are required before
promotion.

## Deployment and rollback

Promote only from a clean tested development branch. Restart the single Producer to adopt the new
CSV schema, then restart the guarded 8777 main service to load the API and pinned frontend. Rollback
uses the previous main commit; the rotated event archive remains recoverable evidence.
