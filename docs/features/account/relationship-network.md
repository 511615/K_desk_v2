---
feature_id: ACC-REL-001
title: Account relationship network
module: account
status: active
apis: ["GET /api/accounts/by-login/{login}/relationship-network", "GET /api/accounts/by-login/{login}/relationship-network/node-profile", "GET /api/accounts/by-login/{login}/relationship-network/relation-detail", "GET /api/accounts/by-login/{login}/relationship-network/relation-display"]
code: ["src/kdesk/application/relationship_network.py", "src/kdesk/application/relationship_expansion.py", "src/kdesk/application/relationship_inspection.py", "src/kdesk/application/relationship_risk.py", "src/kdesk/application/trade_relationship_detection.py", "src/kdesk/domain/ib_rebate_anomaly.py", "src/kdesk/domain/relationship_graph.py", "src/kdesk/api/account_app.py", "src/kdesk/api/fixed_sector_page.py", "src/kdesk/api/kuzu_3d_preview_page.py", "src/kdesk/api/kuzu_focus_workspace_page.py", "src/kdesk/api/kuzu_graph_type_page.py", "src/kdesk/api/kuzu_risk_page.py", "src/kdesk/api/relation_display_page.py", "src/kdesk/infrastructure/kuzu_risk_graph.py", "legacy/apps/problem_account_registry/app.py", "scripts/verify_change.ps1", "scripts/verify_deployed_release.ps1"]
tests: ["tests/test_api.py", "tests/test_ib_rebate_anomaly.py", "tests/test_kuzu_risk_graph.py", "tests/test_relationship_graph.py", "tests/test_relationship_inspection.py", "tests/test_relationship_risk.py", "tests/test_trade_relationship_detection.py", "legacy/apps/problem_account_registry/test_app.py"]
depends_on: ["ACC-DETAIL-001", "ACC-SEARCH-001", "AUT-COPY-001", "AUT-EA-001", "AUT-FOLLOWER-001", "FIN-REBATE-001", "ACC-REL-003", "TOX-PUSH-001", "TOX-HEDGE-001"]
last_verified_version: 2.1.4
last_verified_date: 2026-08-25
---

# Account relationship network

## Node profile and auditable relation evidence

The Galaxy investigation view lazily reads an account profile only after an operator selects an
account. The profile preserves an existing `B/M/P/T/A/TA` database status and falls back to `B` only
when the status is blank. It reports the selected account route, propagation depth and score, query
coverage, versioned behavior and automation tags, and at most eight explainable related accounts.
Every recommendation is drawn from the current investigation snapshot and must have a complete path
back to the investigation subject. Selecting a node never recomputes the graph layout. Profile reads
are cached for ten minutes and superseded browser requests are cancelled and sequence-guarded. The
profile cache separates an in-progress snapshot from a completed or truncated snapshot, so the
selected profile is re-read when background expansion reaches its terminal state and cannot retain a
stale `pending` status after the graph header reports completion.
The profile is the first card in the Galaxy detail panel: account identity, propagated score, layer,
database status and expansion progress are visually separated before the tags and linked-account detail.
An eligible score no longer reads as 继续扩散 after its evidence has already been queried. Completed
nodes report 已完成扩散 · 无新增账户 only when the snapshot proves that outcome.

The Galaxy page keeps its title bar to navigation and product identity only; it does not show a
duplicated workflow hint or a rule-status sentence. Its filters form a compact, responsive control
strip and the desktop workspace scales its three panels down without horizontal scrolling. The right
panel places the selected account profile before the route caption and relation controls. The profile
shows only the operator decisions—identity, routed database status, propagated score, layer and
expansion outcome. Raw coverage dates, query-completeness prose and technical limitations remain in
the auditable relation-evidence view and are not repeated as an account-profile card.

