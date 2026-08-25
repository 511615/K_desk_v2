---
change_id: 20260825-1415-kln-render-compact-axis-real-timestamps
features: ["KLN-RENDER-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Preserve real timestamps on the compressed K-line axis

## Before and after

The lightweight K-line renderer uses a continuous synthetic timestamp sequence internally when
compressed time hides market-closed gaps. The time-scale labels rendered that internal sequence, so
the left edge could display the synthetic `2000年` anchor instead of the quote date.

The chart now formats every compact-axis tick from the corresponding source quote timestamp. The
compressed view still removes empty time gaps, while all visible date/time labels remain real market
timestamps.

## Impact

This changes browser presentation only. K-line payloads, bars, order timestamps, time-window inputs,
routes, quote providers and read-only data access are unchanged.

## Verification

Added a renderer regression that requires the compact axis to use its quote-time formatter. The
dedicated lightweight-renderer test suite and Python compilation pass. The release E2E also checks
the current server-rendered inline K-line section/frame instead of the removed order-details block;
final release verification runs the complete suite and frontend build.

## Documentation updated

Updated `KLN-RENDER-001` with the real-timestamp compact-axis contract and its acceptance coverage.

## Deployment and rollback

Release the already-prepared clean `main` version `2.1.4`. Rollback restores the preceding renderer
revision and restarts 8777; no data migration or external-state reversal is required.
