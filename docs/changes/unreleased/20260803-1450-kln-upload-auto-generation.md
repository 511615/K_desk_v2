---
change_id: 20260803-1450-kln-upload-auto-generation
features: ["KLN-DB-001", "JOB-RECOVERY-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# K-line upload now continues from inspection to generation

## Before and after

The K-line task center submitted `kline_inspect` for an uploaded HTML statement and displayed
`done · 100%` when parsing finished. The page did not submit the existing
`POST /api/jobs/{job_id}/generate` endpoint, so no chart artifact was created.

## After

When inspection completes, the page extracts the parsed symbol list and report time range, submits
the generation job, polls that job independently, refreshes recent charts, and shows a direct
`打开生成图表` link on successful completion. Empty parsed symbol lists and generation submission
errors remain visible as explicit errors.

## Impact and compatibility

- Affected page: `GET /` on the K-line service (`8766` production, `8866` development).
- Affected APIs: existing upload, job polling and generation endpoints; no request or response
  fields were removed or renamed.
- Data: uploaded files and generated artifacts remain in the configured runtime directories.
- Remote data: quote access remains read-only and is unchanged.
- Existing clients that submit generation manually remain compatible.

## Documentation updated

`docs/features/kline/database-generation.md` and `docs/features/jobs/job-progress-recovery.md`.

## Verification

- API page regression asserts the inspection-to-generation handoff and chart link.
- Existing K-line/domain/worker tests remain required by the Fast and Full checks.
- Recovered account `90060` inspection job `06ac617e0ef141508032b180b85ce9c3` was submitted to
  generation and produced `90060_20260723_154541_20260803_054342_trade_kline.html` with 514 parsed
  trades, one accepted `XAUUSD` symbol, no failures, and confidence 1.0.

## Deployment and rollback

The production chart for the reported task was generated without restarting services. The code
change requires restarting only the K-line web process on `8766` (and `8866` when testing). Rollback
is the previous `src/kdesk/api/kline_app.py` plus service restart; generated artifacts are retained.
