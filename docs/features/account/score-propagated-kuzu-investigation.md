---
feature_id: ACC-REL-003
title: Score-propagated Kuzu relationship investigation
module: account
status: active
apis: ["GET /kuzu-risk", "GET /api/kuzu-risk/graph", "GET /api/accounts/by-login/{login}/relationship-network", "GET /api/accounts/by-login/{login}/relationship-network/node-profile", "GET /api/accounts/by-login/{login}/relationship-network/relation-detail"]
code: ["legacy/apps/problem_account_registry/app.py", "src/kdesk/api/account_app.py", "src/kdesk/api/kuzu_3d_preview_page.py", "src/kdesk/api/kuzu_focus_workspace_page.py", "src/kdesk/api/kuzu_graph_type_page.py", "src/kdesk/api/kuzu_risk_page.py", "src/kdesk/application/relationship_expansion.py", "src/kdesk/application/relationship_inspection.py", "src/kdesk/application/relationship_network.py", "src/kdesk/application/relationship_process.py", "src/kdesk/application/relationship_risk.py", "src/kdesk/application/trade_relationship_detection.py", "src/kdesk/domain/ib_rebate_anomaly.py", "src/kdesk/domain/relationship_graph.py", "src/kdesk/domain/relationship_propagation.py", "src/kdesk/infrastructure/kuzu_risk_graph.py", "src/kdesk/settings.py"]
tests: ["tests/test_api.py", "tests/test_ib_rebate_anomaly.py", "tests/test_kuzu_risk_graph.py", "tests/test_relationship_graph.py", "tests/test_relationship_inspection.py", "tests/test_relationship_propagation.py", "tests/test_relationship_risk.py", "tests/test_trade_relationship_detection.py"]
depends_on: ["ACC-REL-001", "ACC-REL-002", "TOX-POSITION-001", "TOX-PUSH-001", "TOX-HEDGE-001"]
last_verified_version: 2.1.2
last_verified_date: 2026-08-25
---

# Score-propagated Kuzu relationship investigation

The investigation snapshot is also the bounded source for lazy node profiles and relation evidence.
Profile/relation requests may carry the snapshot revision; a stale revision receives HTTP 409 instead
of mixing evidence from different snapshots. The default profile range is the latest 90 days, while
explicit start/end values follow the relationship investigation. Slow cross-server open/close and
suspected-hedge matching remains an incremental background source and cannot block static relationship
or cached profile interaction. Partial source failure is disclosed in coverage and never clears facts
already present in the graph.

## Purpose and user entry

`/kuzu-risk?account={login}` is the account-detail relationship investigation screen. Its default
renderer is `focus-force`, the center-constrained investigation workspace. The original galaxy page
is retained only at `graph_type=galaxy`, and `graph_type=choose` retains the selector. Unknown or
missing graph-type values resolve to `focus-force`. Without `account`, the page still supports the
separate static local-file trial.

## UI and behavior

The default focus workspace separates global location, local relationship detail and evidence. It
renders a relationship entity once, connects its member accounts to that entity and avoids the
pairwise edge web. Clicking an account exposes its routed database status and compatible account
detail link. It polls the existing single-flight expansion snapshots every two seconds, pauses polling
while the page is hidden, updates available partial evidence immediately, and stops polling only when
`inProgress=false` or the bounded client poll window expires. A saturated coordinator asks the page to
retry after three seconds. It reads `databaseStatus` directly and uses `B` only for a blank value.

Relationship communities are collapsed by default. Their boundary is clickable and toggles a local
presentation state without restarting the investigation: collapsed state shows the member count,
the highest member status in `TA > A > T > P > M > B` order and one aggregate edge; expanded state
shows the individual accounts and evidence edges inside that community. Each community toggles
independently, and the right evidence panel exposes the same action for keyboard-accessible use.

