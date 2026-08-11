---
change_id: 20260811-acc-rel-continuous-expansion
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: improvement
status: unreleased
compatibility: compatible
---

# Continue relationship discovery through the propagation threshold

## Before and after

Before, the account relationship endpoint performed discovery inside one HTTP request and stopped
after a 12-second total budget. A high-fanout current-LastIP group could consume that budget before
the second or third relationship layer was read, even when those accounts remained above the selected
score threshold.

After, one local single-flight background expansion owns an equivalent account/filter/threshold
request. The endpoint returns immediately with a pollable snapshot, and the Kuzu page automatically
updates while score-eligible accounts continue to be read. The fixed node/score-expansion and final
projection caps remain safety boundaries. Known accounts in the same current-LastIP cohort do not
repeat the identical same-server lookup, and the relationship graph no longer runs the slower personal
login-IP observation source that cannot create account-to-account edges.

## Impact

The compatible endpoint adds `inProgress` and `progress` fields. Existing entities, relationships,
coverage, threshold and score fields retain their shape. At most one relationship expansion executes
locally at once, protecting 8777 and the read-only source databases from duplicate scans.

## Documentation updated

Updated ACC-REL-001, ACC-REL-003, architecture, data-routing, endpoint and test-strategy authorities
to describe background continuous expansion, polling state and LastIP cohort de-duplication.

## Verification

Tests cover threshold-based expansion with no default total deadline, single-flight progress polling,
LastIP cohort query de-duplication, API completion after polling and the existing scoring/Kuzu paths.
Fast and Full governed verification are required before deployment.

## Deployment and rollback

Deploy only the verified 8777 account service from `main`. No remote or local schema/data migration
is involved. Roll back by restarting the preceding verified account-service commit.
