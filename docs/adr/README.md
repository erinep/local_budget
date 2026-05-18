# Architecture Decision Records

One file per non-trivial decision. Append-only.

## Index

| # | Title | Status | Date |
|---|---|---|---|
| [0001](0001-utc-timestamps.md) | UTC-Everywhere Timestamp Strategy | Accepted | 2026-05-10 |
| [0002](0002-supabase-database-and-auth.md) | Supabase for Database and Authentication | Accepted | 2026-05-10 |
| [0003](0003-module-communication-service-layer-only.md) | Module Communication via Service-Layer Interfaces Only | Accepted | 2026-05-10 |
| [0004](0004-flask-blueprint-layout.md) | Flask Blueprint Layout and Module Boundary Mapping | Accepted | 2026-05-10 |
| [0005](0005-category-map-dependency-injection.md) | Category Map Dependency Injection Pattern | Accepted | 2026-05-10 |
| [0006](0006-session-strategy.md) | Session Strategy — Cookie-Based Server-Side Sessions | Accepted | 2026-05-10 |
| [0007](0007-schema-migration-tooling.md) | Schema Migration Tooling — Alembic | Accepted | 2026-05-10 |
| [0008](0008-google-oauth-deferred.md) | Google OAuth Deferred to Phase 1.5 | Accepted | 2026-05-10 |
| [0009](0009-account-settings-schema-normalization.md) | Account Settings Schema Normalization — JSONB to Relational Tables | Accepted | 2026-05-16 |
| [0010](0010-account-settings-caching.md) | Account Settings Caching — Request-Scoped Cache via flask.g | Accepted | 2026-05-16 |
| [0011](0011-navigation-and-landing-page-contract.md) | Navigation and Landing Page Contract | Accepted | 2026-05-17 |
| [0012](0012-supabase-mocking-in-unit-tests.md) | Supabase Mocking in Unit Tests | Accepted | 2026-05-17 |
| [0013](0013-transaction-idempotency-strategy.md) | Transaction Idempotency Strategy — Two-Layer Hash | Accepted | 2026-05-17 |
| [0014](0014-multi-account-per-user.md) | Multi-Account-Per-User — Design Schema Now, Defer UI | Accepted | 2026-05-17 |
| [0015](0015-data-retention-on-account-deletion.md) | Data Retention on Account Deletion — Hard Cascade, No Grace Period | Accepted | 2026-05-17 |
| [0016](0016-transactions-uploads-accounts-schema.md) | Phase 3a Schema — accounts, uploads, transactions in One Migration | Accepted | 2026-05-17 |
| [0017](0017-transaction-engine-read-api.md) | Transaction Engine Read API — get_transactions, get_transaction | Accepted | 2026-05-17 |
| [0018](0018-transaction-engine-write-api.md) | Transaction Engine Write API — recategorize_transaction | Accepted | 2026-05-18 |
| [0019](0019-history-view-route-and-pagination.md) | History View Route, Filter Subset, and Pagination Contract | Accepted | 2026-05-18 |
| [0020](0020-recategorize-ui-flow.md) | Recategorize UI Flow — Edit Page, Apply-Forward Checkbox, Redirect | Accepted | 2026-05-18 |
| [0021](0021-upload-file-management-route-ownership.md) | Upload File Management Route Ownership — Transaction Engine Blueprint | Accepted | 2026-05-18 |
| [0022](0022-uploads-live-transaction-count.md) | Uploads: Replace Stored Row Count with Live Transaction Count | Accepted | 2026-05-18 |
| [0023](0023-aggregation-api.md) | Transaction Engine Aggregation API — get_spend_by_category and get_spend_history | Accepted | 2026-05-18 |
| [0024](0024-intelligence-layer-report-ownership.md) | Intelligence Layer Report Ownership — Module Assignment, URL Structure, and Rendering Architecture | Accepted | 2026-05-18 |
| [0025](0025-budgeting-module.md) | Budgeting Module — Schema, Service API, and Route Design | Partially superseded by ADR-0026 | 2026-05-18 |
| [0026](0026-budgets-global-targets.md) | Budgets — Global Targets, Not Month-Specific Rows | Accepted | 2026-05-18 |

When the first ADR lands, replace the placeholder row with a real entry. Keep entries sorted by number, ascending.

## How to add an ADR

1. Copy [`0000-template.md`](0000-template.md) to `NNNN-short-kebab-title.md`. Number sequentially from the highest existing ADR; do not reuse numbers, even for superseded decisions.
2. Fill in the sections. Keep prose tight — an ADR is a record, not an essay.
3. Set the status: `Proposed`, `Accepted`, `Superseded by NNNN`, or `Deprecated`.
4. Add the entry to the index above in the same PR.
5. If the ADR supersedes an earlier one, edit the earlier ADR's status to `Superseded by NNNN` and link forward. Do not edit the earlier ADR's body.

## When an ADR is required

Any of:
- A schema design decision that future migrations would have to undo.
- A choice between platforms or libraries with non-trivial migration cost (auth provider, DB host, queue runner).
- A cross-module contract that downstream modules will pin to.
- A security or compliance posture choice (retention policy, deletion semantics, log scrubbing rules).
- A reversal or significant evolution of an earlier ADR.

If you are unsure whether a decision is "non-trivial," err on writing the ADR. The marginal cost is low; the cost of missing context six months later is high.

## What an ADR is not

- A design doc. ADRs record *decisions*, not exhaustive design exploration. If you need a longer document to explore options, write that separately and link it from the ADR's Context section.
- A status update. ADRs do not track progress; the [roadmap](../roadmap.md) does.
- A risk register. Risks live in [risks.md](../risks.md); link from an ADR if a decision exists to mitigate a specific risk.
