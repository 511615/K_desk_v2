---
change_id: 20260821-acc-rel-galaxy-ring-collapse-marker
features: ["ACC-REL-003"]
change_type: modification
status: unreleased
compatibility: compatible
---

# ACC-REL-022 — Galaxy ring expand and collapse marker

- Feature: `ACC-REL-003` account relationship investigation workspace
- Scope: `K_desk_v2_rel_dev` clone on port `8977` only
- Status: implemented, awaiting user acceptance

## Change

Restore direct click on a collapsed community ring/anchor to expand that community. After expansion,
the renderer draws a small minus marker beside the ring; clicking the marker merges only that community.
The temporary group-operation list is removed from the visible workspace. Blank clicks remain inert and
the toolbar `恢复初始` button remains the explicit full reset.

## Verification

- `python -m py_compile src/kdesk/api/kuzu_risk_page.py` passed.
- `git diff --check` passed.
- Clone `8977` restarted and health check returned `ok: true`.
- Galaxy page returned HTTP 200 after restart.
- Production port `8777` was not modified or restarted.

## Before and after

Before, expanded communities lacked a reliable, isolated collapse target. After, each expanded ring exposes a
dedicated collapse marker while the community boundary remains the expansion target.

## Impact

Galaxy presentation and input handling only; data contracts and risk calculations are unchanged.

## Documentation updated

Updated the relationship workspace current-state documents and this change record.

## Deployment and rollback

Promote through dev to main and restart the account service. Roll back the release snapshot if ring controls fail.