When a user clicks `ib_direct_rebate` evidence, Galaxy opens the shared **IB 直属返佣核查** relation
display rather than an automatic card below the selected profile. It groups only the already
materialised accounts by the returned direct-IB entity and displays the returned abnormal/total count,
inclusion reason, database status, actual trade P/L, rebate, combined profit, rebate share, rebate
deal count and most recent rebate record. Values are structured edge facts; the table does not infer
that an IB or account is fraudulent. Selecting a row only selects/highlights that account and never
toggles a relation star-track or recomputes expansion.

## Relation display table

Clicking a visible raw relationship edge opens the shared `关系展示表`; selecting a node continues to
open only its account profile. A completed snapshot keeps the table revision-bound. While background
expansion is active, the client reads the newest snapshot so an ordinary edge click is not rejected
only because the worker published a newer revision. On a stale response, the workspace refreshes and
retries the exact edge once, then makes one latest-snapshot attempt. If the clicked edge itself has
been replaced by newer evidence, the panel reports that the graph was synchronised and asks the
operator to click the current visible line; it never exposes a raw 404/409 message or mixes evidence
across revisions. It never starts relationship expansion, changes score, changes a same-CRM orbit, or
repositions a node. Both the default focus workspace and explicit Galaxy workspace consume the same
read-only table contract.

Release preflight keeps its browser check to the legacy page running on the currently deployed
process. The real Galaxy edge-click regression runs after the candidate service has restarted and its
metadata, readiness and source-root checks have passed; this prevents an old process from being used
to judge newly introduced client behaviour. That regression accepts the graph-synchronised notice
only when a live worker replaced the selected evidence; any technical relation-display error remains
a release failure. Its automated edge selection is restricted to a current raw source edge (an IB
edge when directly drawable, otherwise the expanded same-CRM source edge), never a synthetic
aggregate presentation edge.
Both 409 and first-attempt 404 relation-display responses refresh the graph and retry that same raw
edge once; the graph-synchronised notice is reserved for an edge that is still absent after refresh.
The deployment verifier resolves Node from the bundled `pnpm` fallback runtime when a standalone
PowerShell release session does not already expose `node` on `PATH`, so this browser acceptance test
cannot be skipped by an environment-only failure.

An account-to-account edge defaults to **single mode**. It shows only that account's facts for the
clicked relation and its original evidence; it must not report a member count, total P/L or averaged
group value. An account-to-relation-entity edge (IB identity, EA feature, Copy group or CRM community)
can open **group mode**; ordinary LastIP, CID, same-name and copy edges retain direct lines but expose
an explicit `查看…账户群` table action when the materialised snapshot contains more than one member.
Group members are de-duplicated by account/platform/server and come only from the current snapshot.

Every group table separates `known_members`, `included_members` and `statistic_members`; partial
evidence remains partial rather than being extrapolated. Direct-IB rebate additionally reports the
original cohort denominator alongside only the materialised anomaly accounts, so an `异常 8 / 共 27`
card states clearly when money totals are based on 8 complete evidence accounts. IB, EA and Copy use
their identified relation orders/rows. Common IP/CID/same-name tables may make a capped,
operator-triggered, read-only account-summary request for already materialised members; those metrics
are labelled as member-trade aggregation and never imply causation.

Every visible evidence edge resolves to a stable normalized relation key and can be inspected without
rerunning expansion. Exact duplicate evidence is removed. Multiple evidence families between the same
accounts are returned as one relation bundle whose sections remain separately auditable. Only shared
CRM identity is a collapsible account community; LastIP, CID, EA, Copy, rebate, IB and trade facts are
always ordinary account-to-account or account-to-entity lines.
Galaxy has no fixed business-sector renderer: that retired presentation is not loaded or reachable
from the page, so it cannot replace ordinary relationship lines with synthetic sector routes.
The business presentation calls a shared CRM identity `同名账户` and removes SQL, table names, internal
CRM keys and unnecessary personal identifiers from both the profile and relation-detail contracts.

