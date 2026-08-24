---
change_id: ACC-REL-018
features: ["ACC-REL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Galaxy selected-node path focus

## Change

When an account node is selected, the Galaxy canvas now keeps only the selected account's
immediate relationship edges and the complete account-to-subject route. Unrelated relationship
edges are hidden temporarily; the account nodes and ring context remain available for orientation.
The overview note states that the canvas is in local investigation mode.

Clicking empty canvas clears the selection, selected edge and active group while preserving any
intentional group expansion state, then redraws the original full relationship presentation.
Node, community-band and edge clicks retain priority through their existing capture handlers.

## Verification

- Python syntax compilation passed.
- Galaxy page/API regression test passed (`tests/test_api.py -k 'legacy_galaxy or galaxy_page or galaxy'`).
- 8977 clone restarted and served HTTP 200 with the focus-filter and empty-canvas reset code.
- Production port 8777 was not modified or restarted.

## Before and after

Before, selecting an account left unrelated edges visible and obscured its route. After, selection focuses the local
relationships and complete route while an explicit reset restores the initial graph.

## Impact

Galaxy selection presentation only; investigation data and scoring are unchanged.

## Documentation updated

Updated relationship-network current-state documentation and this change record.

## Deployment and rollback

Promote through dev to main and restart the account service. Roll back the release snapshot to restore prior focus behavior.
