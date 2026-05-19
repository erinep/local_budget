# ADR 0029 - merchant_aliases Schema

- **Status:** Accepted
- **Date:** 2026-05-18
- **Phase:** P5b
- **Deciders:** Architect agent

## Context

ADR-0028 introduces Tier 2 of the categorizer pipeline: a merchant alias lookup that maps a normalized description to a category with confidence 1.0. That tier requires a database table to persist aliases across sessions and a service function to write them.

Three binding constraints:

- **ADR-0003** (service-layer-only module communication): Account Settings owns `public.categories` and `public.category_keywords`. Any new table that associates data with categories must be written through Account Settings' service interface, not directly from the Transaction Engine.
- **ADR-0005 / ADR-0028**: the categorizer factory receives pre-loaded data; it must not query the database. The alias list is loaded by the caller before the factory is invoked.
- **ADR-0009** (relational normalization): tenant scope is enforced via foreign keys into `public.categories`, which already carries `user_id`. Duplicating `user_id` on a child table would denormalize the schema and create a second enforcement point that could drift.

Relevant risks: "Schema design locks in early mistakes" (P1+, High) from `risks.md`.

## Options considered

### Option A - user_id column on merchant_aliases

`merchant_aliases(id, user_id, category_id, normalized_name)`. Tenant scope is enforced by `user_id` directly; no join to `categories` needed for the lookup query.

**Pros.** Lookup query is a simple `WHERE user_id = :uid` without a join.

**Cons.** `user_id` is redundant: it is already derivable via `category_id → categories.user_id`. Storing it on the child table creates a second enforcement point. If a category is reassigned or the `categories` row's user changes (even hypothetically), the two `user_id` columns can diverge. The denormalization also violates the pattern established in ADR-0009 where `category_keywords` inherits tenant scope from `categories` via FK alone.

### Option B - No separate table; store aliases as a special keyword variant in category_keywords

Add a `is_alias BOOLEAN` flag to `category_keywords`. Tier 2 looks for exact-match keywords flagged as aliases; Tier 4 uses un-flagged keywords.

**Pros.** No new table; existing schema and service functions are extended rather than replaced.

**Cons.** `category_keywords` holds arbitrary substrings; `merchant_aliases` holds fully normalized merchant names. Conflating them in one table with a boolean flag means the Tier 2 lookup (exact-match on normalized description) and the Tier 4 lookup (substring scan) operate on the same column with different semantics. Indexing, normalization rules, and uniqueness constraints differ between the two use cases. A future reader cannot tell by inspection whether a given keyword row is an alias or a scan target.

### Option C - Separate merchant_aliases table, tenant scope via category_id FK

`merchant_aliases(id, category_id, normalized_name, created_at)`. No `user_id` column; tenant scope is inherited via `category_id → categories.user_id`. The Tier 2 lookup joins through `categories` to resolve `user_id`.

**Pros.** Schema is normalized: `user_id` lives in exactly one place per tenant per category. Consistent with `category_keywords` (ADR-0009). The join is a single indexed lookup; pre-loading aliases for a user costs one query per upload, not per transaction.

**Cons.** The pre-load query requires a join. This is a one-time cost per upload, not per-transaction, so the performance impact is negligible.

## Decision

We will choose **Option C — a separate `merchant_aliases` table with tenant scope via `category_id` FK** because it maintains the normalization invariant from ADR-0009 and keeps semantic separation between aliases (exact normalized names) and keywords (substring scan targets).

## Table DDL

Alembic revision `0004_add_merchant_aliases.py`.

```sql
CREATE TABLE public.merchant_aliases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id     UUID NOT NULL REFERENCES public.categories(id) ON DELETE CASCADE,
    normalized_name TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (category_id, normalized_name)
);

CREATE INDEX idx_merchant_aliases_category_id
    ON public.merchant_aliases (category_id);
```

The `UNIQUE (category_id, normalized_name)` constraint prevents duplicate aliases within a category and serves as the conflict-detection point for `add_merchant_alias`. The index on `category_id` covers the join in the pre-load query.

`ON DELETE CASCADE` on `category_id` mirrors the same clause on `category_keywords` (ADR-0009): deleting a category removes its aliases automatically with no orphan risk.

## Tier 2 lookup query pattern

Aliases are pre-loaded once per upload by the caller before the factory is invoked. The pre-load query:

```sql
SELECT ma.normalized_name, c.name AS category_name
FROM public.merchant_aliases ma
JOIN public.categories c ON c.id = ma.category_id
WHERE c.user_id = :user_id
```

The result is passed to `make_categorizer_v2` as the `aliases` parameter (a `list[tuple[str, str]]`). The factory does not issue this query; the caller is responsible for loading it.