Same-CRM aggregation is deliberately relation-family scoped: connected components are formed only
from `same_crm_user` account-to-account evidence, and reverse copies of the same pair are one
presentation fact. LastIP, IB, EA, Copy or other evidence may overlap those accounts but cannot
enlarge or split their same-CRM component. In Galaxy, a component spanning logical discovery layers
uses the nearest non-subject member's existing star-track ring as its shared visual band. It starts
collapsed: the band label shows the complete component count while no member account or member edge
is drawn. Clicking the band boundary expands those members in the same band; every expanded account
shows its numeric login above the point. The renderer restores the original `same_crm_user` evidence
lines only when both endpoints are visible members of that same expanded band. Each such line keeps
its source relation ID, so clicking it opens the shared read-only relation display. It never redraws
every raw account/IB edge incident to a member: cross-community relations retain their normal
star-track projection even while the band is expanded, preventing long cross-graph arrows and
overlapping labels. LastIP, IB, EA, Copy and every other relation stay ordinary lines: they cannot
become or enlarge an orbit community. Clicking the boundary again collapses the band. This is a
layout-only projection and does not change evidence, propagation, score or expansion eligibility.
Ordinary relationship lines use their direct endpoint path. Only a restored internal same-CRM member
line may use a short local offset to distinguish parallel evidence; it is capped to the member span
and cannot form a cross-graph arc.

`跟单关系`, `开平仓同步` and `疑似对锁` remain distinct facts. Copy evidence requires an identified
source/follower direction. Open/close synchronization is an undirected timing and behavior clue and is
explicitly not proof of copy trading. Suspected hedge evidence requires opposite direction and retains
its limitations; it is not a violation conclusion. Profile rules are versioned as `account-profile-v1`,
use one centralized threshold table and return `数据不足` instead of forcing a behavior label when the
minimum sample is absent.

## Purpose and user entry

The `关系网络` button on the legacy account-detail page opens
`/kuzu-risk?account={login}` while retaining the current platform, server and symbol filters.
The button remains visible for a confirmed account route even when it has no completed order, so
non-trade evidence such as CRM identity or current-IP evidence can still be investigated.
The default renderer is the current center-constrained relationship workspace. The original galaxy
renderer remains available only through explicit `graph_type=galaxy`; missing or stale graph-type
values cannot silently return the legacy view.

## UI and behavior

The default workspace has a global locator, a center-constrained detailed graph and an evidence
panel. It receives a presentation-only relationship-entity projection: repeated account pairs are
represented by a shared relation entity and member edges, while the scored account graph remains the
source of truth. It polls the existing single-flight background expansion and renders each available
snapshot without starting duplicate work. Account nodes read `databaseStatus`; only a blank value
falls back to `B`.

An additive `graph_type=focus-3d` preview uses the same `presentationGraph` response and does not
change discovery or scoring. It projects hop depth into a rotatable Canvas scene, fixes the subject at
the sphere origin, and distributes each hop deterministically on spherical shells. A left-side 2D
top-down (X/Z) locator remains stable while the 3D camera rotates; both views share selection and
route highlighting. The 2D workspace and legacy galaxy renderer remain available for evidence review
and compatibility.

The detailed workspace collapses only same-CRM relationship communities. A collapsed community draws
one aggregate node and one aggregate edge; its displayed status is the highest-priority member status
in `TA > A > T > P > M > B` order. The dashed community boundary is the primary interaction target:
clicking the boundary expands that community into its member accounts, visible account numbers and
individual raw evidence edges, and clicking it again collapses only that community. A transparent widened stroke makes the boundary
hit target usable without changing the visible ring width. The evidence panel repeats the same
expand/collapse control and states the member count, highest status and highest propagated score.
Initial view fitting includes every returned ring, manual wheel zoom can reach 5%, and later polling
does not reset a user-adjusted zoom or pan position.

