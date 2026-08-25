---
change_id: 20260825-2405-kln-renderer-script-parse
features: ["KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Restore parsing of the direct K-line renderer

## Before and after

The conditional expression that selects Profit or Volume rows in the lower pane had one extra
closing parenthesis. Browsers therefore rejected the generated renderer script before it could
create the Lightweight Charts canvas, leaving the direct account K-line frame blank. The expression
now closes only the value-limit, maximum, slice and Profit grouping calls.

## Impact

The direct account K-line keeps the same endpoint, cached quote data, chart controls and panel
semantics. It now initializes instead of showing only the static document shell.

## Documentation updated

Updated the Lightweight renderer current-state document with the generated-script parse guard.

## Verification

The focused renderer test asserts the exact active Profit/Volume row expression. The generated
document's executable script is parsed with Node before promotion, in addition to the existing
renderer, API and legacy-account tests.

## Deployment and rollback

No account, trade, quote or order data changes. Reverting this commit restores the previous
renderer expression and is not recommended because it reintroduces the blank direct chart.
