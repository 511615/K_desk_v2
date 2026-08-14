---
feature_id: ACC-REL-003
title: Score-propagated Kuzu relationship investigation
module: account
status: active
apis: ["GET /kuzu-risk", "GET /api/kuzu-risk/graph", "GET /api/accounts/by-login/{login}/relationship-network"]
code: ["legacy/apps/problem_account_registry/app.py", "src/kdesk/api/account_app.py", "src/kdesk/api/kuzu_risk_page.py", "src/kdesk/application/relationship_expansion.py", "src/kdesk/application/relationship_network.py", "src/kdesk/application/relationship_risk.py", "src/kdesk/domain/relationship_propagation.py", "src/kdesk/infrastructure/kuzu_risk_graph.py", "src/kdesk/settings.py"]
tests: ["tests/test_api.py", "tests/test_kuzu_risk_graph.py", "tests/test_relationship_propagation.py", "tests/test_relationship_risk.py"]
depends_on: ["ACC-REL-001", "ACC-REL-002", "TOX-POSITION-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-08-11
---

# Score-propagated Kuzu relationship investigation

## Purpose and user entry

`/kuzu-risk?account={login}` is the account-detail relationship investigation screen. It reads the
replaced relationship endpoint, materializes returned evidence in a temporary Kuzu projection, and
renders scored relationships. Without `account`, it still supports the separate static local-file
trial.

## UI and behavior

There is no fixed hop limit: a node is visible when it has a contribution, but forwards only when
its aggregate reaches the threshold. The overview projects every returned account node and concrete
IB identity node once into concentric rings by logical account-depth. Within a ring, the stable layout
uses the full circumference rather than evidence-family sectors, so no discovered sibling is obscured
by a coincident coordinate. Nodes sharing the same immediate evidence owner and family form a compact
arc-band cluster, with visibly larger gaps between clusters; selecting a member resolves all connected
members of that evidence family in both directions for symmetric facts (CRM, LastIP, EA, Copy,
rebate, same-name and Toxic), then highlights every already-discovered outward descendant of the whole group.
Hierarchy and direct-IB-rebate facts remain source-to-target. The highlighted branch draws one
parent-to-child line per propagated relation, coloured and labelled with its evidence family; a
directional fact receives an arrowhead and names both endpoints in `来源 → 目标（关系）` form. This
makes `直属上级 IB 本人账户` unambiguous: the target is the source account's direct-superior IB
person's own trading account, not that IB's client. The overview
reports its rendered node totals, has a deeper desktop canvas, initially
fits all discovered rings, and re-fits after board resize. It shows the selected account's ancestry path
plus only that account's direct evidence cluster and outward descendants. Hidden CRM and evidence
entities are collapsed into the visible account-to-account segment and its relationship label. Accounts
that merely share the problem account as an ancestor are not connected or highlighted as if they had a
direct relationship. An entity without a resolvable root route is withheld rather than displayed as an
unexplained candidate. The lower detail view exposes that
account's relationship families, evidence and peer accounts. It explains each layer as an account-to-
account business route from the problem account. A direct subject-to-account evidence edge takes priority
over a longer ledger route in that presentation. For `直属上级 IB 本人交易账户`, the peer list is
strictly the selected account's immediate `ib_direct_account` peers; accounts that merely share the
same parent IB remain in their actual evidence family. Each evidence-family selector carries a
relationship-specific explanation instead of a generic secondary-clue label. The seed account is bright red,
expandable accounts progress from red to lighter orange as score/depth falls, and a retained
non-expandable clue is green. The overview supports pointer-centred mouse-wheel zoom and drag-to-pan.
Account circles, IB glyphs, in-node status badges and terminal markers render at 2× the original
canvas radius. Their click target scales with that visual size. The in-node badge reads only the
routed risk-system database `Status`: blank or unavailable values render as `B`, while `P`, `T`,
`TA`, and `A` retain their database shorthand, with a high-visibility ring for `T`, `TA`, and `A`.
It never uses the local ledger action or local mark, and is separate from both relationship evidence
and propagated score. A left-side extensible `风险表` presently provides one risk item: all rendered
account nodes with database status `T`, `TA` or `A`. It is a sorted status index, not an additional
risk calculation. Clicking a row selects the identical rendered node, highlighting only that node's
existing graph path and local relation evidence.
Edge captions and detail explanations use explicit evidence names: `跟单订单匹配（开仓/平仓）`
for matched copy-trading open/close orders, `跟单来源组匹配` for a shared identified source group,
and `Toxic 同向开平仓时间匹配` / `Toxic 反向开平仓时间匹配` for same-direction or opposite-direction
Toxic open/close time matches. The optional control is named `包含 Toxic 同向/反向开平仓时间匹配（较慢）`.
Clicking a visible copy-order edge opens an on-demand, read-only modal. Its first tab is scoped to
the clicked follower/master pair and lists the matched master and follower orders. Its second tab
keeps the identified master as the centre and shows every follower discovered by the existing copy
query. It reuses the current page filters and does not add an unbounded order payload to the graph
response or hold the expansion worker.
The relationship-name mapping is defined once in the initial page script, so line labels, evidence
cards, relationship-path narration and the loading/control wording cannot diverge at runtime.
The score fill and visual identity are kept independent: account circles use the strict score gradient,
IB identities are hexagons and threshold-stopped accounts are green diamonds. A score-eligible account
that was completely queried but emitted no account child shows a prominent green `叶` terminal badge;
this is distinct from a threshold-stopped node and explains a first-ring leaf. The enclosing relation
band has a separate fixed palette (CRM blue, LastIP purple, EA cyan, Copy pink, rebate gold, IB indigo,
same-name teal and Toxic rose), shown in the UI. Every sufficiently wide band carries its short
relationship label. Selecting a cluster preserves its fixed relation colour and adds a white dashed
outline instead of recolouring the band. Zoom reaches 10% to permit every ring to fit; double
click re-fits the complete discovered graph.
While its background expansion is in progress, the overview overlays a translucent rotating radar
sweep. It appears only for the visible `后台扩散中` state, continues through polling, then hides when
the task completes, fails or is idle. Its origin is continuously projected to the problem account's
current canvas coordinate, including after zoom, pan, resize or graph relayout. The SVG uses the
same dynamically sized pixel coordinate plane as Canvas. This avoids both square-letterboxing offset
and non-uniform stretching: the scan fan remains circular on a wide board; it does not intercept
canvas pointer, zoom or drag interaction.
After a completed, non-truncated scan, an account that met the expansion threshold and was queried
but produced no new account child is marked with a small teal check. The legend and selected-account
detail call this `已核查，无新增账户`; this is distinct from the green low-score `停止扩散` state.
Scores are investigation priority, not a fraud or trading conclusion.

## API contract

The primary path is `GET /api/accounts/by-login/{login}/relationship-network?threshold=1..100`.
The screen defaults to `include_toxic=false`; operators explicitly select the checkbox before the
high-cost cross-platform order match. It returns `inProgress` and processed/pending account counts
while the single-flight background expansion runs, then entities with `score`,
`hops`, `expandable`, `riskLevel`, `riskColor`, and
`scoreLedger`, alongside coverage and truncation. Account entities additively expose `databaseStatus`,
read from the account's routed MT4/MT5 risk-system database in the relationship-core status batch;
it never uses a local ledger action or changes the cached expansion payload. `GET /api/kuzu-risk/graph?threshold=1..100` remains a static
local-file trial. Invalid thresholds are rejected and Kuzu failures are sanitized.

## Data, routing and read-only constraints

Account requests reuse the governed read-only payloads and briefly write only a temporary Kuzu
projection, which is closed and removed before response. The static trial path is selected by
`KDESK_KUZU_RISK_DB`, defaulting to `runtime/<profile>/relationship_risk_graph.kuzu`. Neither path
writes AC, DBG, MT4, MT5, CRM or K_desk SQLite. Projections exclude authentication fields, API
blobs and unnecessary contact/KYC data.

## Business rules and units

Seed score is 100. An edge forwards `residual × relation strength × 0.96`; duplicate evidence in a
family retains its maximum, while independent families combine with noisy-OR. Same CRM is `0.95`,
current LastIP `0.90`, EA and Copy order `0.80`, Copy group `0.75`, rebate `0.70`, Toxic same/open
close sync `0.78`, Toxic opposite sync `0.82`, same name `0.35`, unknown `0.30`. The live path
recursively reads relations while a node remains at or above the selected threshold. The live account
path has a 30-second request-wide discovery budget, a 48-account remote-expansion cap and a
150-account direct-IB-branch cap; these return an explicitly truncated partial graph rather than
allowing one broad cluster to block 8777. Each account evidence source has a six-second wait budget.
Toxic runs only for nodes at least 30 and has a two-check budget. Each evidence read has its own
six-second source timeout; a source failure is retained in coverage but does not stop later eligible
accounts. A started same-server `LastIP` follow-up has a separate three-second maximum wait. The
result is produced by one local background expansion and equivalent page polls join it instead of
launching duplicate scans. Accounts in the same current-LastIP cohort skip repeat LastIP reads.
Each legacy evidence family has one shared local execution lane, preventing timed-out sources from
accumulating unbounded worker threads. The fixed 2,000-node and 10,000-score-expansion caps remain
as secondary graph guards and set `truncated=true` rather than claiming complete coverage. The final
request-scoped Kuzu projection is additionally capped at 120 entities and 360
relationships, ordered by subject then propagated investigation score; cap application also sets
`truncated=true`. Kuzu's native temporary graph is executed in one short-lived child process at a time,
with a four-second hard deadline. A busy, failed or timed-out child is terminated and the server returns
the same capped result from the pure propagation scorer with a `kuzuProjection` coverage failure instead
of retaining native Kuzu memory in the 8777 process.
CRM hierarchy adds explanatory ownership/direct-parent/top-group bridges at `0.05`; these preserve
the auditable path without allowing a large distribution tree to amplify risk. The separately verified
direct-IB-owned trading-account edge is `0.60`, so that account may be investigated normally. If a
discovered account's CRM user is an IB, the graph renders an explicit `IB {CRM user}` identity node.
`ib_identity` is lossless because it only exposes that same business identity. Each actual direct-rebate
payee is emitted once through `ib_direct_rebate` at `0.70`, then can continue normal IP, EA, Copy,
CRM and rebate discovery if its score meets the selected threshold. The CRM source uses one grouped
IB-ID query and returns at most 150 direct payees; an over-limit branch is explicitly marked
truncated rather than silently omitted. A top-IB aggregate remains aggregate-only and never emits
all historic downline accounts.

The overview renderer groups identical relationship branches into one representative path edge,
while the detail panel retains member-level evidence. Every rendered node keeps its ancestry path
back to the subject. Ring captions are positioned on their actual ring and empty rings are omitted.
Optional start/end datetime filters are forwarded to the read-only relationship endpoint; leaving
both blank means full history. Clicking a copy relation stores the selected edge and highlights both
endpoints with a white dashed overlay without changing the relationship colour.
Grouped representative edges also include a visible member count in their relationship label. The
detail-panel expand/merge control resolves its group from the actual relationship edge, so IB, CRM,
copy and other single-relation communities toggle the same group that is drawn on the canvas.
The page script is syntax-checked as part of the UI verification so a malformed interaction wrapper
cannot leave the canvas at “读取中…” with no nodes rendered.
Selecting an account uses the same grouped-edge policy as the overview: one relation line represents
one parent/type community. The detail relation control can explicitly expand that community to show
member edges, then merge it again without rerunning the database scan.
The coloured community band is also a direct click target for the same expand/merge action.

Canvas relation communities use one canonical key (`source account + relation family`). Therefore
same-CRM, same-IP, EA, rebate, copy-order and IB communities render as one representative line by
default, with a member count; the detail control or community band expands only that community.
Every rendered line is registered as a hit target. Clicking a line selects and highlights it (and
opens copy-order evidence when applicable), while clicking a node keeps node selection behavior.
Collapsed communities are rendered as their own canvas anchors instead of borrowing a representative
account node: members share the community anchor, the common edge terminates on that anchor, and the
anchor displays the member count. Clicking the anchor expands the members; clicking the expanded
community band or its detail control collapses them again.

## Loading, empty and failure behavior

The page shows Kuzu loading status, polls the background snapshot and reports processed/pending
accounts. Low-score nodes remain inspectable but do not expand. Missing static trial data does not
trigger a remote scan. Invalid graph shape and Kuzu failures do not expose internal paths or exceptions.

## Code and dependencies

`relationship_propagation.py` is pure scoring, `relationship_risk.py` composes source facts,
`relationship_expansion.py` bounds the single-flight background job, and
`KuzuRiskGraphRepository` owns temporary/static Kuzu reads. Canvas uses DOM `textContent` for data
and never injects evidence as HTML.
`AccountRelationshipNetworkService` obtains the routed CRM hierarchy payload through the existing
read-only legacy boundary. Same-CRM edges use its mapping-only legacy payload instead of a full
trade-history dashboard read. Relationship-only EA and Copy reads bypass the dashboard result cache,
and its aggregate query runs only for the seed account in one request.
For a current-LastIP cohort, EA/Copy discovery is performed by the representative account; sibling
accounts still expand through CRM and LastIP evidence but report their skipped automation source
coverage explicitly.

## Tests and acceptance

Unit tests cover recursive source expansion through its score threshold, one final Kuzu materialization,
single-flight pollable progress, redundant same-IP cohort lookup avoidance, bounded same-IP timeout,
Kuzu projection caps and process timeout termination, threshold stopping, noisy-OR, de-duplication,
cycles, same-IP and Toxic evidence ledger construction, and risk colour. Repository tests cover
request-scoped Kuzu materialization/readback.
API tests cover account-route replacement, page request targeting and invalid thresholds. Source tests use
mocks; they make no live writes.

## Compatibility and deprecation

The former relationship button view/response is replaced at the user's request. The standalone
Kuzu demo, account route, Copy, EA and Toxic contracts remain available.
