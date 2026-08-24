---
change_id: 20260824-kln-render-baseline-and-live-generator-guard
features: ["KLN-RENDER-001", "KLN-DB-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

## Before and after

The Lightweight renderer left the Profit histogram's zero baseline implicit and used thin dashed
holding lines that were difficult to inspect in dense charts. It now explicitly anchors the
histogram at zero, uses a symmetric positive/negative range, renders profitable values red upward
and losing values green downward, and draws holding evidence with a dark halo and solid bright
lavender foreground.

The database K-line generator could fail immediately in its live-quote branch because an
offline-cache-only local import shadowed the display-price alignment helper. The local import now
contains only its cache reader, leaving the module-level helper available to both paths.

## Impact

The chart data, quote provider, execution prices, time mapping, API routes and output names are
unchanged. Manual K-line jobs now complete or return their normal structured quote/data failure
instead of raising the helper-shadowing runtime exception.

## Documentation updated

Updated KLN-RENDER-001 current state for the explicit zero baseline, colour/direction semantics and
high-contrast holding lines. Updated KLN-DB-001 current state for the live-generator runtime guard.

## Verification

Focused renderer and generator regression tests verify the explicit baseline, holding-line layers
and absence of the shadowing import. Fast governance verification is run before promotion.

## Deployment and rollback

No schema, job-payload or provider configuration change is required. Reverting this commit restores
the former renderer treatment and generator import behavior; existing chart artifacts remain valid.