The explicit legacy galaxy page has a linked overview and detail view. The overview renders every returned account and
concrete IB-identity node exactly once in concentric rings by its logical account-to-account discovery
depth. Nodes in each ring are distributed across the whole circle in deterministic order; they are not
stacked into relationship-family sectors, so a high-cardinality relation cannot hide siblings behind one
dot. Siblings that share both their evidence owner and evidence family are placed as a compact visual
cluster with an enclosing arc-band; separate clusters have an angular gap. Selecting any member
first resolves the selected evidence-family cluster bidirectionally for symmetric facts (same CRM,
LastIP, EA, Copy, rebate, same-name and Toxic), then highlights every discovered outward child of that whole
cluster. The detail panel remains focused on the selected account. Hierarchy and direct-IB-rebate
relations retain their source-to-target direction. Every highlighted segment is drawn in the fixed
relation colour and carries a compact relation label; a directional segment names both endpoints in
`来源账号 → 目标账号（关系）` form and carries an arrowhead. In particular, a line named
`直属上级 IB 本人账户` means the target is the source account's direct-superior IB's own trading
account; it does not mean the target is a downline client.
The galaxy workspace's left global locator is an equal-scale projection of the detailed graph's
completed star-track layout. It keeps every returned trading account visible even when a relationship
community is collapsed in the detailed graph, but never performs a separate circular layout: each
account's locator position is derived from the same detailed-layout coordinate relative to the
subject, so corresponding nodes retain the same direction, orbit and relative spacing. Locator fill uses
the routed database status in increasing severity order `B < M < P < T < A < TA`, with progressively
darker colours. Clicking a locator account performs the same selection as clicking that account in
the detailed graph: the selected account, its local evidence and its complete account path back to
the investigation subject are rendered without changing community expansion state.
Galaxy canvas interaction is owned by one capture-phase dispatcher. It reads an immutable hit map
built after the last completed render and never invokes layout while classifying a click. Hit priority
is the current visible account/IB node, relation-track boundary, relation edge, then blank canvas.
The dispatcher consumes every canvas click before legacy compatibility listeners can act, so one
gesture performs at most one expand, collapse, select or edge-inspection action. During incremental
polling, returned account nodes may remain visible for orientation, but relationship lines are
replaced from the newest snapshot rather than accumulated; an obsolete edge cannot remain as a false
click target. Galaxy uses text progress only: the focus-view scan fan is not overlaid on the star map
because its large wedge can be mistaken for a relationship line. A collapsed relation
track has no synthetic anchor or member hit target. Clicking its boundary expands it; clicking the
expanded boundary collapses it again. When a visible node has been moved by its component's
star-track aggregation, the dispatcher first checks the current rendered coordinates and complete
painted-node radius. This selects the visible account without recalculating layout or falling through
to a relation-band action. Expanded tracks use their own empty arc boundary as the collapse target;
they do not draw or register a separate collapse marker. Intersecting relation families remain
overlapping segments on the same star-track radius rather than becoming circles or duplicate account
nodes.
The overview intentionally renders only the selected account's local evidence cluster and its
deduplicated parent chain back to the problem account. Intermediate CRM/evidence entities remain
hidden, but their relationship type is retained on the visible account-to-account segment. Siblings
that merely share the problem account as an ancestor are neither joined nor highlighted as each
other's relation. If a malformed response cannot resolve a selected visible entity's parent chain to
the problem account, that entity is withheld from the Canvas rather than being presented as an
unexplained candidate.
The overview
states the discovered-node and account totals, increases its desktop canvas height for deeper graphs,
fits the initial view to the available board and re-fits after resize; it shows only the selected account's
path instead of a full edge web. Selecting an overview account updates the detailed
account-to-evidence-to-peer view below.
Node fill is a strict propagated-score gradient: the problem account is red, then high-score red,
orange, gold and yellow-green low-score nodes; a node stopped by the threshold is green regardless of
score. A completed account with no discovered account child receives a compact dark-green 叶 badge
only when its additive expansionState=expanded and expansionEvidenceAvailable=true confirm that
it was actually queried with available evidence. A score-eligible, pending or unvisited account never
receives that badge merely because the current rendered graph has no child.
Shape encodes entity state independently of score: a circle is a trading account, a hexagon is a concrete
IB identity and a diamond is a threshold-stopped account. Arc-band color encodes evidence family,
not score: CRM blue, LastIP purple, EA cyan, Copy pink, rebate gold, IB indigo, same-name teal and
Toxic rose. The page displays this mapping and prints a short relationship label in each sufficiently
wide arc-band. Selection never replaces that relation colour: it adds only a white dashed outline,
so selecting a cluster cannot make unrelated evidence families appear to share the same colour.
Each trading-account circle also has a small database-status badge. It reads the risk-system database
`Status` returned by the account's actual MT4/MT5 database route, using `B` only when that status is
blank or unavailable; `A/TA` is rendered as `TA`. It never reads the local ledger's `action` or
local mark. `P` is blue,
`T` amber, `TA` rose and `A` red; `T`/`TA`/`A` have an additional high-visibility ring. This badge
is a local workflow mark, not a propagated score or a new risk conclusion.
Account and IB nodes use a 2× larger base radius than the first rollout so the in-node database
status and selected-node label remain legible at normal zoom. The 叶 badge intentionally uses 62% of
the unscaled node badge size, so its outcome marker remains visible without visually dominating the
account. The node hit target grows with the rendered node size, so selecting a larger node does not
require clicking its former centre.
The overview has a left-side extensible `风险表`. Its first risk item is deliberately narrow: it lists
only rendered trading accounts whose routed database status is `T`, `TA` or `A`, ordered by propagated
score then account number. Each row shows account, database status, relationship layer and score;
selecting it selects and highlights the same graph node and existing graph path. No relationship,
score or expansion inference is added by this table. Empty graphs and graphs without those statuses
state this explicitly. Future risk items may add rows to this table without changing this status rule.
Relationship labels must describe the evidence that produced an edge. `跟单订单匹配（开仓/平仓）`
means the relationship came from matched copy-trading open and/or close orders; it is not a generic
"order synchronization" claim. `跟单来源组匹配` means the accounts share an identified copy source
group, but does not by itself prove every order was copied. Cross-account trade edges are explicitly
labeled as `主订单同向开平仓同步` or `疑似对锁（反向同步开平仓）`. The former uses principal orders,
same symbol/direction, two-second open/close windows and a recurrence floor; the latter uses opposite
directions, five-second open/close windows and at least 80% lot similarity. One peer/detection type
produces one edge even when many order pairs match; the pair rows remain auditable edge evidence.
Every visible `跟单订单匹配（开仓/平仓）` line is an on-demand evidence control. Clicking the
line opens a modal without restarting or blocking graph expansion. The first tab reads the existing
read-only Copy-origin payload for the follower endpoint and shows only that line's follower-to-master
matched orders: master order, follower order, symbol, open/close time, volume and P/L. The second tab
uses the same identified master and payload to show its complete discovered follower-account summary.
The label, detail card, slow-query control and loading state all use this same explicit vocabulary;
the page does not retain the ambiguous `同步订单` wording or override labels after the initial render.
Both tabs retain the page platform/server/symbol/time filters, state when the current scope has no
row-level evidence and never write to an account, trade, database or MT service.
Wheel zoom supports 10% through 250%; pointer-centred
zoom and a double-click refit make every returned ring reachable on a small display.
The caption explicitly states whether the selected account is the problem-account start or which
relationship layer separates it from that account, then narrates the evidence-family route in business
terms. When an account has a direct relationship with the problem account, the displayed path uses that
direct evidence rather than an incidental longer ledger route. Each detail relationship card names the
actual account logic rather than generic `附加线索`; for example, the direct-IB group contains only
accounts connected directly to the selected account by the `ib_direct_account` evidence. It never
places another client there merely because both clients share that IB. Peer cards likewise state their
layer relative to the problem account rather than showing an unexplained hop count.
The subject is bright red; other expandable accounts use a score-and-depth red-to-light-orange
gradient. A node retained as a clue but stopped by the propagation threshold is green. Operators can
use the mouse wheel to zoom around the pointer and drag the overview to pan. Scores are investigation
priorities only; they are not a fraud conclusion or an automated action.
For CRM hierarchy, a verified direct-parent IB user's own trading account is a real account peer and
is visible/expandable. A top-IB downline is rendered as one aggregate group with account/customer
counts; its members are not automatically emitted as account nodes or expanded from that group.
The direct-IB branch also uses a bounded anomaly projection rather than expanding the full downline.
It materialises only accounts whose database status is `P`, `T`, `A` or `TA`, or whose selected-period
combined profit is positive and rebate-dominated. Each IB entity reports `异常 n / 直属返佣账户总数`,
and every materialised member retains its inclusion reason, trade P/L, rebate, combined profit,
rebate share and period. The graph path remains account → CRM owner → direct IB → anomaly account;
it never creates a false one-hop edge from the investigated account to the IB's other members.

