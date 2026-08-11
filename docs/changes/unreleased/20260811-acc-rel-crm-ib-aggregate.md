---
change_id: 20260811-acc-rel-crm-ib-aggregate
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Add bounded CRM and IB hierarchy evidence to the relationship graph

## Before and after

The relationship graph could show same-CRM accounts and rebate totals but omitted the exact path from
an account to its direct IB user's own trading account. It now projects CRM-user and direct-IB bridge
entities, exposes the IB user's routed trading account as a real expandable peer, and adds the top-IB
cohort only as a collapsed aggregate.

## Safety and performance

Top-IB membership never emits every downline account. The breadth aggregate runs for the seed only;
later recursive account reads retain the cheap direct-parent lookup without re-running the aggregate.
All remote CRM reads remain read-only and subject to the existing six-second source and twelve-second
request budgets.

## Impact

The existing relationship endpoint and Kuzu page remain compatible. Responses gain typed CRM/IB
entities and relationship labels when routed CRM hierarchy data is available. The graph has fewer
unrelated account nodes for large IB trees because aggregate membership is intentionally collapsed.

## Documentation updated

Updated ACC-REL-001, ACC-REL-003, data-routing and business-rule authorities with CRM hierarchy,
aggregate-breadth and score-propagation behavior.

## Verification

Focused network, recursive expansion, seed-only aggregate and API-contract tests cover the new
relations. Governed Fast and Full verification cover the complete application.

## Deployment and rollback

Deploy with the existing account-only 8777 launcher. Roll back by restarting the preceding commit;
there is no remote database, Kuzu, CRM or MT mutation.
