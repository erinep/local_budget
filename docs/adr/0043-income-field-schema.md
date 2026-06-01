# ADR 0043 - Income Field Schema and Ownership

- **Status:** Accepted
- **Date:** 2026-05-31
- **Phase:** P5e
- **Deciders:** architect

## Context

Phase 5e introduces an income-driven allocation model: the user enters a monthly income figure and all budget targets are expressed both as a percentage of that income and as a dollar amount. The income value is used exclusively by the Budgeting Module — no other module reads it today. However, architecture.md defines Account Settings as the owner of "user preferences," and a monthly income figure is arguably a preference.

The question is where the income field lives in the schema, which module's service layer writes and reads it, and whether the other module must therefore call across a service boundary. A secondary question is whether to accept income as a monthly figure, an annual figure, or both.

Binding constraints:
- [ADR-0003](0003-module-communication-service-layer-only.md) — no module reaches into another's tables directly. If income lives in Account Settings, Budgeting must call the Account Settings service API to read it.
- [ADR-0007](0007-schema-migration-tooling.md) — every schema change goes through Alembic. The income field requires a migration regardless of where it lands.
- [ADR-0009](0009-account-settings-schema-normalization.md) — Account Settings already owns `public.categories` and `public.category_keywords`. A `public.user_settings` table in that module is a natural extension point.
- [ADR-0026](0026-budgets-global-targets.md) — `public.budgets` carries `amount NUMERIC(12,2)` per category. The income field must coexist with this schema.
- Relevant risk: "Schema design locks in early mistakes" (P1+, High) from [risks.md](../risks.md).

## Options considered

### Option A - Income in Account Settings (`public.user_settings`)

Introduce a new `public.user_settings` table owned by Account Settings, with a `monthly_income` column. The Budgeting Module reads income via `account_settings.services.get_user_settings(user_id)`.

Pros:
- Consistent with the stated charter: Account Settings owns user preferences. Income ceiling is a preference, not a budget target.
- A `user_settings` table has obvious future uses (locale, currency, notification preferences) that do not belong to Budgeting. Creating it now at the correct layer avoids a later migration into a different module.
- The cross-module call is a trivial service read (one row, one column) and already follows the ADR-0003 pattern used by the Transaction Engine.

Cons:
- Budgeting must import from `account_settings.services` at runtime, adding a dependency edge between two modules. This edge is documented in architecture.md but does not yet exist in code.
- Any future "bulk update income + allocations in one form submit" must coordinate two service writes across modules, which is more complex than a single write.

### Option B - Income in Budgeting Module (`public.budget_settings`)

Introduce a `public.budget_settings` table owned by the Budgeting Module, with a `monthly_income` column. No cross-module call needed; Budgeting reads and writes income entirely within its own service layer.

Pros:
- Income is only consumed by Budgeting. Placing it there respects "own what you use" and avoids a new inter-module dependency edge.
- Simpler initial implementation: one service layer owns the full allocation workflow (income + targets + percentages).
- No cross-module call in the hot path when the budget page loads.

Cons:
- Income is a personal preference, not a budget artifact. If the user someday wants income visible outside Budgeting (e.g., a net-worth or savings-rate widget in the Intelligence Layer), the field must either be moved or the Intelligence Layer must import from Budgeting specifically for it.
- `public.budget_settings` is a single-row-per-user settings table that conceptually overlaps with what `public.user_settings` would do for Account Settings. Two single-row settings tables across two modules is a maintenance smell.
- Naming `budget_settings` implies the field is a budget configuration, which is technically true but confuses future readers about where to look for general user preferences.

### Option C - Income as a column on `public.budgets` aggregate

Store a single "income budget" sentinel row in `public.budgets` using a reserved `category_id` or a nullable category with a `type` discriminator.

Pros: No new table.

Cons: This is a schema abuse. `public.budgets` has a NOT NULL `category_id` FK and represents category-level targets, not a header record. A sentinel row would break every query that treats all budget rows as comparable targets. Ruled out.

## Decision

We will choose **Option A** — income lives in `public.user_settings`, owned by Account Settings, read by Budgeting via the Account Settings service API.

The two reasons that carried this decision: (1) income is a personal preference that predates any specific budget configuration — it describes the user's financial context, not a budget target, which makes Account Settings the semantically correct owner; (2) `public.user_settings` is the right general-purpose home for per-user preferences and creating it here at the correct layer means every future preference (locale, currency, notification opt-ins) lands in the right place without a later migration.

