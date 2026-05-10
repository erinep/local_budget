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
