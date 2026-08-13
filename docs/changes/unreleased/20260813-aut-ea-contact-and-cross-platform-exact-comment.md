---
change_id: 20260813-aut-ea-contact-and-cross-platform-exact-comment
features: ["AUT-EA-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# EA contact Comment and cross-platform exact lookup

## Before and after

Exact Comment EA lookup searched only the selected platform and treated a pure contact Comment as
an excluded note. It now treats a complete contact Comment as a user-directed exact EA key and
searches every configured MT4 and MT5 source.

## Impact

One complete Comment produces one group across platforms, databases and servers. Existing group,
member, Excel and API fields remain compatible; the result can include additional MT4/MT5 members.
ExpertID/MAGIC remains evidence only. System events, balance operations, stop/limit suffixes and
known routing formats retain their existing handling.

## Documentation updated

Updated AUT-EA-001 and the central data-routing authority. Generated registry/OpenAPI artifacts
remain required.

## Verification

Added regressions for pure contact Comment classification, cross-MT4/MT5 exact target selection and
single-group seed merging. Full Python/API/report/frontend verification is required before deployment.
All remote MT/CRM reads remain read-only.

## Deployment and rollback

Deploy by restarting only the 8777 account service after verification. Rollback is the paired Git
commit and an 8777 restart; no remote or MT Manager state is altered.