## Write path — add_merchant_alias

The single write path for new aliases is `add_merchant_alias` in `app/account_settings/services.py`. This is the Account Settings module's single write authority over category-scoped data (ADR-0003, ADR-0005).

```python
def add_merchant_alias(user_id: str, category_id: str, normalized_name: str) -> None:
    """Write a merchant alias mapping normalized_name to category_id.

    Validates category ownership (same as add_keyword).
    Normalizes normalized_name by calling normalize_description before inserting.
    Conflict on (category_id, normalized_name) is a no-op (already exists).

    Raises:
        ValueError("Category not found")  — category_id does not belong to user_id.
        ValueError("Alias name cannot be empty")  — after normalization.
    """
    ...
```

`add_merchant_alias` imports `normalize_description` from `app.transactions.services` to apply canonical normalization before the insert. This is a one-way import from Account Settings into Transaction Engine's helper function — it does not touch any Transaction Engine table and does not violate ADR-0003.

## Recategorization integration (apply-forward)

After Phase 5b, the `recategorize_transaction` flow (ADR-0018) writes **both** a merchant alias and a keyword when the user checks "apply going forward":

1. `add_keyword(user_id, category_id, keyword)` — existing call, unchanged.
2. `add_merchant_alias(user_id, category_id, normalize_description(raw_desc))` — new call.

The keyword keeps Tier 4 working for similar-but-not-identical descriptions. The alias gives Tier 2 an exact-match shortcut for future identical descriptions. Both calls are made sequentially by `recategorize_transaction` in `app/transactions/services.py`. A conflict on either call is non-fatal and treated as success (same handling as the existing keyword conflict in ADR-0018). A failure on the alias write (for any reason other than conflict) propagates to the caller the same way the keyword write failure does.

## Cold-start seed corpus

New users receive a curated seed `merchant_aliases` corpus populated at account creation so that first-upload accuracy is reasonable before any correction history exists.

The seed corpus is a static JSON fixture at `app/account_settings/seed_merchant_aliases.json`. Format:

```json
[
  {"normalized_name": "TIM HORTONS", "category_name": "Coffee"},
  {"normalized_name": "NETFLIX",     "category_name": "Subscriptions"},
  ...
]
```

`seed_defaults` in `app/account_settings/services.py` is extended to populate `merchant_aliases` from this file after seeding categories. The seed is applied only when the user has no aliases yet (same guard as the existing category seed). Category rows must exist before aliases are inserted; `seed_defaults` ensures this ordering.

The seed fixture is maintained by hand. It is not automatically generated or updated; an engineer adds or removes entries when real-world accuracy data suggests a change.

## Migration

Alembic revision `0004_add_merchant_aliases.py`.

- `upgrade()`: creates `public.merchant_aliases` and `idx_merchant_aliases_category_id`.
- `downgrade()`: drops the index and table. No data migration needed (table is new; no existing rows to preserve or transform).

The migration write-lock (ADR-0007) applies. Only one agent authors this migration file.

## Consequences

- **Positive.** Schema is normalized: tenant scope is enforced via FK, not a redundant `user_id` column.
- **Positive.** Aliases are semantically distinct from keywords: separate table, separate normalization rule, separate uniqueness constraint.
- **Positive.** Cold-start seed gives reasonable Tier 2 accuracy for new users before any correction history exists.
- **Positive.** `ON DELETE CASCADE` on `category_id` makes category deletion safe with no orphan alias risk.
- **Negative.** The pre-load query requires a join through `categories`. This is one query per upload, not per transaction, so the impact is negligible.
- **Negative.** `add_merchant_alias` imports `normalize_description` from Transaction Engine. This is a deliberate narrow dependency on a pure helper function, not on any table or connection. Reviewers should flag any attempt to broaden this import.
- **Follow-up required.** `seed_defaults` must be extended in the same Phase 5b implementation slice that adds `add_merchant_alias`. The two changes ship together.
- **Follow-up required.** `recategorize_transaction` (ADR-0018) must be updated to call `add_merchant_alias` in its apply-forward path. This extends the function's specification; it does not change its signature or error model.
- **Follow-up required.** The migration write-lock (ADR-0007): one agent authors `0004_add_merchant_aliases.py`.

## Notes

The `normalized_name` column stores the output of `normalize_description`, not the raw transaction description. This means a given merchant maps to exactly one alias string regardless of which transaction triggered the write. If `normalize_description` changes in a future phase, existing aliases are not automatically migrated; a one-time data migration would be needed. This is an acceptable deferred cost given that normalization rules are expected to be stable once established.
