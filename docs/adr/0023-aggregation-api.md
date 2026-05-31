---
adr: 0023
title: Transaction Engine Aggregation API — get_spend_by_category and get_spend_history
status: Accepted
date: 2026-05-18
phase: P3c
deciders: erin
---

## Context

Phase 3c adds two aggregation methods to the Transaction Engine read API, closing out the four-method shape described in [architecture.md](../architecture.md#transaction-engine) and first listed in [ADR-0017](0017-transaction-engine-read-api.md). These methods serve two immediate consumers and one future module:

1. **Dashboard spending summary** (`app/home/routes.py`) — `_get_spending_summary` currently calls `get_transactions` with `limit=500` and manually accumulates category totals. That approach is fragile (the 500-row cap silently undercounts heavy months), issues an unnecessary full-row fetch, and duplicates GROUP BY logic that belongs in the service layer.
2. **Phase 4 Budgeting Module** — `get_spend_by_category` is the "actuals" half of every actual-vs-budget comparison. Phase 4 cannot ship without it, and its contract must be stable before Phase 4 implementation begins.
3. **Intelligence Layer (Phase 5)** — `get_spend_history` drives trend detection and budget proposals. Pinning it now prevents a retrofitted contract from breaking Phase 4 consumers.

ADR-0003 prohibits direct cross-module table access; the aggregation surface must live here. ADR-0017 permits additive evolution — new functions added to the same module without modifying existing signatures. The sign convention in the existing `_get_spending_summary` helper (debits are negative; spend is `abs(amount)` where `amount < 0`) is the established convention across the codebase and is carried forward unchanged.

Relevant risks ([risks.md](../risks.md)): "Cross-module API contract drift" (High) — the Budgeting Module builds directly on this surface; "Schema design locks in early mistakes" (High) — the index shape must be decided here alongside the query shape.

## Options considered

### Option A — Period as `(year, month)` integer tuple

`period: tuple[int, int]` where `period = (2026, 5)` means May 2026. The service computes the date bounds internally.

**Pros.** Natural for monthly budget views. Unambiguous (no question of whether a `date` is inclusive or exclusive). Callers cannot express a half-month range by accident.

**Cons.** Inexpressive — cannot represent a quarter, a fiscal month, or a custom range without a different method. Phase 4 wants monthly granularity, but Phase 5 trend analysis works over arbitrary windows. Forcing the Budgeting Module to call this method twelve times for a year-to-date view is wasteful. The tuple also gives no hint about which element is year and which is month without naming convention or documentation.

### Option B — Period as a `DateRange` frozen dataclass (two `date` bounds, inclusive)

```python
@dataclass(frozen=True)
class DateRange:
    date_from: date
    date_to: date   # inclusive
```

`get_spend_by_category(user_id, period: DateRange)` — the service issues `WHERE date >= :from AND date <= :to`.

**Pros.** Fully general: callers can express a month, a quarter, an arbitrary YTD window, or a comparison range without any additional method overloads. Phase 5 passes a rolling 90-day window with no API change. Consistent with the `date_from`/`date_to` convention already on `TransactionFilters` (ADR-0017). No hidden arithmetic; the bounds are explicit and testable. The dataclass is frozen and can be reused by any future aggregation method that also needs a date window.

**Cons.** Slightly more verbose at the call site — callers construct the first and last day of the month themselves rather than passing `(2026, 5)`. A helper `DateRange.for_month(year, month)` factory method eliminates this in practice.

**Consequences.** The `DateRange` type becomes part of the exported API. It can be imported from `app/transactions/services.py` directly alongside the existing types.

### Option C — Period as a named enum (`CurrentMonth`, `LastMonth`, `Last90Days`, etc.)

An `Enum` of named windows. The service maps each member to a date range at query time.

**Pros.** Call sites are one-word expressions.

**Cons.** Each new period the Budgeting or Intelligence module wants requires an enum change — a contract change that ripples to callers. The Budgeting Module will need arbitrary date windows for multi-month trend tables; an enum cannot express them. This is the same problem as Option A but with even less flexibility.

### Option D — `get_spend_history` as a filter flag on `get_spend_by_category`

Instead of a separate method, add a `periods: list[DateRange] | None` parameter to `get_spend_by_category`. When `periods` is a list, the method returns aggregates for each period. When it is `None` (single period), the method returns aggregates for the one `period`.

**Pros.** One method instead of two. Fewer names in the public surface.

**Cons.** The return type becomes ambiguous — either a `list[CategorySpend]` for the single-period case or a `dict[DateRange, list[CategorySpend]]` for the multi-period case. This forces callers to branch on the return type based on input shape, which is the exact pattern that ADR-0017 rejected when it chose a typed filter dataclass over `**kwargs`. The two methods have meaningfully different SQL shapes (one GROUP BY, one GROUP BY + date bucketing) and different callers — conflating them violates the single-responsibility principle at the service layer. Keep them separate.

### Sub-option — Return type: `list[CategorySpend]` dataclass vs `dict[str, Decimal]`

A `dict[str, Decimal]` keyed by category name is the simplest return for `get_spend_by_category`.

**Against dict.** A dict keyed by name loses the `category_id` — the Budgeting Module needs the ID to join against budget targets. A dict forces callers to handle the uncategorized sentinel name as a magic string. Dict keys are unordered and untested by type checkers. Adding a field (e.g., transaction count) requires a breaking change to the value type.

**For a frozen dataclass `CategorySpend`.** The ID and name travel together. Uncategorized rows carry `category_id=None` and `category_name=None` unambiguously. New fields can be added without changing the key shape. Type checkers enforce the shape. The pattern is consistent with `Transaction` and `TransactionPage` from ADR-0017.

Decision: `CategorySpend` frozen dataclass. `get_spend_history` returns `list[PeriodSpend]` where each `PeriodSpend` contains a `DateRange` and its `list[CategorySpend]`.

## Decision

We will use **Option B** (`DateRange` frozen dataclass) as the period type, keep **two separate methods**, and return **frozen dataclasses** (`CategorySpend` for per-category rows, `PeriodSpend` for history rows).

The two reasons: (1) `DateRange` is the only option that serves both Phase 4's monthly actual-vs-budget views and Phase 5's arbitrary-window trend queries without a future contract change — flexibility now costs nothing and prevents an ADR-breaking retrofit later; (2) typed frozen dataclasses over dicts is the established convention in this codebase (ADR-0017) and gives the Budgeting Module the `category_id` it needs to join against budget targets.

## Public API surface

The following names are added to the Transaction Engine's exported surface in `app/transactions/services.py`. All names from ADR-0017 remain unchanged.

```python
# New types — Phase 3c
DateRange
CategorySpend
PeriodSpend

# New functions — Phase 3c
get_spend_by_category(user_id: str, period: DateRange, account_id: UUID | None = None) -> list[CategorySpend]
get_spend_history(user_id: str, category_id: UUID | None, periods: list[DateRange]) -> list[PeriodSpend]
```

Adding these names is additive per ADR-0017's evolution clause. No existing names are modified or removed.

## Function signatures and types

All types use `datetime.date`, `decimal.Decimal`, and `uuid.UUID` from the standard library.

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class DateRange:
    """Inclusive date bounds [date_from, date_to].

    Both ends are inclusive. Callers may construct arbitrary windows; the
    for_month() factory covers the common monthly-budget case.
    """
    date_from: date
    date_to: date  # inclusive

    def __post_init__(self) -> None:
        if self.date_from > self.date_to:
            raise ValueError("date_from must be <= date_to")

    @classmethod
    def for_month(cls, year: int, month: int) -> DateRange:
        """Return the DateRange covering the full calendar month."""
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        return cls(
            date_from=date(year, month, 1),
            date_to=date(year, month, last_day),
        )


@dataclass(frozen=True)
class CategorySpend:
    """Aggregated spend for one category within a single period.

    spend is always non-negative (absolute value of debits).
    category_id and category_name are None for uncategorized transactions.
    """
    category_id: UUID | None
    category_name: str | None   # None when category_id is None
    spend: Decimal              # non-negative; sum of abs(amount) for amount < 0
    transaction_count: int      # number of debit transactions in the bucket


@dataclass(frozen=True)
class PeriodSpend:
    """Aggregated spend for one DateRange, broken down by category."""
    period: DateRange
    categories: list[CategorySpend]
    total_spend: Decimal        # convenience sum of CategorySpend.spend


def get_spend_by_category(
    user_id: str,
    period: DateRange,
    account_id: UUID | None = None,
) -> list[CategorySpend]: ...


def get_spend_history(
    user_id: str,
    category_id: UUID | None,
    periods: list[DateRange],
) -> list[PeriodSpend]: ...
```

### Parameter rules

**`get_spend_by_category`**

| Parameter | Type | Rules |
|---|---|---|
| `user_id` | `str` | Required. Tenant isolation predicate. Same convention as ADR-0017. |
| `period` | `DateRange` | Required. Must satisfy `date_from <= date_to` (enforced by `DateRange.__post_init__`). |
| `account_id` | `UUID \| None` | Optional. `None` means all accounts for this user. When provided, restricts the aggregate to one account. Follows the pattern established in `TransactionFilters` (ADR-0017). |

Returns an empty list (`[]`) when no transactions match — not `None`, not an exception.

**`get_spend_history`**

| Parameter | Type | Rules |
|---|---|---|
| `user_id` | `str` | Required. Tenant isolation predicate. |
| `category_id` | `UUID \| None` | The category to aggregate over time. `None` means "uncategorized" — returns history for `category_id IS NULL` rows only. To retrieve history across all categories (for a trend overview), callers should call `get_spend_by_category` for each period instead. |
| `periods` | `list[DateRange]` | One or more periods. Must be non-empty; raises `ValueError` if empty. No uniqueness or ordering constraint — callers may pass overlapping or unsorted periods. |

Returns one `PeriodSpend` per period in the same order as the input `periods` list, including `PeriodSpend(period=p, categories=[], total_spend=Decimal("0"))` for periods with no matching transactions. The list length always equals `len(periods)`.

### Sign convention and spend definition

"Spend" is defined as the sum of `abs(amount)` for all transactions where `amount < 0` (debits). Credits (`amount > 0`) are excluded entirely from both methods. Zero-amount transactions are also excluded. This matches the convention in the existing `_get_spending_summary` helper and the `Transaction.amount` signed convention from ADR-0016 (debits negative, credits positive).

There is no separate "income" aggregate in this API. If Phase 4 requires income aggregation, that is a new method, not a change to these signatures.

### Uncategorized transactions

Transactions where `category_id IS NULL` are included in both methods. They appear as a `CategorySpend` row with `category_id=None` and `category_name=None`. This is unambiguous at every call site and avoids magic sentinel strings such as `"Uncategorized"`. Callers that render these rows to a user are responsible for choosing a display label.

### Error model

| Condition | Behavior |
|---|---|
| `period.date_from > period.date_to` | `ValueError` raised by `DateRange.__post_init__` before any DB call. |
| `periods` is an empty list | `ValueError("periods must be non-empty")` raised by `get_spend_history`. |
| No matching transactions | Empty `list[CategorySpend]` from `get_spend_by_category`; a `list[PeriodSpend]` with zero-spend entries from `get_spend_history`. Neither raises. |
| DB connectivity or query failure | Propagates as the underlying exception (e.g., `sqlalchemy.exc.OperationalError`). The service does not wrap these — same policy as ADR-0017. |

## SQL shape

The implementation agent must produce queries equivalent to the following. Full SQLAlchemy is not specified here; the patterns below remove all ambiguity about GROUP BY shape, join strategy, and predicate order.

### `get_spend_by_category`

```sql
SELECT
    t.category_id,
    c.name          AS category_name,
    SUM(ABS(t.amount))  AS spend,
    COUNT(*)            AS transaction_count
FROM public.transactions t
LEFT JOIN public.categories c ON c.id = t.category_id
WHERE
    t.user_id    = :user_id
    AND t.date   >= :date_from
    AND t.date   <= :date_to
    AND t.amount  < 0
    -- Optional: AND t.account_id = :account_id  (only when account_id is not None)
GROUP BY t.category_id, c.name
ORDER BY spend DESC;
```

Notes:
- `LEFT JOIN` on `categories` so that `category_id IS NULL` rows still appear (with `category_name = NULL`).
- `WHERE amount < 0` before the aggregate so the SUM never needs a `CASE` expression.
- `GROUP BY t.category_id, c.name` groups null `category_id` rows together correctly because Postgres treats `NULL = NULL` as false in equality but groups NULLs together in GROUP BY.
- `ORDER BY spend DESC` is a convenience default; the returned `list[CategorySpend]` is ordered by descending spend. Callers must not rely on this order being stable across ties; if deterministic tie-breaking matters for tests, a secondary `ORDER BY category_name NULLS LAST` can be appended by the implementation.

### `get_spend_history`

Issue one query per period in the `periods` list. For each period:

```sql
SELECT
    t.category_id,
    c.name              AS category_name,
    SUM(ABS(t.amount))  AS spend,
    COUNT(*)            AS transaction_count
FROM public.transactions t
LEFT JOIN public.categories c ON c.id = t.category_id
WHERE
    t.user_id        = :user_id
    AND t.date       >= :date_from
    AND t.date       <= :date_to
    AND t.amount      < 0
    -- Exactly one of the two predicates below is appended:
    AND t.category_id = :category_id   -- when category_id is not None
    -- OR:
    AND t.category_id IS NULL           -- when category_id is None
GROUP BY t.category_id, c.name;
```

The implementation issues N queries for N periods. A single query with `AND t.date IN (range1 OR range2 ...)` or a lateral join is a valid optimization if the implementation agent chooses it, but only if it produces identical results to N separate queries. The contract specifies results, not the exact query count.

## Index recommendations

The existing indexes from ADR-0016 are:
- `idx_transactions_user_date ON transactions (user_id, date DESC)`
- `idx_transactions_user_category ON transactions (user_id, category_id)`
- `idx_transactions_user_account ON transactions (user_id, account_id)`

For `get_spend_by_category` the dominant predicate is `WHERE user_id = ? AND date >= ? AND date <= ? AND amount < 0`. The existing `idx_transactions_user_date` covers the first three predicates (leading columns `user_id`, `date`) and the planner applies the `amount < 0` filter post-scan. This is sufficient for per-user row counts in the low tens of thousands.

For `get_spend_history` the predicate adds `AND category_id = ?` (or `IS NULL`) to the above. The existing `idx_transactions_user_category` covers `(user_id, category_id)` but not the date range. At the realistic scale of a personal finance app one additional covering index is warranted:

**New index (add in Phase 3c schema migration):**

```sql
CREATE INDEX idx_transactions_user_date_category
    ON public.transactions (user_id, date DESC, category_id);
```

This covering index satisfies `WHERE user_id = ? AND date BETWEEN ? AND ? AND category_id = ?` (or `IS NULL`) with an index-only range scan. The implementation agent MUST include this index in the Phase 3c Alembic migration alongside this ADR.

**No index on `amount`.** A partial index `WHERE amount < 0` combined with `user_id` and `date` would be the most selective option, but it is speculative for current scale. If profiling on production data later shows the `amount < 0` filter is not pushed down efficiently, a follow-up migration can add `CREATE INDEX ... WHERE amount < 0`.

## Consumer wiring — dashboard spending summary

`app/home/routes.py` contains `_get_spending_summary(user_id)`. When `get_spend_by_category` is implemented, this helper must be replaced as follows:

**Before (current):**
```python
from app.transactions.services import TransactionFilters, get_transactions

today = date.today()
month_start = date(today.year, today.month, 1)
filters = TransactionFilters(date_from=month_start, date_to=today, limit=500)
page = get_transactions(user_id, filters)

# Manual accumulation loop...
by_category: dict[str, Decimal] = defaultdict(Decimal)
total = Decimal("0")
for txn in page.items:
    if txn.amount < 0:
        spend = abs(txn.amount)
        total += spend
        label = txn.category_name or "Uncategorized"
        by_category[label] += spend
```

**After:**
```python
from app.transactions.services import DateRange, get_spend_by_category

today = date.today()
period = DateRange(date_from=date(today.year, today.month, 1), date_to=today)
rows = get_spend_by_category(user_id, period)

total = sum(r.spend for r in rows)
top3 = rows[:3]  # already sorted by spend DESC
breakdown = [
    {"label": r.category_name or "Uncategorized", "amount": r.spend}
    for r in top3
]
```

The 500-row cap disappears. The manual sign-check loop disappears. The `_get_spending_summary` function no longer imports from `collections` or performs arithmetic — it maps the service result to the template dict shape.

The `has_transactions` key in the returned dict becomes `bool(rows)` rather than `bool(page.items)`. All other keys (`total_spend`, `breakdown`) remain identical to the template's expectations, so no template change is required.

The `try/except Exception` wrapper in `_get_spending_summary` is preserved as-is to ensure the dashboard degrades gracefully when the DB is unavailable.

## Consequences

- **Positive.** The dashboard spending card stops being silently capped at 500 rows. Users with more than 500 transactions in a month now see correct totals.
- **Positive.** The Budgeting Module (Phase 4) has a stable, typed contract to build against before implementation begins. No further extension is needed to serve actual-vs-budget views.
- **Positive.** `DateRange.for_month(year, month)` gives Phase 4 a one-line constructor for the common budget-month case without hardcoding month-boundary arithmetic in two places.
- **Positive.** Uncategorized transactions are represented as `category_id=None` rows rather than a magic sentinel string — the Budgeting Module can handle them without special-casing a string comparison.
- **Positive.** `transaction_count` on `CategorySpend` is available at no extra query cost and supports future UI elements ("47 coffee transactions this month").
- **Negative.** The new covering index `idx_transactions_user_date_category` adds minor write overhead on every transaction insert. At personal-finance scale this is negligible and the read benefit justifies it.
- **Negative (resolved in Phase 5d).** `get_spend_history` issues N queries for N periods. For a 12-month trend view that is 12 small indexed queries. Acceptable at Phase 3c scale. The Intelligence Dashboard's date range picker made this a live performance issue; [ADR-0042](0042-batched-monthly-spend-query.md) resolves it by adding `get_spend_by_category_monthly` — a single query that groups by `(year, month, category)` across the full range.
- **Negative.** The Phase 3c Alembic migration must be authored and reviewed before this contract can be exercised in production. The implementation agent holds the migration write-lock for that revision.
- **Follow-up.** The implementation agent must add `DateRange`, `CategorySpend`, and `PeriodSpend` to the module docstring's "Public API" list and reference ADR-0023.
- **Follow-up.** The test-writer agent must cover: empty-period result, uncategorized-only month, mixed categorized/uncategorized, `account_id` filter, `get_spend_history` with non-overlapping and overlapping periods, and the `ValueError` cases.
- **Follow-up.** The Phase 3c Alembic migration (revision `0004_aggregation_indexes`) must create `idx_transactions_user_date_category` and reference this ADR. The implementation agent is the single writer for that revision (ADR-0007).
- **Follow-up.** Once `_get_spending_summary` is updated, the `collections.defaultdict` import and the manual accumulation loop in `app/home/routes.py` are dead code and must be removed in the same PR.

## Notes

ADR-0017 listed `get_spend_by_category` and `get_spend_history` as the Phase 3c additions and explicitly deferred their contract to this ADR. The four-method shape of the Transaction Engine read API was complete at the time of writing: `get_transactions`, `get_transaction` (ADR-0017), `get_spend_by_category`, `get_spend_history` (this ADR). Any addition beyond these four requires a new ADR.

**Phase 5d addition — batched monthly spend query ([ADR-0042](0042-batched-monthly-spend-query.md)).**
The Intelligence Dashboard's multi-month widgets (`category_trends`, `category_radar`) exhibited an N+1 query pattern: one `get_spend_by_category` call per month slot. ADR-0042 adds `CategorySpendMonthly` and `get_spend_by_category_monthly` to the exported API surface as a fifth method. The existing four methods are unchanged. See ADR-0042 for the full decision record, SQL shape, and new dataclass definition.

The `DateRange` type is defined in `app/transactions/services.py` (the Transaction Engine module) rather than in a shared utility module. This keeps it co-located with the functions that consume it and avoids creating a shared-utilities module — a pattern that tends to become a catch-all. If Phase 4 or 5 needs an equivalent date-window type, they import `DateRange` from `app.transactions.services` directly, which is consistent with ADR-0003 (all cross-module reads via the Transaction Engine service layer).
