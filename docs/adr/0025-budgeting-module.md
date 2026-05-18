---
adr: 0025
title: Budgeting Module — Schema, Service API, and Route Design
status: Partially superseded by ADR-0026 (Decisions 1 and 2)
date: 2026-05-18
phase: P4
deciders: erin
---

## Context

Phase 4 adds the Budgeting Module: a first-class module that lets a user set monthly spending targets per category and track actuals against them. The roadmap stub is `budgets (id, user_id, category_id, amount, period, start_date)`; this ADR pins every concrete design decision before implementation begins.

Binding constraints from prior ADRs:

- [ADR-0003](0003-module-communication-service-layer-only.md) — the Budgeting Module reads actuals **only** through the Transaction Engine service layer. No direct access to the `transactions` table.
- [ADR-0001](0001-utc-timestamps.md) — all timestamps UTC.
- [ADR-0015](0015-data-retention-on-account-deletion.md) — `public.budgets` must FK to `auth.users(id) ON DELETE CASCADE`. ADR-0015 names `budgets` explicitly as a forward-looking P4 table.
- [ADR-0023](0023-aggregation-api.md) — `get_spend_by_category(user_id, period: DateRange)` and `get_spend_history(user_id, category_id, periods)` are the only actuals surface available to this module.
- [ADR-0016](0016-transactions-uploads-accounts-schema.md) — schema conventions to follow: UUID PKs defaulting to `gen_random_uuid()`, `TIMESTAMPTZ` defaulting to `now()`, `NUMERIC(12,2)` for monetary amounts, `BYTEA` for hashes.

Relevant risks:
- "Schema design locks in early mistakes" (P1+, High) — the schema must be usable for the real feature set without premature generalization.
- "Cross-module API contract drift" (P3a+, High) — the Budgeting Module's own service API is consumed by the Intelligence Layer in Phase 5; it must be stable and documented before Phase 4 implementation begins.
- "Read API performance degrades with history size" (P3a, P3c, P4+, Medium) — the actual-vs-budget computation calls into the Transaction Engine on every page load; the path must be index-friendly.

## Decisions

### Decision 1 — Schema: period granularity

**Question.** Should the schema support arbitrary period granularities (weekly, quarterly, annual) now, or only monthly?

#### Option A — Monthly-only, strictly typed

`period` is not a column. Instead, `year` (SMALLINT) and `month` (SMALLINT, 1–12) are stored separately. The table carries an implicit "this is a monthly budget" meaning.

Pros: No type column to forget. The pair `(year, month)` is unambiguous — callers cannot express a partial month. Constraint enforcement is trivial: `CHECK (month BETWEEN 1 AND 12)`. Matches how `DateRange.for_month(year, month)` is called by Phase 4's only consumer.

Cons: Cannot represent yearly or quarterly targets without a new table or schema change. Storing `(year, month)` instead of a `DATE` makes range comparisons (`WHERE year > 2026 OR (year = 2026 AND month >= 3)`) awkward and non-index-friendly compared to a DATE column.

#### Option B — Period type column with monthly as the only supported value now

A `period_type TEXT` column defaulting to `'monthly'` (with a CHECK constraint) plus a `DATE` column named `period_start` (first day of the relevant period). The pair encodes the period unambiguously. Other values (`'weekly'`, `'quarterly'`, `'annual'`) are reserved by the CHECK constraint and can be unlocked by a new ADR without a schema change.

Pros: The schema is extensible without a migration. `period_start` as a DATE indexes cleanly. Adding yearly budgets later requires an ADR and a UI change — the schema already accommodates it.

Cons: `period_type` adds a column that has only one live value for the entire Phase 4 lifetime. The NOT NULL check on type must be kept in sync with every query that constructs `DateRange`s from these rows.

#### Option C — Period as a date range (start + end columns)

Two DATE columns, `period_start` and `period_end`. Any granularity is representable.

Pros: Maximum flexibility.

Cons: A monthly budget for May 2026 could be represented as `(2026-05-01, 2026-05-31)` or `(2026-05-01, 2026-05-30)` (off-by-one on end-inclusive vs. exclusive). Callers that construct the DateRange for `get_spend_by_category` must derive end dates from these columns; any inconsistency silently miscounts. The UNIQUE constraint becomes harder to express — how do you prevent two overlapping date ranges for the same category?

