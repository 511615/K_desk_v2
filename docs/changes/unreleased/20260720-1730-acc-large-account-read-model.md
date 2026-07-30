---
change_id: 20260720-1730-acc-large-account-read-model
features: ["ACC-DETAIL-001", "ACC-SEARCH-001", "FIN-COMP-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Complete and accelerate high-volume MT4 accounts

## Before and after

MT4 detail and order-list paths loaded at most the oldest 50,000 rows. Account 8208074 has 59,504
closed market orders, so approximately 9,500 recent orders could be omitted while every order-page
request still loaded the 50,000-row prefix. Detail also calculated identical metrics twice, and a
cold risk request generated visualizations it did not return.

MT4 analytical panels now read the complete closed-order history once and share normalized rows,
costs and metrics by account/source. Detail reuses the shared metrics, risk avoids unused detail
visualizations, and lookup-finance plus automation reuse the same analysis. Order paging now runs an
exact count and a newest-first ticket page in MySQL, then normalizes only the requested page.

## Impact

Account detail, risk panels, lookup-finance, automation analysis and order paging for high-volume
MT4 accounts. API routes and response fields remain compatible. MT5 retains its existing bounded
history behavior. All remote database operations remain read-only.

## Documentation updated

`DATA_AND_ROUTING.md`, `TEST_STRATEGY.md`, `account-detail-legacy.md`, `account-search.md` and
`comprehensive-profit.md`.

## Verification

Focused regression tests cover unlimited MT4 history, shared metric calculation, exact database
pagination and the 1970 open-position sentinel. The complete legacy account test file passes 112
tests. Read-only development acceptance for 8208074 returned 59,504 closed orders, 704 daily bars,
an exact 59,504 order total and 100 newest page rows. Independent cold timings were 5.728 seconds
for detail, 3.988 seconds for risk, 0.549 seconds for automation and 0.838 seconds for page 1.
Full verification passed 198 Python/legacy tests, 11 frontend tests, TypeScript checks and the
production build. After restarting account service 8777, production returned detail in 5.947
seconds, risk panels in 3.628 seconds, automation analysis in 3.729 seconds and order page 1 in
3.452 seconds. Results contained 59,504 closed orders, 704 daily bars, an exact 59,504 pagination
total and 100 newest orders. Browser acceptance confirmed the legacy page and expanded order table
rendered these values with no console errors. Both production readiness endpoints remained ready.

## Deployment and rollback

No schema or local-data migration. Restart only account web service 8777; K-line service 8766 is
unchanged. Rollback this code and restart 8777. The optimization changes no SQLite or remote state.
