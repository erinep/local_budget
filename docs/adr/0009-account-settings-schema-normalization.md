---
adr: 0009
title: Account Settings Schema Normalization — JSONB to Relational Tables
status: Accepted
date: 2026-05-16
deciders: architect agent
---

## Context

Phase 1 (ADR-0007) introduced `public.custom_categories`, which stores a per-user category map as a single JSONB blob (`{category_name: [keyword, ...]}`) with a UNIQUE constraint on `user_id`. This was sufficient for Phase 1's goal of persisting the map between sessions.

Phase 2 requires a CRUD UI so users can add, rename, and delete individual categories and keywords. Operating on JSONB blobs for single-item edits is awkward: every mutation must deserialize the entire blob, modify it in Python, and re-serialize. It also prevents the database from enforcing uniqueness or referential integrity at the row level.

The [Phase 2 roadmap item](../roadmap.md#phase-2--account-settings-service-1-2-weeks) explicitly calls for `categories (id, user_id, name)` and `category_keywords (id, category_id, keyword)` as the target schema. This ADR decides how to get from the current JSONB schema to those relational tables and what constraints and indexes the new tables carry.

Relevant risks: "Schema design locks in early mistakes" (P1+, High) and "Data loss during a migration cutover" (P1+, Very High) from [risks.md](../risks.md).

## Options considered

### Option A — Keep custom_categories and add new tables alongside it

Add `categories` and `category_keywords` alongside `custom_categories`. The service layer reads from the new tables but keeps `custom_categories` as a fallback. A background job or lazy migration moves data on next login.

**Pros:** No destructive migration; rollback is easy since the old table is intact.

**Cons:** Two sources of truth for category data. The service layer must handle "which table is authoritative?" on every read, which creates a class of subtle bugs. The old table's JSONB constraint (`user_id UNIQUE`) diverges from the new tables' normalization. Testing doubles in complexity. This complexity is permanent until the old table is dropped, and dropping it later requires the same data-migration step anyway.

### Option B — Drop custom_categories, replace with new relational tables in a single migration

One migration: (1) create `categories` and `category_keywords`, (2) copy data from `custom_categories.category_map` JSONB into the new tables using a PL/pgSQL data migration block, (3) drop `custom_categories`. The downgrade reverses the steps.

**Pros:** Single source of truth immediately. Service layer is clean. No fallback logic. The schema matches the roadmap target from day one of Phase 2.

**Cons:** The data migration step is irreversible without the downgrade path. The downgrade must re-serialize rows from `categories`/`category_keywords` back into JSONB form — this is expressible but slightly complex. A migration failure mid-flight leaves the database in a partial state, which is mitigated by running the entire migration inside a transaction (Postgres supports transactional DDL).

**Consequences of choosing B:** Every Phase 2 agent writes against the new schema from the start. The old `custom_categories` table and the `save_category_map`/`get_category_map` implementations are replaced (not supplemented) in this phase.

### Option C — Drop custom_categories, use two migrations (structure, then data)

Split the migration into two Alembic revisions: revision 0002 creates the new tables; revision 0003 performs the data migration and drops `custom_categories`.

**Pros:** Each migration is smaller and easier to reason about independently.

**Cons:** Between revisions 0002 and 0003, the database is in an inconsistent state (both schemas exist, neither is fully authoritative). If a deploy runs only 0002 before crashing, the app must handle the partial state. For a project at this scale this adds complexity without meaningful benefit — the same transactional guarantees are available in a single migration revision.

## Decision

We will choose **Option B** — a single Alembic migration revision that creates the new tables, migrates JSONB data into them, and drops `custom_categories`. The entire migration runs inside a transaction so any failure rolls back atomically.

The two reasons that carried this decision: (1) a single authoritative schema is simpler to reason about and test than two parallel representations, and (2) Postgres transactional DDL makes a mid-flight failure safe — either the whole migration applies or nothing changes.

## Migration sequence (revision 0002)

The migration file `migrations/versions/0002_normalize_categories.py` must implement the following steps in order inside `upgrade()`, wrapped in a single transaction:

**Step 1 — Create `public.categories`**

```sql
CREATE TABLE public.categories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

CREATE INDEX idx_categories_user_id
    ON public.categories (user_id);
```

**Step 2 — Create `public.category_keywords`**

```sql
CREATE TABLE public.category_keywords (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id UUID NOT NULL REFERENCES public.categories(id) ON DELETE CASCADE,
    keyword     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (category_id, keyword)
);

CREATE INDEX idx_category_keywords_category_id
    ON public.category_keywords (category_id);
```

**Step 3 — Data migration from JSONB**

Iterate over every row in `custom_categories`. For each `(user_id, category_map)` pair, for each `(category_name, keywords_list)` entry in the JSONB, insert a row into `categories` and insert one row per keyword into `category_keywords`.

This is expressible as a PL/pgSQL block or as Python within the Alembic migration using `conn.execute()`. The Python approach is recommended because it avoids dialect-specific PL/pgSQL and integrates naturally with Alembic's connection object.

Duplicate keyword entries within a single category in the JSONB blob (which the old schema did not prevent) must be deduplicated before insertion to satisfy the `UNIQUE (category_id, keyword)` constraint. Use a `ON CONFLICT DO NOTHING` clause or deduplicate in Python before inserting.

**Step 4 — Drop `public.custom_categories`**

```sql
DROP INDEX public.idx_custom_categories_user_id;
DROP TABLE public.custom_categories;
```

**downgrade() sequence (reverse order):**

1. Recreate `public.custom_categories` with its original structure and index.
2. Re-serialize each user's categories and keywords back into JSONB and insert into `custom_categories`.
3. Drop indexes on `category_keywords` and `categories`.
4. Drop `public.category_keywords`.
5. Drop `public.categories`.

## Schema constraints and indexes

### `public.categories`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY, DEFAULT gen_random_uuid() |
| user_id | UUID | NOT NULL |
| name | TEXT | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() |

Constraints:
- `UNIQUE (user_id, name)` — prevents duplicate category names per user. Case-sensitivity is preserved at the database level; the service layer normalizes names (strip, collapse whitespace) before insert/lookup.

Indexes:
- `idx_categories_user_id ON categories (user_id)` — covers the primary access pattern `SELECT * FROM categories WHERE user_id = ?`.
- The `UNIQUE (user_id, name)` constraint creates an implicit index on `(user_id, name)` which also satisfies the `WHERE user_id = ? AND name = ?` conflict-check pattern.

### `public.category_keywords`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY, DEFAULT gen_random_uuid() |
| category_id | UUID | NOT NULL, FK → categories(id) ON DELETE CASCADE |
| keyword | TEXT | NOT NULL |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() |

Constraints:
- `UNIQUE (category_id, keyword)` — prevents duplicate keywords within a category. Case-sensitivity preserved at DB level; service layer normalizes keywords (strip, lowercase) before insert/lookup.
- `ON DELETE CASCADE` on `category_id` — deleting a category removes its keywords automatically. No orphaned keyword rows.

Indexes:
- `idx_category_keywords_category_id ON category_keywords (category_id)` — covers `SELECT * FROM category_keywords WHERE category_id = ?`.
- The `UNIQUE (category_id, keyword)` constraint creates an implicit index on `(category_id, keyword)`.

## PII handling

`categories.name` and `category_keywords.keyword` contain user-defined labels and merchant keywords. These are user-generated configuration data, not raw transaction descriptions. Retention: lives as long as the user account. Deletion of a user's account must cascade to all rows in both tables (add to the cross-module deletion runbook when it is written in Phase 3a).

## Consequences

- **Positive:** Single source of truth for category data. No dual-schema fallback logic.
- **Positive:** Database enforces uniqueness and referential integrity. Duplicate detection moves from Python to the DB constraint layer.
- **Positive:** `ON DELETE CASCADE` on keywords makes category deletion a single-statement operation with no orphan risk.
- **Negative:** The downgrade is more complex than a typical DDL-only downgrade; it requires re-serializing relational rows back to JSONB. This is acceptable because downgrades in production are rare and the downgrade is documented and testable.
- **Follow-up:** The implementation agent must update `app/account_settings/services.py` to read from the new tables. The `get_category_map` and `save_category_map` functions must be reimplemented against `categories` and `category_keywords` (not modified in-place to hit both old and new tables).
- **Follow-up:** The `_SEED_FILE` fallback path in services.py (`custom_categories.json`) is deprecated in Phase 2. The `seed_defaults` service function replaces it.
- **Follow-up:** The migration write-lock (ADR-0007) applies. Only the backend CRUD agent authors this migration file. The other Phase 2 agents work against the contract, not the migration.
