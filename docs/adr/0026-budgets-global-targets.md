---
adr: 0026
title: Budgets — Global Targets, Not Month-Specific Rows
status: Accepted
date: 2026-05-18
phase: P4
deciders: erin
---

## Context

ADR-0025 (Decisions 1 and 2) defined the `budgets` schema as month-specific: each row carried `(budget_year, budget_month)` and the UNIQUE constraint was `(user_id, category_id, budget_year, budget_month)`. The intended model was "set a different target each month, compare actuals against that month's target."

Before any user data was written, this was identified as the wrong model. The actual requirement is simpler: **one persistent target per category, compared against whichever month the user is viewing.** There is no need to configure a separate budget for January vs February.

## Decision

Supersedes ADR-0025 Decisions 1 and 2.

**Drop `budget_year` and `budget_month` from `public.budgets`.** A budget target is a standing amount per category — not a month-specific record. The UNIQUE constraint becomes `(user_id, category_id)`.

**New schema:**

```sql
CREATE TABLE public.budgets (
    id           UUID          NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id      UUID          NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    category_id  UUID          NOT NULL REFERENCES public.categories(id) ON DELETE CASCADE,
    amount       NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (user_id, category_id)
);

CREATE INDEX idx_budgets_user ON public.budgets (user_id);
```

**Updated service signatures:**

```python
def get_budgets(user_id: str) -> list[Budget]:
    """Return all budget targets for a user."""

def get_budget_progress(user_id: str, year: int, month: int) -> list[BudgetProgress]:
    """Compare standing budget targets against actuals for the given month."""

def upsert_budget(user_id: str, category_id: UUID, amount: Decimal) -> Budget:
    """Create or update the standing budget target for a category."""

def delete_budget(user_id: str, budget_id: UUID) -> None:
    """Hard-delete a budget target."""
```

`propose_budgets` and `apply_proposed_budgets` are simplified accordingly — proposals are applied to the single standing target row, not to a specific month.

## Rationale

The month-specific model adds complexity (configure January separately from February) with no benefit for a personal finance app. A standing target — "I want to spend at most $400 on groceries" — is compared against actual spend for whatever month you're looking at. If targets need to change, the user edits them and the new value applies going forward. Seasonal variation is out of scope (deferred per ADR-0025).

The simpler schema also removes the `replace_existing` flag from `apply_proposed_budgets` and eliminates the "gaps only vs replace all" distinction — there is now only one row per category to set.

## Consequences

- Migration `0006_budgets` (from ADR-0025) must be replaced with a corrected version using the new schema.
- `get_budgets`, `upsert_budget` drop the `year`/`month` parameters.
- The configure UI no longer needs month/year fields — it is a simple "set your targets" form.
- `Budget.budget_year` and `Budget.budget_month` fields are removed from the dataclass.
- All other ADR-0025 decisions (thresholds, routes, PRG, cascade) remain unchanged.