**Decision: Option A — monthly-only, stored as `(budget_year SMALLINT, budget_month SMALLINT)`.**

The two reasons: (1) the roadmap scope is monthly budgets for Phase 4, and Phase 5 has no requirement for other periods — extending now is speculative generalization; (2) a `(year, month)` pair maps directly to `DateRange.for_month(year, month)` with no lossy conversion and no off-by-one risk. If non-monthly periods are ever needed, a new ADR will address the schema extension.

---

### Decision 2 — Schema: one budget per category per month, or multiple

**Question.** Can a user have more than one budget entry for the same (category, month) pair — for example, a "base" and a "stretch" target?

**Decision: one budget per category per month.** A UNIQUE constraint on `(user_id, category_id, budget_year, budget_month)` enforces this. Seasonal overrides (e.g., December grocery budget is higher) are expressed by setting different `amount` values for different months — not by creating a second row for the same month. This is simple and matches the mental model of a monthly budget.

`category_id` is non-nullable. A "total spend" budget is not supported in Phase 4. The Intelligence Layer's alerting in Phase 5 can compute a total from the sum of all category budgets if needed.

---

### Decision 3 — Schema: `start_date` semantics and effective date range

The roadmap stub names `start_date`. In a system where each budget row represents a specific `(year, month)`, `start_date` is redundant — the effective date is fully encoded by `(budget_year, budget_month)`. However, `created_at` and `updated_at` audit columns are useful for debugging and ordering.

**Decision: drop `start_date`; add `created_at` and `updated_at` audit columns.** `created_at` is `TIMESTAMPTZ NOT NULL DEFAULT now()`. `updated_at` is `TIMESTAMPTZ NOT NULL DEFAULT now()` and is maintained via an application-layer update (not a trigger, consistent with conventions elsewhere in the codebase). There is no `end_date` — a budget is permanently in effect for its `(year, month)` unless the row is deleted.

---

### Decision 4 — Schema: deletion semantics (hard delete vs soft delete)

**Decision: hard delete.** Consistent with [ADR-0015](0015-data-retention-on-account-deletion.md)'s principle of minimal retention. A user who removes a budget target has expressed intent to discard it. There is no "undo" for budget deletion (consistent with the no-recovery posture on account deletion). The cascade on `auth.users(id)` handles bulk purge on account deletion.

No `deleted_at` column. Soft-delete was explicitly rejected in ADR-0015 for the same reasons that apply here.

---

### Decision 5 — Monetary amount precision

**Decision: `NUMERIC(12,2)`.** Consistent with `transactions.amount` in ADR-0016. Budget amounts are user-entered and never more precise than cents. The upper bound of 10 digits before the decimal (up to 9,999,999,999.99) is more than sufficient for a personal finance app.

---

### Decision 6 — Computation ownership for actual-vs-budget

**Question.** Who computes the variance between a budget target and the actual spend?

#### Option A — Inline in the route handler

The route handler calls `get_budget_rows(user_id, year, month)` to get budget targets and `get_spend_by_category(user_id, period)` to get actuals, then zips them together.

Pros: Simple. No extra service function. Variance logic is small (subtraction and a ratio).

Cons: The zipping logic (matching by `category_id`, handling categories with a budget but no spend, and categories with spend but no budget) is non-trivial. If it lives in the route handler it is hard to test and hard to reuse for the Intelligence Layer in Phase 5.

#### Option B — Dedicated `get_budget_progress` function in the Budgeting service layer

A single function `get_budget_progress(user_id, year, month) -> list[BudgetProgress]` encapsulates both calls and the join. Returns a typed list that callers (both the route handler and the Phase 5 Intelligence Layer) consume directly.

Pros: Testable independently of routes. Reusable by Phase 5. The join logic (including the "no spend" and "no budget" sentinel cases) is tested once at the service layer, not once per consumer. Consistent with the ADR-0003 principle that modules expose clean service-layer interfaces.

Cons: One more function in the service module.

#### Option C — Database view or materialized view

A Postgres view joins `budgets` with the transaction aggregates directly in the database.

Pros: Single query, no N+1.

Cons: ADR-0003 prohibits cross-module table access. A DB view joining `budgets` with `transactions` violates the module boundary — `transactions` belongs to the Transaction Engine and the Budgeting Module must not query it, even through a view. Materialized views add refresh complexity. This option is ruled out by ADR-0003.

