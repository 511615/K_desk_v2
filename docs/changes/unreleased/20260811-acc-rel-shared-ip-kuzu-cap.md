---
change_id: 20260811-acc-rel-shared-ip-kuzu-cap
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Bound shared-IP discovery and request-scoped Kuzu materialization

## Before and after

The score-propagated relationship endpoint applied its twelve-second discovery budget to account
evidence reads, but the later same-server MT5 `LastIP` lookup could wait on a remote MySQL view without
an independent deadline. A slow view could leave the browser loading page waiting while the account
service retained the request. The final Kuzu projection also accepted every discovered evidence entity
and relationship before temporary local materialization, which allowed a broad cluster to consume
disproportionate memory.

The follow-up `LastIP` lookup now runs under a three-second maximum wait, is clamped to remaining
discovery time, and passes the same short read/connect timeout to the legacy read-only MySQL payload.
If it does not finish, the response retains verified evidence and returns an explicit partial-coverage
timeout. Before Kuzu is opened, the projection is capped to the subject and highest-score 400 entities
and 1,200 relationships; cap use is reported through the existing `truncated` flag.

## Impact

The endpoint URL and response fields remain compatible. A slow shared-IP relation can now be absent
from a given response with a visible timeout record instead of blocking all result rendering. No
database, CRM, MT4, MT5, Manager, Kuzu source file or K_desk SQLite authority is written.

## Documentation updated

Updated ACC-REL-001, ACC-REL-003, architecture, data-routing and business-rule authorities with the
follow-up timeout, projection caps and actual 20-second browser wait behavior.

## Verification

Relationship tests prove that an uncooperative shared-IP provider returns partial coverage within its
budget and that a broad evidence graph is capped before Kuzu materialization. Governed Fast and Full
verification run before deployment, followed by a read-only localhost request for the affected account.

## Deployment and rollback

Deploy only the main-branch 8777 account service through the governed account-only launcher. Roll back
by restarting 8777 from the prior commit; no remote source or trading state changes.
