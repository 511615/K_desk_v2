---
change_id: 20260824-acc-rel-galaxy-independent-locator
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Galaxy global locator independent account projection

## Current-state change

The explicit galaxy workspace now builds its global locator directly from every returned trading
account instead of reusing the detailed graph's community-sensitive node set and coordinates. Its
deterministic concentric layout remains stable while communities in the detailed graph are expanded
or collapsed.

Locator nodes use routed database status colours in increasing severity order
`B < M < P < T < A < TA`. Blank database status continues to resolve to `B` under the existing
account-status contract.

Clicking a locator account updates the same selected-account state used by the detailed galaxy canvas.
The detailed graph and evidence panel therefore show that account's complete path to the investigation
subject and its local relationship evidence.

## Compatibility

- No API or database contract changed.
- The detailed galaxy layout, group expansion state and scoring remain unchanged.
- The default center-constrained workspace and production port 8777 are unchanged.
- The change is deployed only to the isolated relationship-development clone on port 8977 until
  separately promoted.

## Verification

- Added an API page-contract test proving that the locator reads all accounts independently of
  detailed group state, exposes the fixed status palette and dispatches account selection.
- Re-ran the legacy-galaxy graph-type and single-click-dispatcher compatibility tests.
- Parsed the rendered page script with Node.js syntax checking.

## Before and after

Before, the locator inherited detailed-community collapse state. After, it always projects every returned account with
stable risk coloring and dispatches selection into the detailed view.

## Impact

Locator presentation only; relationship discovery, scoring and detailed group state remain unchanged.

## Documentation updated

Updated the two relationship current-state documents, test strategy and this change record.

## Deployment and rollback

Promote through dev to main and restart the account service. Roll back the release snapshot to restore the prior locator.
