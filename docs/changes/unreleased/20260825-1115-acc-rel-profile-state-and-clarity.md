---
change_id: 20260825-1115-acc-rel-profile-state-and-clarity
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Make Galaxy profile state and terminal markers evidence-backed

## Before and after

The Galaxy profile was appended below the legacy account-detail content and compressed score, layer
and expansion status into one low-contrast card. The Canvas inferred 叶 from the absence of a
rendered account child, which could label a score-eligible account as terminal before the response
proved that the account had actually been expanded.

The profile is now prepended to the detail panel and presents account identity, propagation score,
layer, database status and expansion outcome as a high-contrast summary. The recursive response
additively records expansionState and expansionEvidenceAvailable. A leaf badge requires a
completed, evidenced account expansion and no discovered account child. A pending or unvisited
high-score account has no leaf badge; a completed high-score account states that it was expanded and
produced no new account instead of promising further expansion.

## Impact

Existing routes and scored fields remain unchanged. The two new entity fields and the corresponding
node-profile fields are additive. No score, threshold, source query, Kuzu projection, database,
remote provider or MT Manager operation changes.

## Documentation updated

Updated ACC-REL-001 and ACC-REL-003 current-state behavior and the public relationship-network
contract authority with the additive expansion-completion fields and profile presentation rule.

## Verification

Relationship-risk tests prove completed expansion metadata. Galaxy/API regressions prove that the
leaf classifier requires both completion fields, the profile is prepended and the node-profile
endpoint returns the additive state. Fast and Full governed verification are required before release.

## Deployment and rollback

Deploy by promoting the verified dev commit and restarting only 8777 through the governed release
script. Roll back by restoring the preceding verified production commit and restarting 8777; no data
migration or external state reversal is required.
