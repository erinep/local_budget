# ADR 0042 - Batched Grouped Spend Query for Intelligence Widgets

- **Status:** Accepted
- **Date:** 2026-05-30
- **Phase:** P5d
- **Deciders:** erin p

## Context

Phase 5d's Intelligence Dashboard loads several widgets on every page render. The `category_trends` widget answers "How has spending in each category changed over time?" by iterating over each month in the requested date range and calling `get_spend_by_category` once per month. At the default 12-month range plus the current MTD month, this produces 13 round-trips to the database. At a 24-month range it produces 25. The `category_radar` widget compounds this by calling the paginated `get_transactions` endpoint once per month slot — 12 calls minimum, more when pagination kicks in.

With the addition of a date range picker (This month / 3M / 6M / 12M / 24M) and a granularity picker (Daily / Weekly / Monthly) in Phase 5d, every picker change triggers a full page reload that re-runs all of these loops. Daily granularity over a 24-month range would be 730 queries under the old pattern.

[ADR-0023](0023-aggregation-api.md) anticipated this in its Consequences section ("a future optimization with single query and date bucketing does not change the contract") and in its SQL shape note ("A single query with date bucketing is a valid optimization if the implementation agent chooses it, but only if it produces identical results to N separate queries"). ADR-0023 also stated that any addition beyond the four methods defined there requires a new ADR.

[ADR-0003](0003-module-communication-service-layer-only.md) requires all widget reads to go through the Transaction Engine service layer — the fix must be a new service method, not a direct query from the widget.

## Options considered

### Option A — Three separate functions: `get_spend_by_category_monthly`, `_weekly`, `_daily`

One function per granularity, each issuing a single query with the appropriate `DATE_TRUNC` or date expression.

**Pros.** Each function has a single, obvious purpose.
**Cons.** Near-identical SQL and boilerplate repeated three times. Adding a future granularity (e.g., quarterly) means a fourth function. No shared validation or dispatch logic.

### Option B — One `get_spend_by_category_grouped(granularity)` function (selected)

A single function accepting `granularity: str` (`"day"`, `"week"`, or `"month"`). The function validates the granularity, selects the appropriate `DATE_TRUNC` / date expression, and issues one SQL query. Returns `list[CategorySpendGrouped]` with a `period_start: date` field that holds the first date of each bucket (month first-day, ISO week Monday, or the day itself).

**Pros.** One method, one SQL shape, one return type. Adding a granularity is one `elif` branch. The `CategorySpendGrouped` dataclass is granularity-agnostic. Consistent with the "DateRange is the only option that serves both Phase 4's monthly views and Phase 5's arbitrary-window trend queries" reasoning from ADR-0023.
**Cons.** The `granularity` parameter is a string rather than a typed enum — invalid values must be validated at the boundary. The assembler and route both validate it, so runtime risk is low.

### Option C — Extend `get_spend_by_category` with a `group_by` flag

Add a `group_by: str | None = None` parameter to the existing function. When set, return a differently-shaped result.

**Cons.** Return type changes with input — ADR-0023 explicitly rejected this pattern (its Option D). Repeat that rejection here.

## Decision

**Option B — `get_spend_by_category_grouped(user_id, period, granularity, account_id)`.** One function, one query, one return type. The existing `get_spend_by_category` is unchanged.

**What is now true about the system.**

1. `get_spend_by_category_grouped` is part of the Transaction Engine's exported API. It issues one query grouped by `(period_start, category_id, category_name)` and returns `list[CategorySpendGrouped]` ordered by `(period_start, spend DESC)`.
2. `CategorySpendGrouped` is a new frozen dataclass with a `period_start: date` field (month first-day, ISO week Monday, or day) and the same `category_id`, `category_name`, `spend`, `transaction_count` fields as `CategorySpend`.
3. `category_trends` uses `get_spend_by_category_grouped` instead of a per-period loop — query count is 1 regardless of the selected date range or granularity.
4. `category_radar` fetches all transactions for its 12-month window in a single paginated call and groups by month in Python — query count drops from 12+ calls to one paginated loop.
5. The `category_trends` widget exposes a granularity picker (Daily / Weekly / Monthly) alongside the existing date range picker. Both pickers carry each other's current value in their links, so switching one preserves the other.
6. The existing `idx_transactions_user_date` index from ADR-0016 covers the new query's leading predicates. No new index is required.