**Decision: Option B — `get_budget_progress` in the Budgeting Module service layer.** The two reasons: (1) the join logic is non-trivial enough to warrant a testable abstraction; (2) Phase 5 will call this function directly, making the service-layer boundary useful immediately, not just hypothetically.

---

### Decision 7 — "Propose a budget" design

**Question.** How does the budget proposal feature work?

- **Look-back window:** 3 calendar months of complete data preceding the current month. If fewer than 2 complete months of data exist, proposals are still generated (the average of however many months are available) with a UI note that the estimate is based on limited history.
- **Method:** For each category that has any spend in the look-back window, compute `round(average_monthly_spend, 0)` as the proposed target. Categories with zero spend across all look-back months are omitted from the proposal.
- **Re-runnable:** The feature can be re-run at any time. By default it fills only gaps — categories that already have a budget for the target month are not overwritten. A "replace all" checkbox (or a separate route) allows overwriting existing budgets.
- **Implementation:** The proposal calls `get_spend_history(user_id, category_id, periods)` for each category across the 3-month look-back window, computes the average, and writes the result to `public.budgets` via the Budgeting Module's own write path. It does not call any Transaction Engine write functions.
- **Atomicity:** The proposal upsert runs in a single database transaction. Either all proposed budgets land or none do (no partial proposals).

The look-back window is a module-level constant (`PROPOSAL_LOOKBACK_MONTHS = 3`), not a user setting. It can be changed by editing the constant and writing a new ADR only if the default becomes structurally wrong.

---

### Decision 8 — Progress indicator thresholds

Three states: under budget, near limit, over budget. Named in code as `BudgetStatus` with values `UNDER`, `NEAR`, `OVER`.

**Decision: `UNDER` when spend < 80% of target; `NEAR` when 80% <= spend <= 100%; `OVER` when spend > 100%.** These are global constants in the Budgeting Module, not per-user settings. This is a personal finance app for one user; per-user threshold configuration is complexity that adds no meaningful value at this scale.

```python
NEAR_LIMIT_THRESHOLD = Decimal("0.80")   # spend / budget >= this → NEAR
OVER_BUDGET_THRESHOLD = Decimal("1.00")  # spend / budget >  this → OVER
```

If `budget.amount == 0`, the status is always `OVER` (any spend exceeds a zero-dollar target) — this prevents a divide-by-zero and matches the user's intent.

---

### Decision 9 — Blueprint and URL structure

**Decision: Blueprint prefix `/budgets`, registered in the app factory consistent with [ADR-0004](0004-flask-blueprint-layout.md).**

The actual-vs-budget view is the **default landing page** for the Budgeting Module — this is what users will visit most. Budget configuration (setting targets) is a secondary action reachable from the progress view.

Route table:

| Method | URL | Handler | Description |
|---|---|---|---|
| GET | `/budgets/` | `budget_progress` | Actual-vs-budget view, defaults to current month |
| GET | `/budgets/?year=YYYY&month=MM` | `budget_progress` | Actual-vs-budget view for a specified month |
| GET | `/budgets/configure` | `configure_budgets` | List all budgets for current month; form to add/edit |
| POST | `/budgets/configure` | `save_budget` | Create or update a single budget entry |
| POST | `/budgets/<uuid:budget_id>/delete` | `delete_budget` | Hard delete a budget row |
| GET | `/budgets/propose` | `propose_budget_preview` | Preview proposed budgets before applying |
| POST | `/budgets/propose` | `apply_proposed_budgets` | Write proposed budgets (gaps-only or replace-all) |

Notes:
- Period navigation (previous/next month) is handled by the client rendering links with `?year=YYYY&month=MM`.
- The default period when no query params are provided is the **current calendar month** (year and month derived from `date.today()` in UTC per ADR-0001). If the current month has no transactions yet (early in the month), the progress view shows zero actuals against whatever targets exist — this is correct behavior, not an error.
- No AJAX. All forms POST and redirect (PRG pattern), consistent with the rest of the application.
- `budget_id` in the delete route is a UUID. The handler verifies `budget.user_id == session_user_id` before deleting.

---

### Decision 10 — Default period for the actual-vs-budget view

**Decision: current calendar month, derived from `date.today()` in UTC.** If the user navigates to a prior month via query params, that month is displayed instead. There is no "most recent month with data" heuristic — the current month is always the default regardless of whether any transactions have been uploaded for it yet. A month with zero actuals and existing budget targets is a valid and useful view (it shows what the user has budgeted but not yet spent).

