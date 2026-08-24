---
change_id: 20260824-kln-full-axis-zoom
features: ["KLN-RENDER-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

## Before and after

The first minimum-spacing adjustment still imposed a practical pixel floor that differed from the
legacy K-line generator. The generator zooms over its complete logical quote axis (minimum eight
bars, maximum embedded axis) and limits payload size separately.

The Lightweight renderer now permits `0.01` minimum bar spacing and refits the full content. Its
existing 30,000-display-bar payload cap and viewport-only order overlay remain the performance
boundary.

## Impact

Users can zoom out to the complete embedded M1 range. No quote, order, marker, calculation, API or
K-line-job behavior changes.

## Documentation updated

Updated KLN-RENDER-001 with the legacy full-axis zoom equivalence and retained display cap.

## Verification

Renderer tests assert the full-axis minimum spacing configuration; renderer compilation and release
verification continue to cover the generated artifact.

## Deployment and rollback

No stored data or interface changes. Reverting restores the previous `.12` pixel floor only.
