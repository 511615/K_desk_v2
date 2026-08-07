---
change_id: 20260807-1830-kln-timeline-replay-performance
features: ["KLN-TIMELINE-001"]
change_type: refactor
status: unreleased
compatibility: compatible
---

# KLN-TIMELINE-001 — Deferred replay decode and render performance

## Before and after

This is an internal performance refactor and UI responsiveness improvement. A generated K-line
artifact previously embedded every historical replay object in the
executable chart bootstrap. Large histories were synchronously parsed and allocated during page
load. Cursor updates scanned the complete Balance/Credit curve, and every funds-panel redraw
remapped the complete curve, which could stall the browser.

The replay is now embedded as compact non-executing JSON and decoded after the
first browser idle slot. The K-line bootstrap no longer contains the expanded replay. Balance and
Credit state lookup uses precomputed time indexes with binary search; the lower funds panel draws
at most one sampled point per visible pixel plus its final point. The complete cached history,
factual source-event resolution, continuous virtual table and all existing controls remain intact.

## Impact

The standalone HTML format changes only internally. No HTTP route, request field,
account data, cache key, source route, financial rule or MT/CRM operation changes.

## Compatibility and risk

Older artifacts remain readable. New artifacts require a modern
browser with `setTimeout`; browsers supporting `requestIdleCallback` use it with a 250ms timeout.
If deferred parsing fails, the existing K-line chart remains usable and the replay is omitted
rather than blocking chart load.

## Documentation updated

- `docs/features/kline/funds-and-position-replay.md`

## Verification

`tests/test_kline.py` verifies compact payload structure, absence of the replay
from the executable bootstrap, deferred decoding, indexed lookup and existing funds-panel hooks.
Full repository verification is required before release.

## Deployment and rollback

Deployment replaces only the K-line HTML injection module. Rollback to
the preceding release restores synchronous replay embedding for newly generated artifacts; no
data migration, source write or account-state change is involved.
