---
feature_id: KLN-DB-001
title: Database K-line generation
module: kline
status: active
apis: ["POST /api/kline/generate-from-db", "POST /api/uploads", "POST /api/jobs/{job_id}/generate", "GET /output/{name}"]
code: ["src/kdesk/api/account_app.py", "src/kdesk/api/kline_app.py", "src/kdesk/worker/runner.py"]
tests: ["tests/test_api.py"]
depends_on: ["JOB-RECOVERY-001", "ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-17
---

# Database K-line generation

## Purpose and user entry

Generate buy/sell K-line evidence from account databases or uploaded statements and expose the
result through account detail and the K-line task center.

## UI and behavior

Submission is asynchronous; users see durable progress/events and can open generated HTML charts.

## API contract

Account and K-line endpoints submit jobs, poll by job ID, cancel and serve safe artifact names.

## Data, routing and read-only constraints

Database and MT5 quote access is read-only. Uploads/artifacts remain inside configured runtime directories.

## Business rules and units

Chart alignment uses documented symbol/time mapping; trade identifiers, lots and prices are not USC-scaled.

## Loading, empty and failure behavior

Invalid uploads, unavailable quotes and unsafe paths fail explicitly. Jobs survive web restart.

## Code and dependencies

FastAPI validates/submits; the worker owns quote sessions and generator execution.

## Tests and acceptance

API tests cover upload, job generation, polling, cancellation and path traversal protection.

## Compatibility and deprecation

Existing chart URLs and account generation parameters remain compatible.
