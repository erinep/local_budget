---
adr: 0014
title: Multi-Account-Per-User — Design Schema Now, Defer UI
status: Accepted
date: 2026-05-17
phase: P3a
deciders: erin
---

## Context

Phase 3a is the first phase in which transactions are persisted. The [roadmap's open decisions table](../roadmap.md#open-decisions) flags multi-account-per-user as a decision to resolve before 3a starts, with the recommendation: *"Designing for it now is cheap; bolting it on later is expensive. Recommendation: yes, design schema for it even if UI ships later."* This ADR fixes that decision.

An **account** in this ADR means a per-financial-institution source the user uploads CSVs for — e.g., a checking account at Bank A, a credit card at Issuer B. It is **not** the user's login account (that lives in `auth.users`).

Today the app is single-account by accident: users upload one CSV at a time and the schema has nowhere to record which institution it came from. Real users have at least a checking account and a credit card. Once transactions are persisted, mixing them without an account boundary makes ongoing dedup, future budgeting, and any per-source reporting structurally impossible.

This ADR interacts directly with [ADR-0013](0013-transaction-idempotency-strategy.md): `account_id` must be part of the row-level fingerprint so that identical date/amount/description on two different accounts do not collide as false-positive duplicates.

## Options considered

### Option A — Defer entirely; single implicit account per user

Skip the `accounts` table in 3a. `transactions` and `uploads` carry `user_id` only. Add the concept later when multi-account UI becomes a real feature.

**Pros:** Smallest possible schema in 3a. Fewer tables, fewer joins, less surface.

**Cons:** Every later phase pays a migration tax that grows with the row count: adding `account_id` to a populated `transactions` table requires a backfill, a default-account creation for every existing user, and a fingerprint recomputation (because the fingerprint canonicalization includes `account_id`). The fingerprint backfill is the killer — it cannot be done safely on a live table without a downtime window or a careful staged migration. The roadmap calls this out explicitly.

### Option B — Design schema now, defer UI

Ship the `accounts` table in 3a's first migration. `transactions.account_id` and `uploads.account_id` are `NOT NULL` FKs from day one. The upload service auto-creates a single hidden "Default" account on a user's first upload. No accounts management UI in 3a.

**Pros:** 3a is the only phase where backfill is free — there are no existing transactions to migrate. The fingerprint canonicalization is correct from day one. The Phase 3c read API can accept an optional `account_id` filter without retrofit. Phase 4 budgeting can later choose cross-account or per-account without a schema change.

**Cons:** One extra table and two FK columns in 3a. A small amount of service-layer plumbing for the Default-account creation. No user-visible benefit until a later phase ships the management UI.

### Option C — Hybrid: nullable `account_id` with a sentinel

Add the column but allow `NULL` and treat `NULL` as "default." Defer the `accounts` table itself.

**Pros:** Slightly smaller schema than Option B in 3a.

**Cons:** Worst of both worlds. `NULL` semantics propagate into the fingerprint canonicalization (does `NULL` hash as empty string? as a literal `"null"`? this is exactly the kind of ambiguity that produces silent bugs). The unique constraint on `(user_id, fingerprint)` becomes harder to reason about. And eventually the `accounts` table still has to be created and the rows backfilled — at which point you have all the costs of Option A and none of the cleanliness of Option B.

## Decision

We will choose **Option B — design the schema now, defer the UI**. The two reasons that carried the decision: (1) 3a is the only phase where the backfill cost is zero, and any later phase pays for the deferral with a fingerprint-rewriting migration on a populated table, and (2) [ADR-0013](0013-transaction-idempotency-strategy.md)'s idempotency canonicalization needs `account_id` in its tuple from day one to avoid collapsing same-date/same-amount rows from different financial sources as false-positive duplicates.

## Schema sketch

### `public.accounts`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY, DEFAULT gen_random_uuid() |
| user_id | UUID | NOT NULL, FK → auth.users(id) ON DELETE CASCADE |
| name | TEXT | NOT NULL |
| kind | TEXT | NOT NULL — one of: `checking`, `savings`, `credit_card`, `other` |
| currency | TEXT | NOT NULL, DEFAULT `'CAD'` |
| is_active | BOOLEAN | NOT NULL, DEFAULT `true` |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() |

Constraints:
- `UNIQUE (user_id, name)` — prevents duplicate account names per user.

Indexes:
- `idx_accounts_user_id ON accounts (user_id)` — covers `WHERE user_id = ?`.
- The `UNIQUE (user_id, name)` constraint creates an implicit index.

### FK columns added to `transactions` and `uploads`

| Table | Column | Constraints |
|---|---|---|
| transactions | account_id | UUID NOT NULL, FK → accounts(id) ON DELETE CASCADE |
| uploads | account_id | UUID NOT NULL, FK → accounts(id) ON DELETE CASCADE |

Indexes:
- `idx_transactions_account_id ON transactions (account_id)`.
- `idx_uploads_account_id ON uploads (account_id)`.

`ON DELETE CASCADE` aligns with [ADR-0015](0015-data-retention-on-account-deletion.md).

## Service-layer contract

A new `app/transactions/services.py` function — `get_or_create_default_account(user_id)` — is called by the upload service inside the upload transaction. On a user's first upload:

1. The function looks for any active account for `user_id`.
2. If none exists, it inserts one with `name='Default'`, `kind='checking'`, `currency='CAD'`. The insert uses `ON CONFLICT (user_id, name) DO NOTHING RETURNING id` to be safe under concurrent first-uploads.
3. The function returns the account id.

This means accounts are invisible in 3a but the schema is correct. When Phase 3b or later ships an account-management UI, the data is already in place and the service contract does not change.

## Interaction with idempotency (ADR-0013)

`account_id` is part of the row-level fingerprint tuple. Same date, same description, same amount on two different accounts produce two different fingerprints and two different rows. Same on the same account collapses (subject to `within_file_seq` for genuine duplicates).

## Interaction with Phase 3c and Phase 4

Phase 3c's aggregation API (`get_spend_by_category(user_id, period)`, `get_spend_history(user_id, category_id, periods)`) MUST accept an optional `account_id` filter from day one. Phase 4 will decide whether budgets are per-account, cross-account, or both — that decision is **explicitly deferred** to Phase 4. The 3c contract just leaves the lever in place.

## PII handling

`accounts.name` and `accounts.kind` are user-defined labels, not raw transaction data. Retention: cascade on user deletion per [ADR-0015](0015-data-retention-on-account-deletion.md).

## Consequences

- **Positive:** Zero-cost design-time decision; every later phase that touches transactions inherits the correct shape.
- **Positive:** Fingerprint canonicalization (ADR-0013) is correct from day one.
- **Positive:** Phase 4 budgeting can choose cross-account or per-account without a schema change.
- **Negative:** One extra table and two FK columns to maintain in 3a.
- **Negative:** Service-layer plumbing for Default-account creation. A small but non-zero amount of code that has no user-visible payoff until a later phase.
- **Follow-up:** The upload service must call `get_or_create_default_account` inside the upload transaction. The Phase 3a implementation agent owns this.
- **Follow-up:** Phase 3b or later will ship an accounts management UI. At that point the user will be able to rename "Default" and create additional accounts. The schema already supports this.
- **Follow-up:** Status is **Proposed** until human review. The interaction with ADR-0013 means a change in shape requires re-pinning both ADRs together.
