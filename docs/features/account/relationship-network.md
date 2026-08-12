---
feature_id: ACC-REL-001
title: Account relationship network
module: account
status: active
apis: ["GET /api/accounts/by-login/{login}/relationship-network"]
code: ["src/kdesk/application/relationship_network.py", "src/kdesk/application/relationship_expansion.py", "src/kdesk/application/relationship_risk.py", "src/kdesk/api/account_app.py", "src/kdesk/api/kuzu_risk_page.py", "src/kdesk/infrastructure/database.py", "legacy/apps/problem_account_registry/app.py"]
tests: ["tests/test_api.py", "tests/test_kuzu_risk_graph.py", "legacy/apps/problem_account_registry/test_app.py"]
depends_on: ["ACC-DETAIL-001", "ACC-SEARCH-001", "AUT-COPY-001", "AUT-EA-001", "AUT-FOLLOWER-001", "FIN-REBATE-001", "ACC-REL-003"]
last_verified_version: 2.1.0
last_verified_date: 2026-08-10
---

# Account relationship network

## Purpose and user entry

The `关系网络` button on the legacy account-detail page now opens
`/kuzu-risk?account={login}` while retaining the current platform, server and symbol filters. The
previous in-dialog fact graph is no longer the visible account relationship interface.

## UI and behavior

The Kuzu page has a linked overview and detail view. The overview renders every returned account and
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
The overview
states the discovered-node and account totals, increases its desktop canvas height for deeper graphs,
fits the initial view to the available board and re-fits after resize; it shows only the selected account's
path instead of a full edge web. Selecting an overview account updates the detailed
account-to-evidence-to-peer view below.
Node fill is a strict propagated-score gradient: the problem account is red, then high-score red,
orange, gold and yellow-green low-score nodes; a node stopped by the threshold is green regardless of
score. A completed account with no discovered account child retains its score colour but receives a
large dark-green `叶` badge, meaning it was queried and is a terminal investigation leaf rather than
an unexpanded node.
Shape encodes entity state independently of score: a circle is a trading account, a hexagon is a concrete
IB identity and a diamond is a threshold-stopped account. Arc-band color encodes evidence family,
not score: CRM blue, LastIP purple, EA cyan, Copy pink, rebate gold, IB indigo, same-name teal and
Toxic rose. The page displays this mapping and prints a short relationship label in each sufficiently
wide arc-band. Selection never replaces that relation colour: it adds only a white dashed outline,
so selecting a cluster cannot make unrelated evidence families appear to share the same colour.
Each trading-account circle also has a small local-mark badge. It reads the local ledger's `action`
value, using `B` only when the value is blank or `待定`; `A/TA` is rendered as `TA`. `P` is blue,
`T` amber, `TA` rose and `A` red; `T`/`TA`/`A` have an additional high-visibility ring. This badge
is a local workflow mark, not a propagated score or a new risk conclusion.
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

## API contract

`GET /api/accounts/by-login/{login}/relationship-network` accepts existing account filters and
`threshold=1..100` and optional `include_toxic=true`. It returns scored `entities`,
`relationships`, `relationTypes`, `summary`, source `coverage` and limitations. While the same
request key is still expanding, `inProgress=true` and `progress` report processed/pending account
counts; the page polls that snapshot rather than holding a web request open. Each entity includes
score, colour, hop count, expansion state and score ledger. Account entities additively include
`localAction`, populated from the newest matching local K_desk ledger row through a bounded indexed
lookup; cached expansion data is not mutated. The former evidence-only response is replaced by this
contract.

## Data, routing and read-only constraints

The service first reads the selected account's bounded CRM, EA, Copy and rebate evidence, then reads
each account whose propagated score still meets the threshold. For MT5 it also reads
same-server peers sharing the current `LastIP`. When the Kuzu page asks for it, high-priority nodes
are additionally checked through the existing all-platform Toxic synchronised open/close matcher.
Same-CRM account discovery uses a mapping-only legacy payload and never uses the full dashboard
trade-history payload for a graph node.
EA and Copy evidence retain their normal relationship facts but are marked internally as
relationship-only reads, bypassing the legacy dashboard result cache so completed nodes do not
accumulate large payloads in 8777.
When a node belongs to an already-read current-LastIP cohort, the cohort representative's EA/Copy
evidence is reused: sibling nodes continue CRM and LastIP expansion but skip duplicate heavy EA/Copy
reads. Source coverage records the skipped reads and reason, so this optimisation is never presented
as an individual automation query.
It then writes only a request-scoped temporary Kuzu `Entity`/`Evidence` projection, reads it back
through Kuzu and removes it before returning. It never writes AC, DBG, MT4, MT5, CRM or K_desk SQLite.
The CRM hierarchy read resolves account-to-CRM-user, direct parent IB and accounts owned by that
direct IB user through the exact CRM schema/server route. It performs the potentially broad top-IB
aggregate only for the seed account; later score-eligible account reads retain direct-parent mapping
but omit repeated group aggregation.

## Business rules and units

The Kuzu scorer uses the ACC-REL-003 strength table and evidence-family de-duplication. Returned
money labels retain source currency and existing USD/USC normalization. A single local background
expansion continues through score-eligible accounts rather than ending at a request-wide timer;
equivalent requests reuse its current snapshot. Each parallel source has a six-second budget and the
follow-up MT5 same-server `LastIP` read has its own three-second budget. Accounts already identified
in the same current-LastIP cohort skip that redundant lookup. Each legacy evidence family has one
shared local execution lane, so a late source is returned as explicit partial coverage rather than
creating an unbounded number of timed-out worker threads. The 2,000-node/10,000-score-expansion safety
caps remain in force. There is no request-wide discovery timer: eligible accounts keep expanding
until the score threshold or a safety cap stops the path. Before request-scoped Kuzu materialization, the visible projection is
bounded to 400 entities and 1,200 relationships, prioritizing the subject and highest propagated
scores; exceeding either cap sets `truncated=true`. Native Kuzu materialization runs in a one-at-a-time
child process with a four-second hard deadline, so a native allocation or stall cannot retain memory in
the 8777 account-service process. If that child is busy, fails or times out, the response preserves the
capped pure propagation result and records `kuzuProjection` coverage failure.
`discoveryTruncated` and `queryBudgetExhausted` report incomplete discovery. Every account evidence
source has its own six-second wait budget; a late source returns explicit partial coverage without
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
