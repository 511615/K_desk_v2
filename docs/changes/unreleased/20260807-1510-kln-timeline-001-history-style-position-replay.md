---
change_id: 20260807-1510-kln-timeline-history-style-position-replay
features: ["KLN-TIMELINE-001"]
change_type: modification
status: unreleased
compatibility: compatible
---

# Present K-line funds replay as historical funds with Position-level orders

## Before and after

The K-line artifact showed a compact funds table and listed each order opening and closing as
separate rows. It now renders the same source note, eight factual summary cards, Balance/Credit
curve, liquidation chips and detailed table hierarchy as the historical-funds backtrace. Funds
remain individual ledger rows; all market source entries for one Position are folded into one
lifecycle row with open/close evidence, constituent Deal IDs and summed factual values.

## Impact

`KLN-TIMELINE-001` standalone K-line HTML and its versioned timeline input. Existing endpoints,
request fields, chart URLs, remote reads, cache keys and historical-funds API responses are unchanged.
The raw Balance/Credit curve continues to retain every event. MT4/MT5 and remote databases remain
read-only.

## Documentation updated

- `docs/features/kline/funds-and-position-replay.md`
- `docs/TEST_STRATEGY.md`

## Verification

- Domain tests prove Position folding, carry-in and unknown-state behavior.
- K-line HTML tests prove the historical-funds labels, Position/Deal table and JavaScript parsing.
- An offline cache-backed artifact for account `6003593` contains 3,381 source events, 1,687 Position
  rows and one factual liquidation marker without a source refresh.

## Deployment and rollback

The change is released through the normal production script. Rollback restores the prior standalone
timeline rendering; no schema, account, trade, cache-source or MT state is changed.
