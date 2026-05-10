# Architecture

The shape of the system. This document changes rarely.

## Module shape

Three modules plus a read-only intelligence layer. Each module owns its data and exposes a clean service-layer interface. No module reaches into another's storage.

```
┌──────────────────────────────────────────────────────┐
│                  Intelligence Layer                  │
│   (narrative summaries, anomaly detection, alerts)   │
└──────────────────┬───────────────────────────────────┘
                   │ reads from both
          ┌────────┴────────┐
          ▼                 ▼
┌──────────────────┐  ┌──────────────────┐
│ Transaction      │◄─┤ Budgeting        │
│ Engine           │  │ Module           │
└──────────────────┘  └──────────────────┘
          ▲              reads via API
          │       (seeding + actual-vs-budget)
┌──────────────────┐
│ Account Settings │
│ (category map,   │
│  user prefs)     │
└──────────────────┘
```

## Responsibilities

| Module | Owns | Reads | Writes |
|---|---|---|---|
| Account Settings | Category rules, user preferences | — | Own data |
| Transaction Engine | Raw transactions, categorization output | Account Settings | Own data |
| Budgeting Module | Budget targets, period configurations, actual-vs-budget computation | Transaction Engine (ongoing, via read API) | Own data |
| Intelligence Layer | — | Transaction Engine + Budgeting Module | Alerts, insight artifacts |

The Intelligence Layer is intentionally a **read layer** — it produces language and surfaces anomalies, but does not own canonical data and is not on the critical path for core features. It is reserved for genuine interpretation work: narrative summaries, trend analysis, anomaly detection, smart categorization. This keeps it additive and replaceable.

Budgeting reads from the Transaction Engine because actual-vs-budget tracking is core to what a budget feature is — without spending data alongside targets, it is only a wishlist. Keeping that arithmetic inside the Budgeting Module lets it ship independently of the Intelligence Layer. The read API on the Transaction Engine is a service boundary, consumed the way any external integration would consume it, which is consistent with "one job per module."

## Per-module deep dive

### Account Settings

Owns the user's category rules (the keyword → category map) and user-level preferences. Single write path: any change to a user's category map flows through this module's service interface. Direct edits to JSON files or downstream tables are bugs.

Two writers feed Account Settings, both routed through the single service interface:
- The user, via the category-management UI (introduced in Phase 2).
- Transaction-edit flows that opt into "apply this rule going forward" (introduced in Phase 3b) and any future smart-categorization corrections (Phase 5). These two writers must use a shared conflict-resolution rule documented in an ADR — see the categorization-feedback risk in [risks.md](risks.md).

Caching: a user's category map is loaded once per request, not per transaction. The cache key includes a version stamp that bumps on any write, so cache invalidation is implicit.

### Transaction Engine

Owns raw transactions and the categorization output. The most consumed module in the system; its read API is the contract the rest of the platform depends on.

Read API (introduced incrementally — see [roadmap.md](roadmap.md)):

- `get_transactions(user_id, filters)` — paginated, filterable list (date range, category, amount range, search). Drives the report and the history view.
- `get_transaction(user_id, transaction_id)` — single record fetch. Drives the edit / recategorize flows.
- `get_spend_by_category(user_id, period)` — aggregate spend per category for a given period. Drives Budgeting's actual-vs-budget views.
- `get_spend_history(user_id, category_id, periods)` — historical aggregates per category. Drives budget proposals and trend insights.

The API is documented and tested at the service layer, independently of any HTTP route, so it can be reused across web requests, background jobs, and future surfaces without coupling to the route layer's request lifecycle.

Idempotency: re-uploading the same CSV must not double-count. The dedup strategy (hash-based vs. composite key) is resolved as part of Phase 3a and recorded in an ADR.

### Budgeting Module

Owns budget targets and period configurations. Performs the actual-vs-budget computation by joining its own targets against `get_spend_by_category` output from the Transaction Engine. The Transaction Engine is read-only from Budgeting's perspective; budgets never write to transactions.

The "Propose a budget" feature uses `get_spend_history` to suggest realistic targets per category. After the initial proposal, budgets are user-owned and live entirely in this module's tables.

### Intelligence Layer

Owns no canonical data. Reads from Transaction Engine and Budgeting Module. Produces:

- **Alerts** — threshold-driven (e.g., "80% of food budget"), surfaced in-app. Stored so they can be acknowledged or dismissed; not derivable from transactions alone because state changes (dismissal) are user-driven.
- **Insight artifacts** — narrative summaries (monthly), anomaly notes. Stored to avoid recomputing LLM output, but always regeneratable from the source modules.
- **Smart categorization fallback** — when keyword categorization fails, the Intelligence Layer proposes a category. User corrections flow back to Account Settings via the Account Settings write path; the Intelligence Layer does not own learned rules.

Because everything the Intelligence Layer produces is either regeneratable or user-driven state, the layer can be paused, rebuilt, or replaced without touching core features.

## Guiding principles

1. **One job per module.** Each service owns its data and exposes a clean interface. No module reaches into another's storage directly.
2. **Stateless processing where possible.** Persistence only where required for the feature to function.
3. **Data privacy is non-negotiable.** Financial data demands encryption at rest, secure auth, and minimal retention.
4. **Ship vertical slices.** Every phase ends with a working app a user could use. No big-bang releases.
5. **Tests gate every merge.** The CI pipeline already enforces this; do not erode it.
6. **Reversibility over optimization.** Prefer simple choices that can be undone over clever ones that can't.

## Cross-cutting concerns

### Security

- All data encrypted at rest (Supabase / Postgres handles this once introduced in Phase 1).
- HTTPS enforced (Render handles this; verify in middleware).
- Password hashing via Argon2 or bcrypt (Supabase handles this).
- CSRF protection on all state-changing routes, including upload (Flask-WTF or equivalent).
- Rate limiting on auth endpoints from Phase 1; on LLM-backed endpoints from Phase 5.
- Audit log for sensitive actions (data export, account deletion).
- One owner per change to the auth surface. Security review required before public launch.

### Observability

- Structured logging from Phase 0 onward, with a PII scrubber for transaction descriptions, amounts, and email addresses.
- Error tracking (Sentry, free tier) from Phase 1.
- Request tracing if the system is ever split across services.
- Basic uptime monitoring (UptimeRobot free tier).

### Testing

- Unit test coverage above 70% on services.
- Integration tests for every route.
- A small end-to-end suite (Playwright) added in Phase 1 covering: sign up → upload → see report.
- Database fixtures and rollback strategy for tests added in Phase 1.

### Data

- Backups: automated daily backups when Postgres is introduced. Quarterly restore drill into a scratch database with checksum verification — backups are not real until they have been restored.
- Migration discipline: every schema change goes through migration tooling. Never raw SQL on prod. Only one agent holds the migration write-lock at a time.
- PII handling: documented per table — what is stored, why, and the retention period.
- Timezones: all timestamps stored in UTC. One canonical conversion layer for rendering to user-local time. No exceptions.

### Documentation

- ADRs (Architecture Decision Records) for every non-trivial choice — see [adr/](adr/).
- API documentation auto-generated from route definitions when the surface grows.
- A user-facing privacy policy and data-handling document before user signups open publicly.
