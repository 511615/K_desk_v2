---
change_id: 20260811-acc-rel-depth-overview-budget
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: improvement
status: unreleased
compatibility: compatible
---

# Link depth overview to account evidence detail

## Before and after

The relationship page used a force-directed account/evidence web, which made a broad cluster hard
to interpret and imposed a repeated quadratic browser layout cost. It now renders an account-only
concentric overview by logical discovery depth, with evidence families allocated to stable angular
sectors. Selecting an account immediately updates a separate evidence-and-peer detail view below.

Account evidence sources now receive the remaining request-wide discovery time as an additional cap.
Near the discovery deadline, a source cannot wait another full six seconds before the partial result
returns.

## Impact

The existing API response, propagation rule, Kuzu projection, threshold, read-only routing and Toxic
opt-in behavior remain compatible. The changed browser rendering is linear in the returned account
and relationship data rather than iterative force-layout work.

## Documentation updated

Updated ACC-REL-001 and ACC-REL-003 current-state documents for the linked overview/detail UI and
deadline-aware source reads.

## Verification

API page contract tests cover the overview and detail render functions. Relationship tests cover the
remaining-discovery-budget source timeout. Fast and Full governed verification run before deployment.

## Deployment and rollback

Deploy only the account service on 8777 through the governed account-only launcher. Roll back by
restarting 8777 from the preceding commit; no remote database, Kuzu source file, MT, or CRM state is changed.
