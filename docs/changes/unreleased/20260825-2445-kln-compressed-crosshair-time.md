---
change_id: 20260825-2445-kln-compressed-crosshair-time
features: ["KLN-RENDER-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Map compressed-axis crosshair time back to M1 source time

## Before and after

The compressed K-line axis displayed correct tick labels, but Lightweight Charts' default crosshair
formatter exposed the internal `2000-01-01` synthetic timestamp. The crosshair now uses the same
source-bar index mapping as the axis and displays the original M1 datetime.

## Impact

Compressed mode continues to remove market-closed spacing while real-time mode remains unchanged.
Only the hover/click time label changes from an internal placeholder to the quoted source time.

## Accuracy and limitations

The formatter returns the supplied bar timestamp, not a reconstructed calendar value. If no bar
matches an interaction coordinate it falls back to the existing axis formatter.

## Documentation updated

Updated the Lightweight renderer timing contract.

## Verification

The renderer regression asserts the custom localization formatter and source-time fallback. The
generated JavaScript is parsed by Node.

## Deployment and rollback

No data source or API changes are involved. Reverting restores the previous crosshair formatting.
