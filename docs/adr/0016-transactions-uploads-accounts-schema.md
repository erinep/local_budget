---
adr: 0016
title: Phase 3a Schema — accounts, uploads, transactions in One Migration
status: Accepted
date: 2026-05-17
phase: P3a
deciders: erin
---

## Context

Phase 3a introduces three new tables that together back the persisted Transaction Engine: `public.accounts`, `public.uploads`, and `public.transactions`. Their shape is already constrained by three upstream ADRs that landed on the same day:

- [ADR-0013](0013-transaction-idempotency-strategy.md) — two-layer hash idempotency: `uploads.file_hash` and `transactions.fingerprint`, with `UNIQUE (user_id, file_hash)` and `UNIQUE (user_id, fingerprint)`.
- [ADR-0014](0014-multi-account-per-user.md) — design the `accounts` table now, defer the UI. `account_id` is `NOT NULL` on both `transactions` and `uploads`.
- [ADR-0015](0015-data-retention-on-account-deletion.md) — hard cascade on user deletion. Every per-user table FKs to `auth.users(id) ON DELETE CASCADE`, and transitive cascades on `accounts(id)` and `uploads(id)` provide defense-in-depth on `transactions`.

This ADR is the **schema specification** that consolidates those three decisions into one concrete artifact the implementation agent can author the Alembic migration from. It is not the migration code; it is the contract the migration code must implement.

Per [ADR-0007](0007-schema-migration-tooling.md) the migration write-lock applies: a single agent authors a single Alembic revision. The current head is revision `0002_normalize_categories`; this work is the next revision in sequence.

Relevant risks: "Schema design locks in early mistakes" (P3a, High), "Data loss during a migration cutover" (P1+, Very High), and the deletion-cascade risk pinned by ADR-0015.

## Options considered

### Option 1 — One Alembic revision, three tables, one transaction

A single revision `0003_transactions_uploads_accounts` creates `accounts`, `uploads`, and `transactions` in dependency order inside a single transaction. Postgres has transactional DDL, so a mid-flight failure rolls back atomically.

**Pros:** Atomic. Either the whole Phase 3a schema lands or none of it does. The migration history has a single boundary point — before 0003 there are no persisted transactions; after 0003 the entire Transaction Engine surface exists. Easiest mental model for rollback. Matches the pattern set by ADR-0009 / revision 0002 (one revision, one cohesive schema change, transactional).

**Cons:** A single migration file is longer than three small ones. If a single index is wrong the rollback rewinds all three tables. In practice this is fine because the tables are empty on rollback — there is no data to preserve.

### Option 2 — Three sequential revisions (one per table)

Revision 0003 creates `accounts`; 0004 creates `uploads`; 0005 creates `transactions`.

**Pros:** Each revision is small and reviewable in isolation.

**Cons:** Between revisions the schema is partially built. If 0003 ships to prod and 0004 fails CI for a week, the database carries an `accounts` table with no consumer. The Phase 3a slice cannot ship until all three land anyway, so the small-revision granularity buys nothing. Three boundaries for rollback instead of one. No real benefit at this scale.

### Option 3 — Create `accounts` in an earlier, separate revision; bundle `uploads` + `transactions` together

Land `accounts` first (since it has no upstream dependency in this batch), then `uploads` + `transactions` together because they share the file-hash / fingerprint contract.

**Pros:** Slightly smaller second revision.

**Cons:** Same as Option 2 — partial-state window with no payoff. `accounts` exists only to be referenced by `uploads.account_id` and `transactions.account_id`; shipping it ahead of its consumers is pure churn.

### Sub-option — fingerprint and file_hash storage representation

`BYTEA` raw 32 bytes (SHA-256 digest), `BYTEA` of hex-encoded ASCII (64 bytes), or `UUID` (16 bytes).

- **Raw `BYTEA`** is 32 bytes, indexable, exact match for SHA-256 output, no encoding round-trip. Postgres comparison is byte-equality. Standard choice.
- **Hex `BYTEA` / `TEXT`** doubles storage and requires every comparison to canonicalize encoding (uppercase vs lowercase hex). Pointless.
- **`UUID`** is only 16 bytes (half a SHA-256 digest) and would require truncation, weakening collision resistance for no benefit.

Pick raw `BYTEA`. ADR-0013 already specifies this; recording the rejection of the alternatives here for completeness.

## Decision

