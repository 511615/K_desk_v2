---
change_id: 20260825-2355-kln-inline-runtime-srcdoc
features: ["ACC-DETAIL-001", "KLN-RENDER-001"]
change_type: bug_fix
status: unreleased
compatibility: compatible
---

# Inline the verified chart runtime for the sandboxed direct K-line document

## Before and after

Even with a local base URL, the sandboxed `srcdoc` iframe did not execute a separate runtime script
and the K-line frame remained a blank shell. The inline endpoint now replaces the fixed vendor tag
with the already SHA-256-verified Lightweight Charts runtime bytes before returning the document.

## Impact

The direct K-line document is self-contained at render time and can create its canvas inside the
sandboxed iframe. Standalone documents retain the same local vendor reference, so their URL contract
is unchanged.

## Documentation updated

Updated the account-detail and Lightweight renderer feature documents with the inline-runtime rule.

## Verification

The account inline-K-line API regression requires the fixed vendor tag to become the verified inline
runtime, while legacy-page tests retain the `srcdoc` base-document rule.

## Deployment and rollback

No account, trade, quote or order data changes. Reverting restores the separate local runtime tag.