## Schema specification

Single Alembic revision: `migrations/versions/0005_budgets.py`. Revises: `0004` (or the current head at the time Phase 4 ships).

### `public.budgets`

| Column | Type | Constraints |
|---|---|---|
| id | UUID | PRIMARY KEY, DEFAULT `gen_random_uuid()` |
| user_id | UUID | NOT NULL, FK → `auth.users(id)` ON DELETE CASCADE |
| category_id | UUID | NOT NULL, FK → `public.categories(id)` ON DELETE CASCADE |
| amount | NUMERIC(12,2) | NOT NULL, CHECK (`amount >= 0`) |
| budget_year | SMALLINT | NOT NULL, CHECK (`budget_year >= 2000 AND budget_year <= 2100`) |
| budget_month | SMALLINT | NOT NULL, CHECK (`budget_month BETWEEN 1 AND 12`) |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT `now()` |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT `now()` |

Constraints:
- `UNIQUE (user_id, category_id, budget_year, budget_month)` — one budget per user per category per month. Implicit index on these four columns satisfies the primary lookup pattern.
- `CHECK (amount >= 0)` — budget targets cannot be negative.
- `CHECK (budget_year >= 2000 AND budget_year <= 2100)` — defensive guard on year entry; rejects obviously wrong values.
- `CHECK (budget_month BETWEEN 1 AND 12)` — enforces valid month values.

Foreign keys:
- `user_id → auth.users(id) ON DELETE CASCADE` (per ADR-0015).
- `category_id → public.categories(id) ON DELETE CASCADE` — when a user deletes a category, the associated budget targets are deleted too. Unlike `transactions.category_id` (which uses `ON DELETE SET NULL` to preserve spend history), budget targets without a category have no meaning and should not survive the category's deletion.

Indexes:
- `idx_budgets_user_month ON budgets (user_id, budget_year, budget_month)` — covers the primary read pattern: "fetch all budgets for a user in a given month." The UNIQUE constraint on `(user_id, category_id, budget_year, budget_month)` also satisfies the upsert conflict target, but the three-column index provides a tighter scan for the monthly fetch.

**DDL sketch (for migration reference):**

```sql
CREATE TABLE public.budgets (
    id           UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id      UUID         NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    category_id  UUID         NOT NULL REFERENCES public.categories(id) ON DELETE CASCADE,
    amount       NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
    budget_year  SMALLINT     NOT NULL CHECK (budget_year  BETWEEN 2000 AND 2100),
    budget_month SMALLINT     NOT NULL CHECK (budget_month BETWEEN 1   AND 12),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (user_id, category_id, budget_year, budget_month)
);

CREATE INDEX idx_budgets_user_month
    ON public.budgets (user_id, budget_year, budget_month);
```

**PII note:** Budget targets (`amount`) are financial data. `category_id` is a reference to a user-defined category label — the label itself may contain PII (e.g., a category named after a person). Both are treated as High sensitivity, subject to cascade deletion on account removal (ADR-0015).

## Public service API

All functions live in `app/budgets/services.py`. No other module imports from this file except the Intelligence Layer (Phase 5), and only via the functions listed here.

### Types

```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from uuid import UUID


class BudgetStatus(Enum):
    UNDER = "under"   # spend < 80% of target
    NEAR  = "near"    # 80% <= spend <= 100% of target
    OVER  = "over"    # spend > 100% of target, or target == 0 and spend > 0


@dataclass(frozen=True)
class Budget:
    """A single budget target row, as returned by the service layer."""
    id: UUID
    user_id: str
    category_id: UUID
    category_name: str          # denormalized from categories table for display
    amount: Decimal             # the budget target; always >= 0
    budget_year: int
    budget_month: int


@dataclass(frozen=True)
class BudgetProgress:
    """A budget target paired with the actual spend for that period."""
    budget: Budget | None       # None when there is spend but no budget set
    category_id: UUID
    category_name: str | None   # None only for uncategorized spend
    target: Decimal             # budget.amount, or Decimal("0") if no budget
    actual: Decimal             # from get_spend_by_category; always >= 0
    variance: Decimal           # target - actual; negative means over budget
    pct_used: Decimal           # actual / target * 100; Decimal("0") if target == 0
    status: BudgetStatus


@dataclass(frozen=True)
class ProposedBudget:
    """A budget amount suggested by the proposal engine, not yet persisted."""
    category_id: UUID
    category_name: str
    proposed_amount: Decimal    # rounded to nearest whole dollar
    months_of_data: int         # how many look-back months had any spend
    average_monthly_spend: Decimal  # unrounded, for display
```