## API contract

`GET /api/accounts/by-login/{login}/relationship-network` accepts existing account filters and
`threshold=1..100` and optional `include_toxic=true`. It returns scored `entities`,
`relationships`, `relationTypes`, `summary`, source `coverage` and limitations. While the same
request key is still expanding, `inProgress=true` and `progress` report processed/pending account
counts; the page polls that snapshot rather than holding a web request open. Each entity includes
score, colour, hop count, expansion state and score ledger. Account entities additively include
`databaseStatus`, read in the same bounded database-status batch as the CRM-account mapping for the
account's actual route; cached expansion data is not mutated. The former evidence-only response is
replaced by this contract. `presentationGraph` is additive and contains relation entities, grouped
member edges, auditable subject paths and the unchanged account status fields.
`GET /api/accounts/by-login/{login}/relationship-network/relation-display` is additive to
`relation-detail`: it accepts the same filters plus a raw `edge_id`, `scope=auto|single|group` and
bounded member pagination. It returns a stable display key, relation/anchor metadata, coverage,
mode-specific metrics, paged member rows, group actions and safe evidence. `relation-detail` remains
the source for a user explicitly requesting original per-edge evidence.

## Data, routing and read-only constraints

The service first reads the selected account's bounded CRM, EA, Copy and rebate evidence, then reads
each account whose propagated score still meets the threshold. For MT5 it also reads
same-server peers sharing the current `LastIP` or current MT5 `ClientID` (CID). CID zero/null is ignored,
and current MT4 exports do not synthesize CID. When the Kuzu page asks for it, high-priority nodes
are additionally checked through the bounded all-platform MT4/MT5 principal-order open/close and
suspected opposite-lock matcher.
Same-name account discovery uses a mapping-only legacy payload plus a bounded `Login/Status` lookup
on that same route; it never uses the full dashboard trade-history payload for a graph node.
The UI calls this evidence `同名账户` and hides the internal CRM table name and `user_id`.
EA and Copy evidence retain their normal relationship facts but are marked internally as
relationship-only reads, bypassing the legacy dashboard result cache so completed nodes do not
accumulate large payloads in 8777.
When a node belongs to an already-read current-LastIP or current-CID cohort, the repeated LastIP/CID
follow-up itself is skipped. This cohort optimisation never suppresses per-account EA or Copy evidence:
accounts sharing one current IP/CID can still have different expert or copy-trading behavior, so every
score-eligible account runs those account-specific sources. Coverage records only the skipped cohort
follow-up, not a falsely implied completed automation query.
It then writes only a request-scoped temporary Kuzu `Entity`/`Evidence` projection, reads it back
through Kuzu and removes it before returning. It never writes AC, DBG, MT4, MT5, CRM or K_desk SQLite.
The CRM hierarchy read resolves account-to-CRM-user, direct parent IB and accounts owned by that
direct IB user through the exact CRM schema/server route. It performs the potentially broad top-IB
aggregate only for the seed account; later score-eligible account reads retain direct-parent mapping
but omit repeated group aggregation.
For both an investigated account that is itself an IB and its direct parent IB, a two-stage read first
aggregates indexed rebate rows and elevated database statuses, then reads trading P/L only for the
bounded candidate set. Blank graph dates use the latest 90 days. Cent/USC rebate and trading P/L are
both converted to the same display-currency scale before the dominance rule is evaluated.

