# K_desk production ports and APIs

## Production services

| Service | Bind address | Port | Purpose |
| --- | --- | ---: | --- |
| Account workbench | `127.0.0.1` | `8777` | Main Vue UI, account APIs, ledger, analytics and task submission |
| K-line task center | `127.0.0.1` | `8766` | Statement upload, K-line task management and generated chart files |
| Background worker | no listening port | - | Persistent K-line, Toxic and push-discovery jobs |

Development ports `8877/8866` are reserved for isolated testing and are stopped after production cutover. Vite may use `5177` only during frontend development; production does not require Node.js or Vite.

## Account service (`8777`)

### Pages and health

- `GET /` - account risk workbench
- `GET /account/{login}` - account detail page
- `GET /health/live` - process liveness
- `GET /health/ready` - service and SQLite readiness
- `GET /api/meta` - version, profile and capability metadata

### Ledger and local data

- `GET /api/accounts`
- `GET /api/accounts/by-login/{login}/ledger`
- `POST /api/accounts/mark`
- `POST /api/accounts/mark-batch`
- `PUT /api/accounts/{record_id}`
- `DELETE /api/accounts/{record_id}`
- `GET /api/accounts/{record_id}/history`
- `GET|POST /api/quick-actions`
- `DELETE /api/quick-actions/{name}`
- `GET /download/problematic_accounts.xlsx`

### Account analytics

- `GET /api/accounts/by-login/{login}/detail`
- `GET /api/accounts/by-login/{login}/risk-panels`
- `GET /api/accounts/by-login/{login}/automation-analysis`
- `GET /api/accounts/by-login/{login}/copy-origins`
- `GET /api/accounts/by-login/{login}/copy-group-profit`
- `GET /api/accounts/by-login/{login}/login-ips`
- `GET /api/accounts/by-login/{login}/orders`
- `GET /api/account-lookup`
- `GET /api/account-lookup-finance`
- `GET /api/account-logs`
- `GET /api/trades/summary`
- `GET /api/hierarchy-products`
- `GET /api/hierarchy-net-deposit`

### Persistent jobs

- `POST /api/kline/generate-from-db`
- `GET /api/kline/jobs/{job_id}`
- `GET /api/toxic/check-types`
- `POST /api/accounts/by-login/{login}/toxic-checks`
- `GET /api/toxic/jobs/{job_id}`
- `POST /api/push-discovery/start`
- `GET /api/push-discovery/jobs/{job_id}`
- `POST /api/jobs/{job_id}/cancel`
- `GET /chart-file/{name}`

## K-line service (`8766`)

- `GET /` - K-line task center
- `GET /health/live`
- `GET /health/ready`
- `GET /api/recent`
- `POST /api/uploads`
- `POST /api/jobs/{job_id}/generate`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/cancel`
- `GET /output/{name}`

## Operations

- Start production: `pwsh -File D:\risk\K_desk_v2\scripts\start_prod.ps1`
- Stop production: `pwsh -File D:\risk\K_desk_v2\scripts\stop_prod.ps1`
- Health check: `pwsh -File D:\risk\K_desk_v2\scripts\health_check_prod.ps1`
- Roll back: `pwsh -File D:\risk\K_desk_v2\scripts\rollback_to_legacy.ps1 -ConfirmRollback ROLLBACK-KDESK`

All services bind only to localhost. MySQL, MT4 and MT5 integrations are outbound read-only data providers and do not add a K_desk listening port.
