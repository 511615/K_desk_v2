---
change_id: 20260811-acc-rel-checked-leaf-marker
features: ["ACC-REL-003"]
change_type: ui
status: unreleased
compatibility: compatible
---

# Mark investigated relationship leaves without new account evidence

## Before and after

The relationship graph ended visually at both low-score stopped accounts and at accounts that met
the threshold, were queried, and produced no new account relation. Operators could not distinguish
these materially different outcomes from the graph alone.

## Impact

After a completed non-truncated scan, an expanded account with at least one available evidence
source and no account child receives a teal check marker. The legend and selected-account detail
label it `已核查，无新增账户`. Low-score non-expandable accounts remain green and keep the existing
`停止扩散` meaning.

## Documentation updated

Updated ACC-REL-003 current-state behavior and relationship-network UI regression expectations.

## Verification

The account-page regression requires the checked-leaf classifier and readable label. Fast and Full
governed checks are required before deployment.

## Deployment and rollback

Deploy by restarting only the 8777 account service. No API, database, Kuzu graph, remote provider
or MT Manager state changes. Roll back by restoring the preceding verified account-service commit
and restarting 8777.
