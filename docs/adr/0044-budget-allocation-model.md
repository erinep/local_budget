# ADR 0044 - Budget Allocation Model: Dual Representation

- **Status:** Accepted
- **Date:** 2026-05-31
- **Phase:** P5e
- **Deciders:** architect

## Context

Phase 5e introduces an income-driven allocation model (see [ADR-0043](0043-income-field-schema.md)). Once a user sets their monthly income, every category budget target should be expressible both as a dollar amount and as a percentage of income. The slider UI must show both values live. The question is which representation is stored as the source of truth in `public.budgets.amount` and which is derived at display time.

The current schema (ADR-0026) stores only `amount NUMERIC(12,2)` — a dollar figure. Any change that introduces a percentage column or replaces the dollar column requires an Alembic migration and must not lose existing budget data.

Binding constraints:
- [ADR-0026](0026-budgets-global-targets.md) — `public.budgets.amount` is NUMERIC(12,2), the existing source of truth. Any migration must preserve all existing rows.
- [ADR-0007](0007-schema-migration-tooling.md) — every schema change goes through Alembic.
- [ADR-0043](0043-income-field-schema.md) — `monthly_income` is nullable. When income is not set, the percentage representation is undefined. The model must degrade gracefully.
- [ADR-0003](0003-module-communication-service-layer-only.md) — derived values computed by the service layer, not by cross-module queries.
- Relevant risk: "Schema design locks in early mistakes" (P1+, High) from [risks.md](../risks.md).

## Options considered

### Option A - Store dollars only; compute percentage on the fly

Keep `public.budgets.amount` as the sole stored field. When the budget page loads and income is set, compute `pct = amount / monthly_income * 100` in the service layer for display. When a slider moves (dollar or percent), the client sends the dollar value; the server stores it. The percentage shown is always derived.

Pros:
- No schema change from ADR-0026. Zero migration risk for existing rows.
- Single source of truth; no sync problem. Rounding only happens at display time, not in the DB.
- Percentage is conceptually a derived value — it changes whenever income changes, even if the dollar target hasn't changed. Storing it would make it stale the moment income is updated.
- Consistent with how every other financial report in this system works: amounts are stored as dollars and ratios are computed at query time.

Cons:
- If a user sets a budget by typing a percentage (e.g., "20% of income"), the stored dollar value is `round(0.20 × income, 2)`. If they later change income, the percentage is no longer 20% unless they re-derive and re-save the dollar value. The system cannot distinguish "this budget was set as 20% of income" from "this budget was set as $800." The intent is lost.
- Slider UX must recompute the percentage client-side from the dollar value and income, which means the JavaScript needs both values.

### Option B - Store percentage only; compute dollars on the fly

Replace `amount NUMERIC(12,2)` with `pct_of_income NUMERIC(5,4)` (e.g., `0.2000` for 20%). Dollar amount is computed as `pct_of_income × monthly_income` at display time.

Pros:
- Budget targets survive an income change correctly — a 20% target is always 20% of whatever income is current.
- Slider intent is preserved exactly as set.

Cons:
- Requires a breaking migration on `public.budgets`. Existing `amount` rows must be converted to percentages, which requires income to be known at migration time. Existing users who have no income set would have their budget rows set to NULL or 0%, destroying data.
- When income is not set (ADR-0043: `monthly_income` is nullable), the dollar amount is undefined and the budget progress view (`get_budget_progress`) cannot function — there is nothing to compare against actuals. The Phase 4 experience is fully broken for users without income.
- Percentages do not compose naturally when income is unknown. A "20% of income" budget is meaningless without an income figure.
- NUMERIC(5,4) permits up to 9.9999, which is nonsensical for a percentage stored as a fraction. Constraints must guard against this, adding complexity.

### Option C - Store both dollar amount and percentage; keep both in sync

Add a `pct_of_income NUMERIC(5,4)` column alongside `amount NUMERIC(12,2)`. When a user saves, both are stored. When income changes, a recompute step updates both.

Pros:
- Both values are instantly readable from the DB without computation.

Cons:
- Two columns for one logical value. Any write that updates one without the other leaves the row in an inconsistent state. The service layer must enforce atomic updates of both fields on every write path — a discipline cost that grows with the number of write paths.
- Income changes require a sweep of all `public.budgets` rows to recompute `amount` from `pct_of_income` or vice versa — whichever is canonical at that moment. The question of "which is canonical" is the same decision this ADR is trying to make, just deferred until runtime.
- The sync problem is a known reliability risk: two columns that should agree but sometimes don't, especially across edge cases like income being cleared after budgets are set.
- Ruled out by the architecture principle "reversibility over optimization" — Option C is optimization (avoid a division) at the cost of correctness surface.

## Decision

We will choose **Option A** — store dollar amounts only in `public.budgets.amount`; derive percentage from `amount / monthly_income` in the service layer for display.

