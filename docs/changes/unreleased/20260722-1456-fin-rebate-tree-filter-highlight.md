---
change_id: 20260722-1456-fin-rebate-tree-filter-highlight
features: ["FIN-REBATE-AUDIT-001"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Filter truly empty rebate branches and highlight excessive hierarchy rebate

## Before and after

The empty-node toggle previously retained a customer whenever CRM mapped any account to it, even
when every displayed account had zero orders and zero risk contribution. It also displayed genuine
CRM hierarchy records with no name or trading account as a dash-only card. The toggle now removes
zero-order/zero-contribution account rows and recursively removes branches with no remaining trade,
P/L, rebate or net-deposit activity.

Customer summary rows now receive a prominent red `返佣过大` warning when hierarchy rebate is
positive and customer trade P/L plus hierarchy rebate is strictly above zero. This is a visual
economic warning only and does not change the existing rebate-churning score or API payload.

## Evidence and scope

Read-only DBG CRM checks confirmed that screenshot nodes 48781, 48992 and 49265 are real
`crm_cn.sys_user_view` records under the same parent. All four name fields are NULL and none has a
row in `crm_cn.mt_users_account`, which explains the frontend `node.name || '-'` placeholder.

## Impact

The change is frontend-only and affects the shared rebate tree presentation in account audit and
platform discovery. It does not alter API responses, financial totals, audit scores, exports,
database routing or remote state.

## Documentation updated

`docs/features/finance/rebate-churning-audit.md`, `docs/BUSINESS_RULES.md` and
`docs/TEST_STRATEGY.md`.

## Verification

Frontend unit tests cover account filtering, recursive branch retention, the strict combined-value
boundary, the positive-rebate requirement and exclusion of IB rows. The focused Vitest run passed
all four cases. Fast verification passed. Full verification passed 255 Python/legacy tests, 15
frontend tests and the Vue production build.

Browser acceptance used the production `8777` page and the read-only full-history audit for DBG CN
account `2013862`. Before filtering, the rendered tree contained 81 zero-order/zero-contribution
account rows and CRM nodes 48781, 48992 and 49265. After clicking `隐藏空节点`, the count was zero and
all three empty CRM branches were absent. The 23 qualifying customer warnings remained visible with
the `返佣过大` label, dark-red background `rgb(59, 16, 25)` and red border `rgb(255, 83, 99)`.

## Deployment and rollback

No API, database, worker or local schema changes are required. Deployment rebuilds the Vue bundle
and restarts only account service 8777; K-line service 8766 remains untouched. Rollback restores the
previous helper/component bundle and restarts 8777. Remote CRM and trading data remain read-only.