The selector also exposes the isolated `focus-3d` preview. It is a Canvas projection of the same
read-only snapshot: the subject remains at the sphere origin, each hop is distributed on a deterministic
spherical shell, drag rotates the camera, and the wheel changes camera distance. A stable left-side 2D
top-down X/Z locator shows the same nodes and selection path while the 3D view rotates. Selecting a
node highlights its path to the subject. This mode is presentation-only and does not replace the default
2D evidence workspace.

The explicit galaxy compatibility view retains the following behavior. There is no fixed hop limit: a node is visible when it has a contribution, but forwards only when
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
The galaxy workspace locator is a separate, account-only projection rather than a miniature of the
currently expanded detailed graph. It always shows all returned trading accounts, assigns their rings
from logical account depth, and therefore does not lose nodes when a detailed relationship community
is collapsed or expanded. Locator colour comes from routed database status with severity order
`B < M < P < T < A < TA`. Selecting a locator node updates the shared selected-account state and
renders the same complete subject path and evidence detail as a direct click in the detailed graph.
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
and `主订单同向开平仓同步` / `疑似对锁（反向同步开平仓）` for the two cross-account trade
detections. The same-direction detector uses principal orders, two-second open/close windows and a
recurrence floor. The opposite detector uses five-second open/close windows and at least 80% lot
similarity. Repeated order pairs are evidence details of one peer relationship, not parallel graph edges.
The compatibility canvas has one authoritative capture-phase click dispatcher backed by a frozen
post-render hit frame. It does not recompute or mutate ring layout during hit testing. Expanded-group
collapse markers take precedence over overlapping member nodes; visible nodes take precedence over
collapsed boundaries; boundaries take precedence over edges. Every click is consumed by this
dispatcher, including blank clicks, so older compatibility listeners cannot cause double toggles,
stale-coordinate misses or a node selection and group toggle from the same gesture.
Clicking a visible copy-order edge opens an on-demand, read-only modal. Its first tab is scoped to
the clicked follower/master pair and lists the matched master and follower orders. Its second tab
keeps the identified master as the centre and shows every follower discovered by the existing copy
query. It reuses the current page filters and does not add an unbounded order payload to the graph
response or hold the expansion worker.
The relationship-name mapping is defined once in the initial page script, so line labels, evidence
cards, relationship-path narration and the loading/control wording cannot diverge at runtime.
The score fill and visual identity are kept independent: account circles use the strict score gradient,
IB identities are hexagons and threshold-stopped accounts are green diamonds. A prominent green 叶
terminal badge requires the completed expansionState=expanded and available evidence confirmation,
as well as no account child. It is never inferred from a high score plus an empty currently rendered
child list. The selected account profile is prepended above the legacy Galaxy detail section and
foregrounds the account, propagation score, layer, database status and expansion outcome; a completed
high-score investigation therefore reads 已完成扩散 · 无新增账户, not 继续扩散. The enclosing relation
band has a separate fixed palette (same-name blue, LastIP purple, CID violet, EA cyan, Copy pink, rebate gold, IB indigo,
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
`hops`, `expandable`, additive `expansionState`, additive `expansionEvidenceAvailable`, `riskLevel`, `riskColor`, and
`scoreLedger`, alongside coverage and truncation. Account entities additively expose `databaseStatus`,
read from the account's routed MT4/MT5 risk-system database in the relationship-core status batch;
it never uses a local ledger action or changes the cached expansion payload. The additive
`presentationGraph` contains relation entities and auditable paths without changing propagation
scores or the existing `entities`/`relationships` contract. `GET /api/kuzu-risk/graph?threshold=1..100` remains a static
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
path has no request-wide discovery deadline, but retains a 48-account remote-expansion cap and a
150-account direct-IB-branch cap; these return an explicitly truncated partial graph rather than
allowing one broad cluster to grow without bounds. Each account evidence source has a 120-second hard ceiling.
The optional cross-account trade detector runs only for nodes at least 30 and has a two-check budget.
It scans the configured AC/DBG MT4+MT5 sources in one bounded batch per account, reports partial source
coverage, and emits at most one edge per peer and detection type. Each evidence read has its own
120-second source timeout; a source failure is retained in coverage but does not stop later eligible
accounts. A started same-server `LastIP` or current MT5 `ClientID` follow-up has a separate three-second maximum wait. The
result is produced by one local background expansion and equivalent page polls join it instead of
launching duplicate scans. Accounts in the same current-LastIP/CID cohort skip repeat cohort reads.
In production, that expansion always runs in a disposable child process with a 45-second wall-clock
ceiling. This outer ceiling is independent of the source budgets: it terminates an over-limit child,
retains the newest available partial snapshot as truncated evidence, and releases its process memory
without blocking the 8777 account service.
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
`ib_identity` is lossless because it only exposes that same business identity. A direct-IB branch no
longer emits every payee. It emits a payee once through `ib_direct_rebate` at `0.70` only when the
selected-period account is rebate-dominated profitable or its database status is `P` or higher; that
account can then continue normal IP, EA, Copy, CRM and rebate discovery if its score meets the selected
threshold. The source reports the exact period direct-payee denominator and the selected anomaly count,
while a 500-candidate safety cap is explicit as truncated. A top-IB aggregate remains aggregate-only
and never emits all historic downline accounts.

The overview renderer resolves each account's ancestry with a bounded evidence-graph search rather
than blindly following the first score-ledger entry. This prevents reciprocal same-CRM evidence from
forming a parent cycle and hiding the selected account's route. It then groups identical relationship branches into one representative path edge,
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
The focus workspace activates that band on primary pointer-down and keeps a wider transparent stroke
as its hit target. Background snapshot polling skips DOM reconstruction when the entity/relationship
signature has not changed, while pan and wheel redraws are coalesced through one animation frame.
Collapsed community edges are anchored only to the visible subject and visible aggregate node; an
account hidden inside another collapsed community cannot remain as an orphan edge endpoint.
The collapsed projection uses deterministic multi-ring radial slots for community anchors. It does
not position aggregate circles from hidden member coordinates, so the investigation spokes terminate
at visible group anchors; member-level routing is introduced only after that group is expanded.
After expansion, the community band is removed from the band hit-test projection; clicking a member
node is handled first and opens that account's complete route to the subject. The remaining band stays
the direct collapse target.
Evidence edges include a direction marker in the detail canvas, while repeated interaction instructions
remain available in the evidence panel instead of being drawn beside every ring.

Canvas relation communities retain their canonical collapsed controls, but Galaxy additionally builds
relation-family components from every returned evidence edge. Therefore same-CRM, same-IP, EA, rebate,
copy-order and IB components can intersect at one account; that account keeps its individual position
instead of being hidden in one canonical anchor. Intersection membership is rendered as compact,
parallel coloured arc segments on the existing star-track orbit, never as a new circle around a
component centroid; each segment retains its family label and member count. The detail control or
community band still expands only its canonical group.
Every rendered line is registered as a hit target. Clicking a line selects and highlights it (and
opens copy-order evidence when applicable), while clicking a node keeps node selection behavior.
Collapsed communities are rendered as their own canvas anchors instead of borrowing a representative
account node: members share the community anchor, the common edge terminates on that anchor, and the
anchor displays the member count. Clicking the anchor expands the members; clicking the expanded
community band or its detail control collapses them again.
If a multi-member community has no drawable member route after aggregation, the renderer adds one
presentation-only bridge from its actual parent community (or the subject) to that anchor, so every
non-scattered community remains visibly connected to the investigation chain without inventing
evidence or expanding singleton clues.
Close-angle edges use deterministic alternating curved lanes from each source. Their labels follow
the curve midpoint, and hit testing samples the same quadratic path, so visual separation does not
make the lines unclickable.
Lane allocation is shared across all relation types emitted by one source account; a source cannot
restart at lane zero merely because the next edge has a different relation label.
The first lane also receives a deterministic left/right bend, so an isolated edge cannot remain a
straight line that visually merges with a nearby edge from another source.

## Loading, empty and failure behavior

The focus and galaxy pages show Kuzu loading status, poll the background snapshot and report processed/pending
accounts. Low-score nodes remain inspectable but do not expand. Missing static trial data does not
trigger a remote scan. Invalid graph shape and Kuzu failures do not expose internal paths or exceptions.

## Code and dependencies

`relationship_propagation.py` is pure scoring, `relationship_graph.py` creates the presentation-only
relation-entity graph, `relationship_risk.py` composes source facts,
`relationship_expansion.py` bounds the single-flight background job, and
`KuzuRiskGraphRepository` owns temporary/static Kuzu reads. Canvas uses DOM `textContent` for data
and never injects evidence as HTML. `kuzu_focus_workspace_page.py` is the default renderer;
`kuzu_risk_page.py` remains the explicit galaxy compatibility renderer.
`AccountRelationshipNetworkService` obtains the routed CRM hierarchy payload through the existing
read-only legacy boundary. Same-CRM edges use its mapping-only legacy payload instead of a full
trade-history dashboard read. Relationship-only EA and Copy reads bypass the dashboard result cache,
and its aggregate query runs only for the seed account in one request.
For a current-LastIP/CID cohort, only the repeated cohort follow-up is deduplicated. EA/Copy discovery
still runs for every score-eligible account because sharing an IP/CID does not establish identical
expert or copy-trading behavior; the response never represents those automation sources as reused.

The expansion coordinator retains at most three distinct running, queued or completed investigation
snapshots. Completed snapshots expire after 90 seconds and the least recently accessed completed
snapshot is evicted before admitting a new account. Poll reads make only a shallow response envelope
copy; the immutable graph arrays are not duplicated on every request. Progress presentation graphs are
materialized at most once every two seconds. `/health/ready.relationshipExpansion` exposes resident,
running, queued and completed counts so resource pressure is observable without opening the UI.

In production, each admitted investigation runs inside one disposable spawned process. Remote-source
threads, legacy payloads, parsing caches and native allocations therefore belong to that child and are
released by Windows when the investigation completes. The 8777 process receives only normalized progress
and final graph snapshots. There is no investigation-wide child-process deadline: slow but valid reads may
finish without blocking 8777. Each individual evidence source retains its finite hard ceiling, and account,
node and relationship budgets still bound the investigation. Test and development profiles retain the
injectable in-process builder for deterministic source tests.

## Tests and acceptance

Unit tests cover recursive source expansion through its score threshold, one final Kuzu materialization,
single-flight pollable progress, redundant same-IP cohort lookup avoidance, bounded same-IP timeout,
resident-job admission control, non-deep-copy polling, throttled progress materialization,
production process isolation, progress forwarding and optional finite-timeout termination tests,
Kuzu projection caps, threshold stopping, noisy-OR, de-duplication,
cycles, same-IP and Toxic evidence ledger construction, and risk colour. Repository tests cover
request-scoped Kuzu materialization/readback.
API tests cover account-route replacement, page request targeting and invalid thresholds. Source tests use
mocks; they make no live writes.

## Compatibility and deprecation

When a galaxy community is collapsed, its visible anchor is connected through the complete
score-ledger route from the subject to the owning intermediate community. If a source route is
missing, the renderer uses an explicitly presentation-only connector and does not treat it as
new evidence or a score contribution.

Galaxy route lookup is now built once per response data snapshot and reused by the renderer;
the selected account's complete subject route is redrawn after aggregation so collapsed groups
cannot hide an otherwise valid path. This is a presentation/performance change only and does not
alter the read-only API or source database contract.

Galaxy group rings use a two-state interaction. Clicking a collapsed ring/anchor expands that one
community. Once expanded, a small minus marker is drawn beside the ring; clicking that marker merges
the community again. Account and evidence-edge clicks retain their selection behavior, while blank-
canvas clicks leave the current selection unchanged. The temporary DOM group-operation list is not
shown in the workspace. A small “恢复初始” control is the only action that clears the selection,
collapsed/expanded state, and route highlight.

The former relationship button view/response is replaced at the user's request. The standalone
Kuzu demo, account route, Copy, EA and Toxic contracts remain available.
