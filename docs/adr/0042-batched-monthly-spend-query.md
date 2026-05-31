# ADR 0042 - Batched Monthly Spend Query for Intelligence Widgets

- **Status:** Accepted
- **Date:** 2026-05-30
- **Phase:** P5d
- **Deciders:** erin p

## Context

Phase 5d's Intelligence Dashboard loads several widgets on every page render. The `category_trends` widget answers "How has spending in each category changed over time?" by iterating over each month in the requested date range and calling `get_spend_by_category` once per month. At the default 12-month range plus the current MTD month, this produces 13 round-trips to the database. At a 24-month range it produces 25. The `category_radar` widget compounds this by calling the paginated `get_transactions` endpoint once per month slot — 12 calls minimum, more when pagination kicks in.

With the addition of a date range picker (3M / 6M / 12M / 24M) in Phase 5d, every range change triggers a full page reload that re-runs all of these loops. This was flagged as a live performance issue: page load time scaled linearly with the number of months in view, and every date range change re-paid the full cost.

[ADR-0023](0023-aggregation-api.md) anticipated this in its Consequences section ("a future optimization with single query and date bucketing does not change the contract") and in its SQL shape note ("A single query with date bucketing is a valid optimization if the implementation agent chooses it, but only if it produces identical results to N separate queries"). ADR-0023 also stated that any addition beyond the four methods defined there requires a new ADR.

[ADR-0003](0003-module-communication-service-layer-only.md) requires all widget reads to go through the Transaction Engine service layer — the fix must be a new service method, not a direct query from the widget.

## Options considered

### Option A — Optimize inside the existing `get_spend_by_category` call site

Have the widget build the full date range and call `get_spend_by_category` once with the whole span. This returns a single `list[CategorySpend]` without month granularity — the month breakdown is lost and the widget cannot plot a time series.

**Pros.** No new service method.
**Cons.** Lossy — collapses all months into a single aggregate, which is not what the trend widget needs.

### Option B — Add `get_spend_by_category_monthly`: one query, grouped by (year, month, category)

A new service function takes a `DateRange` spanning the full multi-month window and issues a single SQL query that groups by `EXTRACT(YEAR FROM date)`, `EXTRACT(MONTH FROM date)`, `category_id`, and `category_name`. The result is a flat `list[CategorySpendMonthly]` that callers pivot in Python by `(year, month)` key.

```sql
SELECT
    EXTRACT(YEAR  FROM t.date)::int AS year,
    EXTRACT(MONTH FROM t.date)::int AS month,
    t.category_id,
    c.name AS category_name,
    SUM(ABS(t.amount)) AS spend,
    COUNT(*) AS transaction_count
FROM public.transactions t
LEFT JOIN public.categories c ON c.id = t.category_id
JOIN public.accounts a ON a.id = t.account_id AND a.is_active = TRUE
WHERE t.user_id = :user_id
  AND t.date >= :date_from AND t.date <= :date_to
  AND t.amount < 0
GROUP BY year, month, t.category_id, c.name
ORDER BY year, month, spend DESC, category_name NULLS LAST
```

**Pros.** N+1 becomes 1. The existing `get_spend_by_category` contract is unchanged — no callers break. The new function is additive, consistent with ADR-0017's evolution clause. The SQL shape is identical in semantics to calling `get_spend_by_category` N times — the results are identical at any month boundary.
**Cons.** A fifth method on the Transaction Engine API (hence this ADR). Callers are responsible for pivoting the flat result into their per-month structure, which is a small amount of boilerplate — acceptable given the query savings.

### Option C — Extend `get_spend_by_category` with an optional `group_by_month` flag

Add a `group_by_month: bool = False` parameter to the existing function. When true, return a differently-shaped result.

**Pros.** One method name.
**Cons.** The return type changes shape based on a flag — `list[CategorySpend]` vs something else. ADR-0023 explicitly rejected this pattern (see "Option D" in that ADR) as it forces callers to branch on return type based on input shape. Repeat that rejection here.

## Decision

**Option B — new `get_spend_by_category_monthly` function** returning `list[CategorySpendMonthly]`.

The existing `get_spend_by_category` remains unchanged. No callers break. The new function is the right tool specifically for widgets that need a per-month breakdown across a multi-month window. Option C is rejected for the same reason ADR-0023 rejected its equivalent.

**What is now true about the system.**

1. `get_spend_by_category_monthly(user_id, period, account_id=None)` is part of the Transaction Engine's exported API surface. It issues one query and returns `list[CategorySpendMonthly]` ordered by `(year, month, spend DESC)`.
2. `CategorySpendMonthly` is a new frozen dataclass exported from `app/transactions/services.py`.
3. `category_trends` uses `get_spend_by_category_monthly` instead of a per-month loop — query count drops from N+1 to 1 regardless of the selected date range.
4. `category_radar` fetches all transactions for its 12-month window in a single paginated call and groups by month in Python — query count drops from 12+ calls to one paginated loop.
5. The existing `idx_transactions_user_date` index from ADR-0016 covers the new query's leading predicates (`user_id`, `date`). No new index is required.

## Public API addition

The following names are added to the Transaction Engine's exported surface in `app/transactions/services.py`. All names from ADR-0023 remain unchanged.

```python
# New types — Phase 5d (this ADR)
CategorySpendMonthly

# New functions — Phase 5d (this ADR)
get_spend_by_category_monthly(
    user_id: str,
    period: DateRange,
    account_id: UUID | None = None,
) -> list[CategorySpendMonthly]
```

```python
@dataclass(frozen=True)
class CategorySpendMonthly:
    """Aggregated spend for one category within one calendar month.

    Returned by get_spend_by_category_monthly. spend is non-negative.
    category_id and category_name are None for uncategorized transactions.
    """
    year: int
    month: int
    category_id: UUID | None
    category_name: str | None
    spend: Decimal
    transaction_count: int
```

## Consequences

- **Positive.** Dashboard load time no longer scales with the selected date range. A 24-month view costs the same number of queries as a 3-month view: one.
- **Positive.** Every date range change (3M / 6M / 12M / 24M picker) now triggers one query per widget instead of N. The picker is viable at any supported range.
- **Positive.** The existing `get_spend_by_category` signature is untouched. Budgeting Module callers and home route callers see no change.
- **Negative.** A fifth method on the Transaction Engine API. Future maintainers must keep two aggregation functions with similar names conceptually aligned.
- **Negative.** Callers of `get_spend_by_category_monthly` must pivot the flat result into per-month structures in Python. The boilerplate is small but it is the caller's responsibility.
- **Follow-up.** The test-writer agent should cover: empty range, single-month range (should produce equivalent results to `get_spend_by_category`), multi-month range with gaps, `account_id` filter, uncategorized rows, and the month-boundary pivot in the `category_trends` assembler.

## Notes

ADR-0023's Consequences section noted: "A future optimization (single query with date bucketing) does not change the contract." This ADR is that optimization, implemented as a separate function per the guidance in that section and the additive-evolution clause from ADR-0017.

The `category_radar` fix (single paginated fetch over the full range, Python grouping by month) follows the same principle but operates at the transaction level rather than the aggregate level — radar needs individual transactions for outlier detection and per-transaction display, so an aggregate query is not sufficient there. The fix reduces it from 12 × N_pages queries to N_pages queries.