## Business rules and units

The Kuzu scorer uses the ACC-REL-003 strength table and evidence-family de-duplication. Returned
money labels retain source currency and existing USD/USC normalization. A single local background
expansion continues through score-eligible accounts rather than ending at a request-wide timer;
equivalent requests reuse its current snapshot. Each parallel source has a 120-second hard ceiling and the
follow-up MT5 same-server `LastIP` read has its own three-second budget. Accounts already identified
in the same current-LastIP cohort skip that redundant lookup. Each legacy evidence family has one
shared local execution lane, so a late source is returned as explicit partial coverage rather than
creating an unbounded number of timed-out worker threads. The 2,000-node/10,000-score-expansion safety
caps remain in force. There is no request-wide discovery timer: eligible accounts keep expanding
until the score threshold or a safety cap stops the path. Production runs each investigation in a
disposable child process without an investigation-wide lifetime deadline; the child isolates slow work
from 8777 and is reclaimed when the investigation completes or fails. Before request-scoped Kuzu
materialization, the visible projection is
bounded to 400 entities and 1,200 relationships, prioritizing the subject and highest propagated
scores; exceeding either cap sets `truncated=true`. Native Kuzu materialization runs in a one-at-a-time
child process with a four-second hard deadline, so a native allocation or stall cannot retain memory in
the 8777 account-service process. If that child is busy, fails or times out, the response preserves the
capped pure propagation result and records `kuzuProjection` coverage failure.
`discoveryTruncated` and `queryBudgetExhausted` report incomplete discovery. Every account evidence
source has its own 120-second hard ceiling; a late source returns explicit partial coverage without
preventing later eligible accounts from expanding. Toxic checks are
restricted to nodes scored at least 30 and two cross-platform checks per request. A current `LastIP`
is a shared-login clue, not proof of shared device ownership or historical IP use.
CRM ownership and hierarchy bridge edges are explanatory and deliberately weak. The verified direct
IB-owned trading-account shortcut is separately scored and may expand; membership of a top-IB aggregate
alone never creates a downstream account candidate.

