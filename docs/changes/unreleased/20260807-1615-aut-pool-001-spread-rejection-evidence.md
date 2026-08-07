---
change_id: 20260807-1615-aut-pool-001-spread-rejection-evidence
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Show numeric spread evidence for rejected copy entries

## Before and after

The event stream previously identified a spread rejection with a bounded reason code but did not
retain the values that caused the decision. Operators could not distinguish a valid high-cost
rejection from a conversion defect by looking at the dashboard. The Producer now snapshots the
account-currency spread cost per lot, configured limit, bid and ask when the spread gate rejects an
entry. The API exposes those optional values and the UI renders the exact comparison. Legacy rows
without evidence continue to use the existing bounded fallback label.

## Impact

This is an additive observability change. It does not change pool membership, weights, spread
thresholds, order sizing, order execution or database routing. The public event CSV gains optional
columns through the existing compatible schema-migration path, preserving current rows.

## Security and compatibility

Only numeric market evidence and the existing allowlisted reason code are public. Raw exceptions,
credentials, source SQL and private account-routing keys remain excluded. Existing API consumers
may ignore the new nullable fields, and old event archives remain readable.

## Documentation updated

The AUT-POOL-001 current-state document now defines the nullable numeric spread-evidence contract,
the exact UI comparison and the non-inference rule for legacy event rows.

## Verification

Producer tests cover MT4 and MT5 spread-rejection snapshots. Backend tests cover new and legacy CSV
projection. Frontend helper and mounted-page tests cover the numeric Chinese explanation and legacy
fallback. Type checking, production build, governance validation and Full repository verification
are required before promotion.

## Deployment and rollback

Promote only from the tested development branch. Restart the single Producer to adopt the additive
event columns, then restart only the guarded 8777 account service to load the API and versioned
frontend. Rollback uses the previous main commit; additive columns remain harmless to older readers.