### Functions

```python
# --- Read ---

def get_budgets(
    user_id: str,
    year: int,
    month: int,
) -> list[Budget]:
    """Return all budget targets for a user in a given month.

    Returns an empty list if no budgets are set. Never raises on missing data.
    Ordered by category_name ASC, nulls last.
    """
    ...


def get_budget_progress(
    user_id: str,
    year: int,
    month: int,
) -> list[BudgetProgress]:
    """Return actual-vs-budget for every relevant category in the given month.

    Calls get_spend_by_category(user_id, DateRange.for_month(year, month))
    and get_budgets(user_id, year, month), then joins by category_id.

    The returned list includes:
    - Categories that have a budget target (even if actual spend is zero).
    - Categories that have actual spend in the period (even if no budget is set;
      these appear with budget=None and target=Decimal("0")).

    Uncategorized spend (category_id=None) is included with budget=None and
    category_name=None. Callers are responsible for rendering a display label.

    Ordered by: budgeted categories first (by category_name ASC), then
    unbudgeted-but-spent categories (by actual DESC), then uncategorized.

    Never raises on empty data. Returns an empty list if no budgets and no spend.
    """
    ...


def propose_budgets(
    user_id: str,
    target_year: int,
    target_month: int,
) -> list[ProposedBudget]:
    """Generate proposed budget amounts based on spending history.

    Looks back PROPOSAL_LOOKBACK_MONTHS complete calendar months before
    target_month. Calls get_spend_history for each category found in that
    window. Computes round(average_monthly_spend, 0) per category.

    Returns proposals for all categories that had any spend in the look-back
    window. Does not filter out categories that already have a budget for
    target_month — the caller decides whether to skip or overwrite those.

    Returns an empty list if there is no transaction history. Never raises
    on missing data.
    """
    ...


# --- Write ---

def upsert_budget(
    user_id: str,
    category_id: UUID,
    amount: Decimal,
    year: int,
    month: int,
) -> Budget:
    """Create or update the budget target for a category in a given month.

    Uses INSERT ... ON CONFLICT (user_id, category_id, budget_year, budget_month)
    DO UPDATE SET amount = EXCLUDED.amount, updated_at = now().

    Raises ValueError if amount < 0.
    Raises ValueError if month not in 1..12.
    Raises ValueError if year not in 2000..2100.
    Propagates DB exceptions (e.g., FK violation if category_id does not exist
    for this user) without wrapping.

    Returns the persisted Budget row after upsert.
    """
    ...


def delete_budget(
    user_id: str,
    budget_id: UUID,
) -> None:
    """Hard-delete a budget row.

    Verifies user_id ownership before deleting. Raises ValueError if the
    budget_id does not exist or does not belong to user_id.
    """
    ...


def apply_proposed_budgets(
    user_id: str,
    proposals: list[ProposedBudget],
    year: int,
    month: int,
    replace_existing: bool = False,
) -> int:
    """Persist a list of proposed budgets for the given month.

    If replace_existing is False (default), skips any proposal for a category
    that already has a budget row for (year, month). If replace_existing is
    True, overwrites existing rows via upsert.

    All writes run in a single database transaction. Either all proposed
    budgets land or none do.

    Returns the number of budget rows written (skipped rows are not counted).
    """
    ...
```

### Module-level constants

```python
PROPOSAL_LOOKBACK_MONTHS: int = 3
NEAR_LIMIT_THRESHOLD: Decimal = Decimal("0.80")
OVER_BUDGET_THRESHOLD: Decimal = Decimal("1.00")
```

### Error model

| Condition | Behavior |
|---|---|
| `amount < 0` passed to `upsert_budget` | `ValueError` raised before any DB call |
| `month` not in 1..12 | `ValueError` raised before any DB call |
| `budget_id` not found or wrong user in `delete_budget` | `ValueError` |
| `proposals` is an empty list in `apply_proposed_budgets` | Returns 0 immediately, no DB call |
| No budgets and no spend for period | `get_budget_progress` returns `[]`, does not raise |
| DB connectivity failure | Propagates as the underlying exception. No wrapping. Same policy as ADR-0017/ADR-0023. |

