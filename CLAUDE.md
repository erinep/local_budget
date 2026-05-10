# Local Budget Parser

Personal finance platform evolving from a stateless CSV report tool into a multi-module system with persisted user data, configurable budgets, and an intelligence layer for narrative insights and proactive alerts.

This file is the orientation entry point. It is intentionally short. Detail lives in `docs/`.

## Status

- **Current phase:** Phase 0 — Foundation Hardening
- **Last updated:** 2026-05-09

Update both fields when a phase ships.

## Stack

- **Web framework:** Flask (Python)
- **Tests:** pytest (currently 23 tests covering pure functions and routes)
- **CI:** GitHub Actions on every PR
- **Deploy:** Render on merge to `main`
- **Database (Phase 1+):** PostgreSQL via Supabase
- **Auth (Phase 1+):** Supabase Auth (email/password + Google OAuth)

## Module shape

The system is organized as four modules plus a read-only intelligence layer. Each module owns its data and exposes a clean service-layer interface. No module reaches into another's storage.

- **Account Settings** — owns category rules and user preferences. Single write path for any change to a user's category map.
- **Transaction Engine** — owns raw transactions and categorization output. Exposes a documented read API consumed by every downstream module.
- **Budgeting Module** — owns budget targets and the actual-vs-budget computation. Reads from the Transaction Engine via API.
- **Intelligence Layer** — owns no canonical data. Reads from Transaction Engine and Budgeting. Produces narrative summaries, anomaly detection, smart categorization, alerts. Always additive, never on the critical path for core features.

See [docs/architecture.md](docs/architecture.md) for the diagram, responsibilities table, per-module deep dive, and cross-cutting concerns.

## Where to find things

- [docs/architecture.md](docs/architecture.md) — module shape, principles, cross-cutting concerns. Stable; changes rarely.
- [docs/roadmap.md](docs/roadmap.md) — phases, work items, exit criteria. Updated as phases ship.
- [docs/risks.md](docs/risks.md) — living risk register with phase mapping.
- [docs/orchestration.md](docs/orchestration.md) — how AI agents work this codebase: roles, parallelism rules, merge protocol.
- [docs/adr/](docs/adr/) — Architecture Decision Records, one file per non-trivial decision. Use [docs/adr/0000-template.md](docs/adr/0000-template.md).

## Discipline (do not skip)

1. **Every non-trivial decision becomes an ADR.** Number sequentially. Future-you will thank you.
2. **Every schema change goes through migration tooling.** Never raw SQL on prod. Only one agent holds the migration write-lock at a time.
3. **CI gates every merge.** The pytest + Render pipeline is the floor; reviewer-agent passes are additive, not a replacement.
4. **Modules talk only through documented APIs.** Cross-module reads via service-layer interfaces. Direct database access into another module's tables is a bug, not a shortcut.
5. **Vertical slices over horizontal layers.** Every PR ships something a user could touch. No big-bang releases.
6. **Branch naming.** When creating branches, follow naming convention `<agent-role>/kebab-task-summary` — e.g., architect/adr-0006-session-strategy, implementation/phase0-blueprint-refactor, refactor/extract-services-package.


## Constraints to respect

- **Financial data:** encrypted at rest, PII scrubbed from logs, retention policy documented per table.
- **Auth surface:** one owner per change. Security review required before public launch.
- **LLM endpoints:** per-user rate caps and circuit breakers. Merchant-level caching with long TTL. No endpoint is exposed without cost controls.
- **Background jobs:** required by Phase 5 and not available on the current Render free tier. Hosting decision must be resolved before Phase 4 ends.
- **Timezones:** all timestamps in UTC. One canonical conversion layer for rendering. No exceptions.

## For a fresh agent starting work

1. Read this file (you are here).
2. Read [docs/architecture.md](docs/architecture.md).
3. Read [docs/roadmap.md](docs/roadmap.md) and find the current phase in the status table.
4. Read any ADRs in [docs/adr/](docs/adr/) relevant to the current phase.
5. Read [docs/risks.md](docs/risks.md) and filter to risks tagged with the current phase or `All`.

That is sufficient context to start work.
