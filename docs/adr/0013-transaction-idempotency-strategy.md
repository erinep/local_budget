---
adr: 0013
title: Transaction Idempotency Strategy — Two-Layer Hash
status: Accepted
date: 2026-05-17
phase: P3a
deciders: erin
---

## Context

Phase 3a moves the Transaction Engine from in-memory upload processing to a persisted `transactions` table. Both the [roadmap](../roadmap.md#phase-3a--persistence-2-weeks) and the [architecture](../architecture.md#transaction-engine) call out the same hard requirement: *re-uploading the same CSV must not double-count*. This ADR fixes the strategy that enforces that requirement at the database layer.

The naive ideas — a `UNIQUE (user_id, date, description, amount)` constraint, or a file-level hash on the upload — each fail in a realistic case:

- **Composite natural key only** silently destroys genuine same-day duplicate transactions (two $5 coffees on the same day at the same merchant collapse to one row).
- **File-level hash only** does nothing when a user re-exports a longer date range from their bank that overlaps the previously uploaded range — the second file is not byte-identical but most of its rows are duplicates.

This decision interacts directly with [ADR-0014](0014-multi-account-per-user.md) (multi-account-per-user) — the dedup namespace must include `account_id` so identical date/amount/description on two different financial sources do not collide as false-positive duplicates.

Relevant risks: "Schema design locks in early mistakes" (High) and "Silent data loss from over-eager dedup" (implicit in the categorization-feedback theme) in [risks.md](../risks.md).

## Options considered

### Option A — Composite natural key on `(user_id, date, description, amount)`

`UNIQUE (user_id, date, description, amount)` on `transactions`. Re-uploads use `ON CONFLICT DO NOTHING`.

**Pros:** Simplest schema. No hash columns. Constraint is human-readable.

**Cons:** Silently collapses two real same-day same-merchant transactions of the same amount into one row. This is not a corner case — coffee, transit, and small repeat purchases regularly produce this pattern. Once the row is lost on insert, it cannot be recovered without re-parsing the original CSV. Unacceptable for a finance tool.

### Option B — File-level hash only

`uploads.file_hash` SHA-256 over the raw upload bytes; `UNIQUE (user_id, file_hash)`. Reject re-uploads where the hash already exists; otherwise insert every row of the new file.

**Pros:** Easy to implement. Clear user-facing message ("this file was already uploaded on YYYY-MM-DD").

**Cons:** Defeated by the most common real re-upload pattern — exporting a wider or shifted date range from a bank's web UI produces a different file with overlapping rows. The non-identical bytes pass the file hash check; the overlapping rows then double-count.

### Option C — Row-level hash only

`transactions.fingerprint` SHA-256 over a canonical tuple per row; `UNIQUE (user_id, fingerprint)`; `ON CONFLICT DO NOTHING` on insert.

**Pros:** Handles overlapping re-uploads correctly. Same-day duplicates can be disambiguated by including a per-file sequence number in the tuple.

**Cons:** A byte-identical re-upload still parses the entire CSV before the database short-circuits each row. For large files this is wasted work. No fast path for the "I clicked upload twice" case, and the user-facing message ("0 new transactions") is muddier than "this file was already uploaded."

### Option D — Two-layer hash (file-level + row-level)

Both: `uploads.file_hash` short-circuits byte-identical re-uploads before parsing; `transactions.fingerprint` handles the realistic overlapping-export case row by row.

**Pros:** Each layer covers the case the other misses. Cheap byte-identical short-circuit; correct dedup on partial overlap. Both columns are deterministic, indexable, and FK-safe.

**Cons:** Two hash columns to maintain. Canonicalization rules become part of the schema contract — changing them later requires a backfill. Slightly more code than a single-layer approach.

## Decision

We will choose **Option D — a two-layer hash**. The two reasons that carried the decision: (1) Option C alone is technically sufficient but wastes parse work on the common "double-click upload" case, and (2) the file-level layer gives the user a clear, specific error message ("you already uploaded this file") that the row-level layer cannot produce on its own.

## Schema implications

### `public.uploads`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY, DEFAULT gen_random_uuid() |
| user_id | UUID | NOT NULL, FK → auth.users(id) ON DELETE CASCADE |
| account_id | UUID | NOT NULL, FK → accounts(id) ON DELETE CASCADE |
| filename | TEXT | NOT NULL |
| file_hash | BYTEA | NOT NULL (SHA-256, 32 bytes) |
| row_count | INTEGER | NOT NULL |
| uploaded_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() |

Constraints:
- `UNIQUE (user_id, file_hash)` — byte-identical re-upload short-circuits before parsing.

### `public.transactions`

The fingerprint column and its constraint:

| Column | Type | Constraints |
|---|---|---|
| fingerprint | BYTEA | NOT NULL (SHA-256, 32 bytes) |

- `UNIQUE (user_id, fingerprint)` — row-level dedup across overlapping uploads.
- Inserts use `INSERT … ON CONFLICT (user_id, fingerprint) DO NOTHING` so partial overlaps drop only the duplicate rows, not the upload.

## Canonicalization rule

The fingerprint is `SHA-256(tuple)` where `tuple` is the concatenation of the following fields joined by the ASCII Unit Separator (`\x1f`, byte `0x1F`):

1. `user_id` — UUID, lowercase canonical string form.
2. `account_id` — UUID, lowercase canonical string form. (See [ADR-0014](0014-multi-account-per-user.md).)
3. `iso_date_utc` — transaction date as `YYYY-MM-DD` in UTC.
4. `description_normalized` — original description after `strip → collapse internal whitespace to single space → casefold()`. **Not persisted on the row** — the original description is preserved verbatim in its own column.
5. `amount_signed_2dp` — signed decimal amount to 2 decimal places, e.g. `-12.50` or `100.00`. Sign included so a $50 debit and a $50 credit on the same day do not collide.
6. `within_file_seq` — 0-indexed counter incremented per `(date, description_normalized, amount_signed_2dp)` group within a single CSV file. Preserves genuine same-day duplicates. Computed by the parser before insert; not persisted.

`source_file_id` is **deliberately excluded** from the tuple so that the same row appearing in two different CSV exports collapses to one stored transaction (which is the entire point of the row-level layer).

Changing any element of this canonicalization rule is a schema change and requires a follow-up ADR plus a fingerprint backfill migration.

## PII handling

`uploads.file_hash` and `transactions.fingerprint` are one-way hashes that do not reveal the underlying transaction content, but they are derived from PII and should be treated as such for log scrubbing purposes. Retention: lifetime of the parent row; cascade on user deletion per [ADR-0015](0015-data-retention-on-account-deletion.md).

## Consequences

- **Positive:** Byte-identical re-uploads short-circuit before parsing, with a clear user-facing message.
- **Positive:** Overlapping CSV exports (the common case) dedupe correctly at the row level.
- **Positive:** Same-day duplicate transactions are preserved.
- **Positive:** Same-day same-amount on different accounts do not collide (account_id is in the tuple).
- **Negative:** Two hash columns and a canonicalization rule become part of the schema contract. Changing the rule later requires a backfill.
- **Negative:** The `within_file_seq` field is parser state, not row state. The parser implementation must compute it deterministically; tests should pin the ordering rule.
- **Follow-up:** The Phase 3a schema migration is the single-writer surface and authors both the `uploads` and `transactions` tables. The migration agent owns both hash columns.
- **Follow-up:** The upload service emits a structured event when a re-upload is short-circuited at the file layer vs. when row-level conflicts occur. This is needed for observability and for future user-facing UI in Phase 3b.
- **Follow-up:** Status is **Proposed** until human review confirms the canonicalization rule. The rule directly determines whether legitimate user spend can be silently dropped, and is the kind of decision worth a second pair of eyes.