**Option 1 — one Alembic revision, three tables, one transaction, in dependency order: `accounts` → `uploads` → `transactions`.** Hash columns stored as raw `BYTEA` (32 bytes, SHA-256 digest).

The two reasons that carried the decision: (1) the three tables are a cohesive vertical slice and rollback is trivial because no data exists yet — splitting buys nothing, and (2) Postgres transactional DDL plus a single boundary point in the migration history is the simplest thing that is also correct.

## Schema specification

All `TIMESTAMPTZ` columns default to `now()` per [ADR-0001](0001-utc-timestamps.md). All UUID primary keys default to `gen_random_uuid()`. Every per-user table cascades to `auth.users(id)` per [ADR-0015](0015-data-retention-on-account-deletion.md).

### `public.accounts`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY, DEFAULT `gen_random_uuid()` |
| user_id | UUID | NOT NULL, FK → `auth.users(id)` ON DELETE CASCADE |
| name | TEXT | NOT NULL |
| kind | TEXT | NOT NULL — one of `checking`, `savings`, `credit_card`, `other` |
| currency | TEXT | NOT NULL, DEFAULT `'CAD'` |
| is_active | BOOLEAN | NOT NULL, DEFAULT `true` |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT `now()` |

Constraints:
- `UNIQUE (user_id, name)` — prevents duplicate account names per user. Implicitly indexes `(user_id, name)`.
- `CHECK (kind IN ('checking','savings','credit_card','other'))` — enforces the enum at the DB layer. (A Postgres `ENUM` type is an acceptable alternative; `CHECK` is preferred because it is easier to evolve than `ALTER TYPE`.)

