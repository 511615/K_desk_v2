# ADR-0003: LegacyBridge is the only legacy boundary

- Status: Accepted
- Date: 2026-07-17

Only `src/kdesk/infrastructure/legacy_bridge.py` may load the copied monolith. Features are extracted
vertically while URLs, the legacy account page and response contracts remain stable.
