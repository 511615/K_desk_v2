---
change_id: 20260825-2340-kln-srcdoc-runtime-base
features: ["ACC-DETAIL-001", "KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Resolve the local chart runtime inside the direct K-line iframe

## Before and after

The inline chart is inserted through `iframe.srcdoc`. Its document URL is `about:srcdoc`, so the
new same-origin runtime path could not be resolved and the frame still showed a blank chart shell.
The account page now inserts an explicit base URL for its own origin before assigning the document.

## Impact

The iframe resolves `/vendor/lightweight-charts-5.0.8.js` against the local account service and can
create the K-line canvas. This applies only to the direct embedded document; standalone chart URLs
remain compatible.

## Documentation updated

Updated `docs/features/account/account-detail-legacy.md` with the `srcdoc` base-URL rule.

## Verification

The legacy account-page regression requires the base-document helper and its use when assigning
`inlineKlineFrame.srcdoc`.

## Deployment and rollback

No account, order or quote data changes. Reverting removes only the explicit `srcdoc` base binding.
