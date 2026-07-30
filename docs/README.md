# K_desk documentation map

This directory is the authoritative maintenance source for K_desk. Documents are written in
English; Chinese UI labels and business field names remain unchanged.

| Authority | Document |
| --- | --- |
| Runtime and dependency boundaries | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Module ownership | [MODULE_CATALOG.md](MODULE_CATALOG.md) |
| Storage and server routing | [DATA_AND_ROUTING.md](DATA_AND_ROUTING.md) |
| Financial and detection rules | [BUSINESS_RULES.md](BUSINESS_RULES.md) |
| Ports and public endpoints | [PORTS_AND_APIS.md](PORTS_AND_APIS.md) |
| Startup, release and rollback | [OPERATIONS.md](OPERATIONS.md) |
| Required verification | [TEST_STRATEGY.md](TEST_STRATEGY.md) |
| Current feature behavior | [features/](features/) |
| Approved future implementation plans | [plans/](plans/) |
| Immutable change history | [changes/](changes/) and [CHANGELOG.md](CHANGELOG.md) |
| Architecture decisions | [ADR/](ADR/) |

Feature documents use a machine-readable YAML-compatible header. Run
`python scripts/governance.py registry --check` to verify that
`docs/feature-registry.json` exactly matches those documents.

## Change decision

- New or changed behavior: update the feature document and add an unreleased change record.
- Bug fix with unchanged documented behavior: add a change record; update the feature document's
  verification date and any inaccurate behavior.
- API, data/routing, formula, architecture or operations change: also update the corresponding
  system authority and generated contract.
- Internal refactor: add a change record; update architecture only if responsibilities or
  dependencies changed.
- Feature removal: deprecate first, document the replacement and removal version, then remove only
  after the compatibility window.