## Loading, empty and failure behavior

The destination page shows a Kuzu loading state, renders the first verified snapshot when available,
then polls while background expansion continues. It labels processed and pending account counts, so
an incomplete view is not mistaken for threshold stopping. Independent source failure or timeout
does not hide available facts and remains in source coverage. A Kuzu failure returns a sanitized
unavailable response.
The focus workspace compares a stable entity/relationship signature on each poll and only rebuilds
the SVG when the graph snapshot changes. Group expansion therefore is not overwritten by identical
half-second polling responses. Group boundaries and aggregate nodes react on primary pointer-down;
pan and zoom redraws are animation-frame coalesced. Collapsed representative edges run only between
the visible investigation subject and the visible aggregate node, preventing line fragments whose
original account endpoint is hidden by another collapsed community.
Collapsed communities are assigned deterministic multi-ring radial slots rather than member-derived
coordinates. This keeps each aggregate endpoint visible and separates center-to-community spokes;
only an explicit expansion reintroduces member coordinates and member-level edges.
Evidence paths show a small arrowhead so the rendered source and target are unambiguous; repeated
expand/merge instructions remain in the side panel rather than being duplicated around every ring.

## Code and dependencies

`AccountRelationshipNetworkService` retains evidence composition.
`AccountRelationshipExpansionCoordinator` serializes one active request key and stores its pollable
snapshot. `AccountRelationshipRiskService` passes completed evidence to the request-scoped
`KuzuRiskGraphRepository`, while the pure domain scorer owns propagation. The legacy page only
navigates to the Kuzu page.

## Tests and acceptance

API and application tests pin recursive expansion, threshold stopping, same-IP and Toxic evidence
ledgers, score/colour output, typed evidence and partial coverage. Repository tests prove temporary
Kuzu materialization/readback. Legacy HTML tests pin button placement and navigation preserving filters.

## Compatibility and deprecation

The button remains at its existing location, but its view and endpoint contract are intentionally
replaced. Copy, EA and Toxic interactions are unchanged.