## What is explicitly deferred

- **Non-monthly period types.** The schema is monthly-only. Weekly, quarterly, and annual budgets require a new ADR and a schema migration.
- **Per-user threshold configuration.** `NEAR_LIMIT_THRESHOLD` and `OVER_BUDGET_THRESHOLD` are global constants. Making them user-configurable requires a new ADR and an Account Settings schema change.
- **Income budgeting.** The Transaction Engine's aggregation API excludes credits. If the user wants to budget expected income, a new ADR is needed covering how credits are aggregated.
- **"Total spend" (uncategorized-only or all-category) budget.** `category_id` is NOT NULL. A total-spend sentinel requires a schema change.
- **Notifications and alerting.** Phase 5 (Intelligence Layer) will implement threshold alerts. The `BudgetProgress.status` field exposed by `get_budget_progress` is the hook Phase 5 will consume; no alert infrastructure is introduced in Phase 4.
- **Budget history / trend view.** Phase 4 shows the progress view for one month at a time. A multi-month comparison table is deferred to Phase 5 or a Phase 4.1 follow-up.
- **Category-level notes or labels on budget rows.** No free-text field on `budgets`. If needed, add it via a separate ADR.

## Consequences

- **Positive:** The Budgeting Module is fully isolated from the Transaction Engine's tables — all actuals flow through `get_spend_by_category`, consistent with ADR-0003.
- **Positive:** `get_budget_progress` gives Phase 5 (Intelligence Layer) a single function call to retrieve everything needed for threshold alerts and narrative summaries.
- **Positive:** The monthly-only schema is simple, correct, and directly maps to the `DateRange.for_month` constructor from ADR-0023 — no conversion or off-by-one risk.
- **Positive:** Hard delete (consistent with ADR-0015) and cascade on category deletion keep the database free of orphaned targets.
- **Positive:** The upsert path (`ON CONFLICT DO UPDATE`) means the "save budget" form is always idempotent — double-submitting does not create duplicate rows.
- **Negative:** `get_budget_progress` makes two service calls (one to the Transaction Engine, one to its own data layer) on every page load. At personal-finance scale (dozens of categories, one user) this is negligible; if profiling later shows it is a bottleneck, a caching layer can be added without changing the API contract.
- **Negative:** The proposal engine calls `get_spend_history` once per category across the look-back window (N categories × 1 call each). For a user with 20 categories and a 3-month look-back, this is 20 calls to `get_spend_history`. Acceptable at this scale; a future optimization (batch all categories in a single call) does not change the public API.
- **Follow-up:** The implementation agent authors Alembic revision `0005_budgets` under the migration write-lock (ADR-0007). The revision creates `public.budgets` and `idx_budgets_user_month` exactly as specified in this ADR.
- **Follow-up:** The test-writer agent must cover: `get_budget_progress` with no budgets and spend (unbudgeted categories appear), `get_budget_progress` with budgets and no spend (zero actuals), proposal with fewer than 2 months of history, `upsert_budget` with invalid inputs, `delete_budget` with wrong `user_id`, `apply_proposed_budgets` with `replace_existing=False` skips existing rows, and `apply_proposed_budgets` atomicity on partial failure.
- **Follow-up:** Phase 5 Intelligence Layer must import `get_budget_progress` and `BudgetProgress` from `app.budgets.services` — not from `app.transactions.services`. This is the cross-module contract for alerting.
- **Follow-up:** Update the cross-module deletion runbook in ADR-0015 to add the verification query `SELECT COUNT(*) FROM public.budgets WHERE user_id = :uid` to the post-deletion checklist.

## Notes

The roadmap note on Phase 4 states: "The actual-vs-budget computation is the Budgeting Module's own responsibility, since that arithmetic is core to what a budget feature is." This ADR implements that principle via `get_budget_progress` — the Transaction Engine is purely a data source, and the join, variance calculation, and status classification all live in the Budgeting Module's service layer.

`category_id ON DELETE CASCADE` (vs. the `ON DELETE SET NULL` used on `transactions.category_id`) is a deliberate asymmetry. A transaction without a category is still a real spend event and should be preserved. A budget target without a category is a meaningless row with no display label and no join target — it should not outlive its category.