Indexes:
- `idx_accounts_user_id ON accounts (user_id)` — covers `WHERE user_id = ?`.
- The `UNIQUE (user_id, name)` constraint creates an implicit index that also satisfies `WHERE user_id = ? AND name = ?` (used by `get_or_create_default_account`'s upsert).

Foreign keys:
- `user_id → auth.users(id) ON DELETE CASCADE`.

### `public.uploads`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY, DEFAULT `gen_random_uuid()` |
| user_id | UUID | NOT NULL, FK → `auth.users(id)` ON DELETE CASCADE |
| account_id | UUID | NOT NULL, FK → `public.accounts(id)` ON DELETE CASCADE |
| filename | TEXT | NOT NULL |
| file_hash | BYTEA | NOT NULL — SHA-256 digest, exactly 32 bytes |
| row_count | INTEGER | NOT NULL, CHECK (`row_count >= 0`) |
| uploaded_at | TIMESTAMPTZ | NOT NULL, DEFAULT `now()` |

Constraints:
- `UNIQUE (user_id, file_hash)` — byte-identical re-upload short-circuits before parsing (ADR-0013, file-level layer). Implicitly indexes `(user_id, file_hash)`.
- `CHECK (octet_length(file_hash) = 32)` — defensive: rejects mis-sized hashes at the DB boundary.

Indexes:
- `idx_uploads_user_id ON uploads (user_id)` — covers `WHERE user_id = ?` listings (history view in 3b).
- `idx_uploads_account_id ON uploads (account_id)` — covers `WHERE account_id = ?` listings (per ADR-0014).
- The `UNIQUE (user_id, file_hash)` constraint creates an implicit index sufficient for the file-hash short-circuit lookup; no separate index needed.

Foreign keys:
- `user_id → auth.users(id) ON DELETE CASCADE`.
- `account_id → accounts(id) ON DELETE CASCADE`.

### `public.transactions`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY, DEFAULT `gen_random_uuid()` |
| user_id | UUID | NOT NULL, FK → `auth.users(id)` ON DELETE CASCADE |
| account_id | UUID | NOT NULL, FK → `public.accounts(id)` ON DELETE CASCADE |
| source_file_id | UUID | NOT NULL, FK → `public.uploads(id)` ON DELETE CASCADE |
| date | DATE | NOT NULL — transaction date (no time component; canonicalized to UTC calendar date by the parser) |
| description | TEXT | NOT NULL — original/unnormalized description as it appeared in the source CSV |
| amount | NUMERIC(12,2) | NOT NULL — signed; debits negative, credits positive |
| category_id | UUID | NULLABLE, FK → `public.categories(id)` ON DELETE SET NULL |
| fingerprint | BYTEA | NOT NULL — SHA-256 digest, exactly 32 bytes (per ADR-0013 canonicalization rule) |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT `now()` |

Constraints:
- `UNIQUE (user_id, fingerprint)` — row-level dedup across overlapping uploads (ADR-0013). Inserts use `ON CONFLICT (user_id, fingerprint) DO NOTHING`. Implicitly indexes `(user_id, fingerprint)`.
- `CHECK (octet_length(fingerprint) = 32)` — defensive bound on hash size.

`category_id` rationale (NULLABLE + `ON DELETE SET NULL`):

- **Nullable** because the categorizer is not guaranteed to resolve every transaction. The current rule-based categorizer returns an "Uncategorized" sentinel; persisting that as a real row in `categories` would either pollute every user's category list or require a hidden system category. Both are worse than allowing `category_id IS NULL` and treating it as the uncategorized state in the read layer. Phase 5's smart categorization may later fill these in.
- **`ON DELETE SET NULL`** rather than `CASCADE` because deleting a user-defined category should not delete the underlying spend. The transaction remains; it becomes uncategorized. This is the only FK on `transactions` that does not cascade.

Indexes (composite indexes are deliberate; see [Indexes for the read API](#indexes-for-the-read-api)):

- `idx_transactions_user_date ON transactions (user_id, date DESC)` — covers the dominant read pattern `WHERE user_id = ? AND date BETWEEN ? AND ?` ordered by date descending (history view, report).
- `idx_transactions_user_category ON transactions (user_id, category_id)` — covers `WHERE user_id = ? AND category_id = ?` (filter by category). Includes `NULL` rows.
- `idx_transactions_user_account ON transactions (user_id, account_id)` — covers `WHERE user_id = ? AND account_id = ?` (per-account filter from ADR-0014).
- `idx_transactions_source_file ON transactions (source_file_id)` — covers reverse lookups "which transactions came from this upload" (3b history view and the cascade delete path).
- The `UNIQUE (user_id, fingerprint)` constraint creates an implicit index sufficient for the dedup conflict check; no separate index needed.

Foreign keys:
- `user_id → auth.users(id) ON DELETE CASCADE`.
- `account_id → accounts(id) ON DELETE CASCADE` (per ADR-0014).
- `source_file_id → uploads(id) ON DELETE CASCADE` (per ADR-0015, defense in depth).
- `category_id → categories(id) ON DELETE SET NULL` (see rationale above).

## Migration sequence

Single Alembic revision: `migrations/versions/0003_transactions_uploads_accounts.py`. Revises: `0002`.

The entire `upgrade()` runs inside the implicit Alembic transaction (Postgres transactional DDL). Order matters because of FK dependencies.

### `upgrade()`

1. `CREATE TABLE public.accounts` with all columns, the `UNIQUE (user_id, name)` constraint, the `CHECK` on `kind`, and the FK on `user_id`.
2. `CREATE INDEX idx_accounts_user_id ON public.accounts (user_id)`.
3. `CREATE TABLE public.uploads` with all columns, the `UNIQUE (user_id, file_hash)` constraint, the `CHECK` on `octet_length(file_hash)`, and FKs on `user_id` and `account_id`.
4. `CREATE INDEX idx_uploads_user_id ON public.uploads (user_id)`.
5. `CREATE INDEX idx_uploads_account_id ON public.uploads (account_id)`.
6. `CREATE TABLE public.transactions` with all columns, the `UNIQUE (user_id, fingerprint)` constraint, the `CHECK` on `octet_length(fingerprint)`, and the four FKs (`user_id`, `account_id`, `source_file_id`, `category_id`).
7. `CREATE INDEX idx_transactions_user_date ON public.transactions (user_id, date DESC)`.
8. `CREATE INDEX idx_transactions_user_category ON public.transactions (user_id, category_id)`.
9. `CREATE INDEX idx_transactions_user_account ON public.transactions (user_id, account_id)`.
10. `CREATE INDEX idx_transactions_source_file ON public.transactions (source_file_id)`.

No data migration. The tables are created empty; the upload service backfills `accounts` lazily via `get_or_create_default_account` per ADR-0014.

### `downgrade()` (reverse order)

1. `DROP INDEX idx_transactions_source_file`.
2. `DROP INDEX idx_transactions_user_account`.
3. `DROP INDEX idx_transactions_user_category`.
4. `DROP INDEX idx_transactions_user_date`.
5. `DROP TABLE public.transactions`.
6. `DROP INDEX idx_uploads_account_id`.
7. `DROP INDEX idx_uploads_user_id`.
8. `DROP TABLE public.uploads`.
9. `DROP INDEX idx_accounts_user_id`.
10. `DROP TABLE public.accounts`.

`DROP TABLE` removes the table's implicit indexes (those backing `UNIQUE` and `PRIMARY KEY`); only the explicitly named `CREATE INDEX` indexes need explicit `DROP INDEX`.

## Indexes for the read API

The composite indexes shipping in this migration are sized to the three queries ADR-0017 (the read API ADR) will pin. They are deliberately the minimum set required by the read API plus the cascade-driven reverse lookup on `source_file_id`. No speculative indexes.

| Query pattern | Index used |
|---|---|
| `WHERE user_id = ? AND date BETWEEN ? AND ? ORDER BY date DESC` | `idx_transactions_user_date` |
| `WHERE user_id = ? AND category_id = ?` (and `category_id IS NULL`) | `idx_transactions_user_category` |
| `WHERE user_id = ? AND account_id = ?` | `idx_transactions_user_account` |
| `WHERE user_id = ? AND fingerprint = ?` (dedup conflict check) | implicit index from `UNIQUE (user_id, fingerprint)` |
| `WHERE source_file_id = ?` (reverse lookup, cascade) | `idx_transactions_source_file` |
| `WHERE user_id = ? AND file_hash = ?` (dedup short-circuit) | implicit index from `UNIQUE (user_id, file_hash)` |

Aggregation indexes for ADR-0017's `get_spend_by_category` and `get_spend_history` are **explicitly deferred** to Phase 3c per the roadmap ("ensure these methods are index-friendly; add covering indexes if benchmarks warrant"). Adding them now is speculative.

## PII handling per table

| Table | What is stored | Sensitivity | Retention |
|---|---|---|---|
| `public.accounts` | User-defined account labels and kind; currency code | Low — labels only, no PAN/account-number | Lifetime of user account; cascade on delete |
| `public.uploads` | Original filename, SHA-256 of file bytes, row count, upload timestamp | Medium — filename may contain PII (e.g., `"jane_doe_chequing_2026-04.csv"`); file_hash is derived from PII | Lifetime of user account; cascade on delete |
| `public.transactions` | Date, original description, signed amount, category assignment, SHA-256 fingerprint | High — raw transaction descriptions are merchant data, amounts are financial data | Lifetime of user account; cascade on delete |

PII in logs is scrubbed per the Phase 0 logging configuration. The transaction `description` column stores the original verbatim string; the normalized form used in the fingerprint canonicalization is computed in memory and **not persisted** (per ADR-0013). The fingerprint and file_hash are one-way digests but should still be treated as PII for log-scrubbing purposes.

## Consequences

- **Positive:** Phase 3a's entire schema lands in one atomic, reviewable boundary. Rollback is trivial because no data exists yet.
- **Positive:** All four constraints from ADRs 0013/0014/0015 land together — there is no intermediate state where, e.g., `uploads` exists without its `UNIQUE (user_id, file_hash)` or where `transactions.account_id` is nullable.
- **Positive:** The composite indexes match the planned read API. The dedup constraints' implicit indexes do double duty as access-path indexes.
- **Positive:** `category_id ON DELETE SET NULL` preserves spend history when a user deletes a category mid-life — the only acceptable behavior for a finance tool.
- **Negative:** A single migration file is longer than three small ones. Tradeoff accepted because the three tables are a cohesive slice.
- **Negative:** `CHECK (octet_length(...) = 32)` is defensive and slightly redundant with `BYTEA`'s lack of length enforcement, but it catches encoding bugs early. The runtime cost is negligible.
- **Follow-up:** The implementation agent authoring revision `0003_transactions_uploads_accounts` is the single writer for this migration per ADR-0007. The other Phase 3a agents work against this contract, not against the migration file.
- **Follow-up:** ADR-0017 (Transaction Engine read API) will pin `get_transactions` and `get_transaction` against this schema. Aggregation methods and any covering indexes they require are deferred to Phase 3c per the roadmap.
- **Follow-up:** Verify that the existing `public.categories` table from revision 0002 declares `ON DELETE CASCADE` on its `user_id` FK (per ADR-0015's follow-up). If not, this migration also fixes it; otherwise the fix is a separate revision.
- **Follow-up:** Status is **Proposed** until human review confirms the schema. This ADR consolidates three already-Proposed ADRs and inherits their review requirement — it cannot move to Accepted before 0013, 0014, and 0015 do.
