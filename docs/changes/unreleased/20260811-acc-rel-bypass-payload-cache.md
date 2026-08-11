---
change_id: 20260811-acc-rel-bypass-payload-cache
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Avoid retaining full EA and Copy payloads during graph expansion

## Before and after

Even after CRM mapping was made lightweight, relationship discovery used the normal EA and Copy
payload functions. Their global dashboard cache retained a complete result for each expanded account,
which still produced linear 8777 memory growth.

## Impact

Relationship evidence calls now carry an internal `_relationship=1` marker. EA and Copy payload
functions bypass their global result-cache read/write path when that marker is present, while
interactive dashboard calls keep the existing cache and response unchanged.

## Documentation updated

Updated ACC-REL-001 and ACC-REL-003 current-state documents plus architecture, data routing and
test strategy authorities.

## Verification

API regression verifies every relationship source receives the internal marker. Full verification and
a live read-only multi-hop/memory acceptance are required before release.

## Deployment and rollback

No public API, remote database, MT Manager or port changes occur. Deploy by restarting only 8777.
Roll back by restoring the preceding account-service commit and restarting only 8777; no migration
or remote state change is involved.