The two reasons that carried this decision: (1) percentage is a derived value that depends on both `amount` and `monthly_income` — storing it introduces a sync problem that grows every time income is updated, and a sync bug in financial data is worse than the cost of a division; (2) Option A requires no schema migration, preserving all existing budget rows and the full Phase 4 experience for users who never set income.

**Slider behavior contract.** The sliders on the budget page show both a dollar value and a percentage. The percentage shown is always `amount / monthly_income × 100`, computed client-side from the slider position and the income value embedded in the page. When the user moves the dollar slider, the percent updates; when the user moves the percent slider, the dollar updates. The value submitted to the server on save is always the dollar amount, rounded to the nearest cent. The server stores only the dollar amount.

**Rounding rule.** When a percent slider produces a dollar value, round to the nearest cent (`round(income × pct / 100, 2)`). This is a display-time rounding, not a stored rounding; the stored value is always the rounded result of what the user confirmed. Percentage displayed back from a stored dollar amount is `round(amount / income × 100, 1)` — one decimal place is sufficient for display and avoids floating-point drift in the UI.

**Income-not-set fallback.** When `monthly_income` is NULL, the percentage column on the slider is hidden. The slider shows dollar amounts only, and the page does not display an "allocated vs. unallocated" summary. This preserves the Phase 4 experience for users who have not set income.

## Service API changes (Budgeting Module)

The `Budget` dataclass gains a computed field for display; the underlying DB schema is unchanged.

```python
@dataclass(frozen=True)
class Budget:
    """A single budget target row, as returned by the service layer."""
    id: UUID
    user_id: str
    category_id: UUID
    category_name: str
    amount: Decimal             # stored dollar value; always >= 0
    # No pct_of_income field on the dataclass — percentage is computed by the
    # caller using monthly_income from get_user_settings(). Keeping it out of
    # the dataclass prevents accidental stale-percentage bugs when income changes.
```

A helper function in the Budgeting service layer produces the allocation summary:

```python
def compute_allocation_summary(
    budgets: list[Budget],
    monthly_income: Decimal | None,
) -> AllocationSummary | None:
    """Return allocated vs. unallocated income totals.

    Returns None when monthly_income is None (income not set).
    Returns an AllocationSummary with:
        total_allocated: sum of all budget amounts
        total_unallocated: monthly_income - total_allocated (may be negative)
        pct_allocated: total_allocated / monthly_income * 100
    All values are Decimal. Caller is responsible for display rounding.
    """
    ...


@dataclass(frozen=True)
class AllocationSummary:
    total_allocated: Decimal
    total_unallocated: Decimal   # negative means over-allocated
    pct_allocated: Decimal
    monthly_income: Decimal
```

The existing `upsert_budget` signature from ADR-0026 is unchanged — it accepts a dollar `amount` and stores it. No percentage parameter is added.

## Consequences

- Positive: No schema migration. All existing budget rows are valid under the new model. Users who never set income see no change.
- Positive: No sync problem. There is exactly one source of truth (`amount`) and one derived value (`pct`) computed at display time.
- Positive: Income changes are free — no row sweep needed. The new percentage display is correct immediately on the next page load because it is computed from the current income figure.
- Positive: `AllocationSummary` gives the UI the "allocated vs. unallocated" running total ([roadmap](../roadmap.md) work item 1) without any schema change.
- Negative: If a user sets a budget intending "20% of income" and later changes income, the stored dollar amount is unchanged. The displayed percentage drifts. The UI should make this visible: when income changes, the allocation summary updates instantly, and the user can see that their existing dollar targets now represent different percentages. A future "recalculate all targets from percentages" feature could address this, but it requires storing intent (percentage-based vs. dollar-based) — deferred past Phase 5e.
- Negative: Client-side slider math requires JavaScript access to the `monthly_income` value. This must be serialized into the page (e.g., as a `data-income` attribute on the form container) rather than fetched via AJAX, consistent with the Jinja + HTMX stack ([ADR-0038](0038-frontend-stack-for-reporting-overhaul.md)).
- Follow-ups required:
  1. Implementation agent embeds `monthly_income` in the budget page template as a `data-` attribute for slider JavaScript to consume.
  2. Test-writer agent must cover `compute_allocation_summary` with: income set and all budgets allocated, income set and over-allocated (negative unallocated), income set and zero budgets, income not set (returns None).
  3. If a future phase adds "percentage-intent" storage, open a new ADR — do not add a `pct_of_income` column without one.

## Notes

Option B was the most tempting alternative because it preserves the user's intent ("I want 20% on groceries"). The decisive counterargument is the income-not-set case: a personal finance app for one user may go weeks without income being set, and Option B makes the entire budget view non-functional in that window. The real-world behavior of Option A — dollar amounts that predate income entry are perfectly usable, and the percentage column simply appears once income is entered — is the correct degradation path.