**Income frequency decision.** Accept monthly income only. The system stores and displays monthly income exclusively. If a user knows only their annual figure, the UI provides a hint ("annual salary ÷ 12") but the stored field is always monthly. Annual-with-auto-conversion adds no data-model value (it is trivial arithmetic the UI can surface inline) and creates a representation question — when both figures are stored, which is canonical after a partial edit?

## Schema

New Alembic migration: `migrations/versions/NNNN_user_settings.py`.

```sql
CREATE TABLE public.user_settings (
    user_id        UUID           NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
    monthly_income NUMERIC(12,2)  CHECK (monthly_income IS NULL OR monthly_income >= 0),
    created_at     TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ    NOT NULL DEFAULT now()
);
```

Notes on the schema:
- `user_id` is both the PK and the FK — one row per user, no surrogate key needed.
- `monthly_income` is nullable. A NULL value means "income not set"; the Budgeting Module treats this as "income-driven allocation unavailable" and falls back to the existing dollar-only budget view.
- `CHECK (monthly_income IS NULL OR monthly_income >= 0)` — permits NULL (not set) but rejects negative values.
- `NUMERIC(12,2)` — consistent with `budgets.amount` (ADR-0026) and `transactions.amount` (ADR-0016).
- `ON DELETE CASCADE` — per [ADR-0015](0015-data-retention-on-account-deletion.md).

## Service API additions (Account Settings)

New functions in `app/account_settings/services.py`:

```python
from dataclasses import dataclass
from decimal import Decimal

@dataclass(frozen=True)
class UserSettings:
    """Per-user preference record."""
    user_id: str
    monthly_income: Decimal | None  # None when not set


def get_user_settings(user_id: str) -> UserSettings:
    """Return the user's settings record.

    Returns a UserSettings with monthly_income=None if no row exists yet.
    Never raises on missing data.
    """
    ...


def upsert_user_settings(
    user_id: str,
    monthly_income: Decimal | None,
) -> UserSettings:
    """Create or update the user's settings record.

    Raises ValueError if monthly_income is not None and monthly_income < 0.
    Uses INSERT ... ON CONFLICT (user_id) DO UPDATE.
    Returns the persisted UserSettings after upsert.
    """
    ...
```

## Cross-module call contract (Budgeting reads income)

The Budgeting Module calls `account_settings.services.get_user_settings(user_id)` to retrieve `monthly_income` when building the allocation view. This is the only Budgeting → Account Settings call. It must remain a service-layer call; Budgeting must never query `public.user_settings` directly.

```python
# In app/budgets/services.py — the only permitted import from account_settings
from app.account_settings.services import get_user_settings
```

## Consequences

- Positive: `public.user_settings` is the correct long-term home for per-user preferences. Future preferences (locale, notifications, currency) are added as nullable columns in one migration, not scattered across module tables.
- Positive: The Account Settings service API is extended with two small, well-scoped functions that follow the existing caching and testing patterns in that module.
- Positive: Budgeting's income fallback (NULL monthly_income → dollar-only mode) means the Phase 4 budget experience is fully preserved for users who never set income.
- Negative: Budgeting now has a runtime import dependency on Account Settings. This dependency must be documented in architecture.md's responsibilities table.
- Negative: The `updated_at` column on `user_settings` is maintained by the application layer (not a trigger), consistent with conventions elsewhere. Implementation must remember to update it on every write.
- Follow-ups required:
  1. Implementation agent authors Alembic migration `NNNN_user_settings.py` under the migration write-lock ([ADR-0007](0007-schema-migration-tooling.md)).
  2. Update `docs/architecture.md` responsibilities table to add `user_settings` to Account Settings' "Owns" column and add the Budgeting → Account Settings read dependency.
  3. Update the cross-module deletion runbook in [ADR-0015](0015-data-retention-on-account-deletion.md) to add `SELECT COUNT(*) FROM public.user_settings WHERE user_id = :uid` to the post-deletion checklist.
  4. The income entry UI lives on the budget page (Phase 5e), not in `/settings` — income is an allocation input, not a background preference. If a future phase adds an income field to the Settings profile page, it should call the same `upsert_user_settings` function.

## Notes

The "income is a preference" vs. "income is a budget input" framing resolves cleanly once you ask: would the Intelligence Layer or a future net-worth module want income? Yes — a savings rate calculation needs income regardless of whether the user has configured any budgets. Placing income in Budgeting would force those future consumers to import from Budgeting, which is architecturally wrong (Intelligence Layer → Budgeting → Account Settings for a field that belongs in Account Settings). Putting it in Account Settings from the start avoids that inversion.