## Public API addition

The following names are added to the Transaction Engine's exported surface in `app/transactions/services.py`. All names from ADR-0023 remain unchanged.

```python
# New types — Phase 5d (this ADR)
CategorySpendGrouped

# New functions — Phase 5d (this ADR)
get_spend_by_category_grouped(
    user_id: str,
    period: DateRange,
    granularity: str = "month",   # "day", "week", or "month"
    account_id: UUID | None = None,
) -> list[CategorySpendGrouped]
```

```python
@dataclass(frozen=True)
class CategorySpendGrouped:
    """Aggregated spend for one category within one time bucket.

    period_start is the first date of the bucket:
      - granularity="month" → first day of the calendar month
      - granularity="week"  → Monday of the ISO week (DATE_TRUNC('week'))
      - granularity="day"   → the transaction date itself
    spend is always non-negative. category_id / category_name are None for
    uncategorized transactions.
    """
    period_start: date
    category_id: UUID | None
    category_name: str | None
    spend: Decimal
    transaction_count: int
```

## SQL shape

```sql
SELECT
    -- period_expr is one of:
    --   DATE_TRUNC('month', t.date)::date   (granularity="month")
    --   DATE_TRUNC('week',  t.date)::date   (granularity="week")
    --   t.date                              (granularity="day")
    <period_expr> AS period_start,
    t.category_id,
    c.name AS category_name,
    SUM(ABS(t.amount)) AS spend,
    COUNT(*) AS transaction_count
FROM public.transactions t
LEFT JOIN public.categories c ON c.id = t.category_id
JOIN public.accounts a ON a.id = t.account_id AND a.is_active = TRUE
WHERE t.user_id = :user_id
  AND t.date >= :date_from
  AND t.date <= :date_to
  AND t.amount < 0
GROUP BY period_start, t.category_id, c.name
ORDER BY period_start, spend DESC, category_name NULLS LAST
```

`DATE_TRUNC('week', ...)` in PostgreSQL returns the Monday of the ISO week, which is the correct week-start convention.

## `CategoryTrendsVM` additions

```python
@dataclass(frozen=True)
class CategoryTrendsVM:
    title: str
    labels: list[str]   # display labels ("Jan 2026", "Jan 5", etc.)
    dates: list[str]    # "YYYY-MM-DD" ISO period starts for JS click-through
    datasets: list[dict]
    period_months: int
    granularity: str    # "day", "week", or "month"
```

The `dates` field is serialized into the chart's `data-chart` attribute and consumed by the click-through handler in JS to compute the correct `date_from`/`date_to` URL parameters — no label string parsing needed.

## Consequences

- **Positive.** Dashboard load time no longer scales with the selected date range or granularity. A daily 24-month view costs 1 query, same as a monthly 3-month view.
- **Positive.** The granularity picker (Daily / Weekly / Monthly) is viable at any supported date range — the query cost is flat.
- **Positive.** Existing `get_spend_by_category` callers are unchanged.
- **Negative.** A fifth method on the Transaction Engine API. Future maintainers must keep `get_spend_by_category` and `get_spend_by_category_grouped` conceptually aligned.
- **Negative.** `granularity` is a validated string rather than a typed enum — the boundary validation in the route and assembler must stay in sync with the service's `_VALID_GRANULARITIES` set.
- **Follow-up.** The test-writer agent should cover: each granularity with a multi-period range, `account_id` filter, uncategorized rows, `ValueError` on invalid granularity, and equivalence between `get_spend_by_category_grouped(granularity="month")` and `get_spend_by_category` for a single calendar month.

## Notes

ADR-0023's Consequences section noted: "A future optimization (single query with date bucketing) does not change the contract." This ADR is that optimization, generalized to support daily and weekly buckets in addition to monthly.

The `category_radar` fix (single paginated fetch over the full range, Python grouping by month) follows the same principle but operates at the transaction level — radar needs individual transactions for outlier detection and per-transaction display, so an aggregate query is not sufficient there.
