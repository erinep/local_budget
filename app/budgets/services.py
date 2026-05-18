"""Budgeting Module service layer — ADR-0025.

All functions in this module are the public API for the Budgeting Module.
No other module queries public.budgets directly (ADR-0003).

Actuals are read via app.transactions.services — get_spend_by_category and
get_spend_history. Budget targets are read/written against public.budgets.

PII note: budget amounts and category references are High-sensitivity financial
data. Never log raw amounts or category names. Use structured logging only.

Constants:
    PROPOSAL_LOOKBACK_MONTHS  = 3
    NEAR_LIMIT_THRESHOLD      = Decimal("0.80")  # spend/budget >= this -> NEAR
    OVER_BUDGET_THRESHOLD     = Decimal("1.00")  # spend/budget >  this -> OVER
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy import text

from app.db import get_engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants (ADR-0025, Decision 7 & 8)
# ---------------------------------------------------------------------------

PROPOSAL_LOOKBACK_MONTHS: int = 3
NEAR_LIMIT_THRESHOLD: Decimal = Decimal("0.80")
OVER_BUDGET_THRESHOLD: Decimal = Decimal("1.00")


# ---------------------------------------------------------------------------
# Types (ADR-0025 — Public service API / Types)
# ---------------------------------------------------------------------------

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
    category_name: str           # denormalized from categories table for display
    amount: Decimal              # the budget target; always >= 0
    budget_year: int
    budget_month: int


@dataclass(frozen=True)
class BudgetProgress:
    """A budget target paired with the actual spend for that period."""
    budget: Budget | None        # None when there is spend but no budget set
    category_id: UUID | None
    category_name: str | None    # None only for uncategorized spend
    target: Decimal              # budget.amount, or Decimal("0") if no budget
    actual: Decimal              # from get_spend_by_category; always >= 0
    variance: Decimal            # target - actual; negative means over budget
    pct_used: Decimal            # actual / target * 100; Decimal("0") if target == 0
    status: BudgetStatus


@dataclass(frozen=True)
class ProposedBudget:
    """A budget amount suggested by the proposal engine, not yet persisted."""
    category_id: UUID
    category_name: str
    proposed_amount: Decimal     # rounded to nearest whole dollar
    months_of_data: int          # how many look-back months had any spend
    average_monthly_spend: Decimal  # unrounded, for display


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_status(target: Decimal, actual: Decimal) -> BudgetStatus:
    """Classify spend relative to target per ADR-0025, Decision 8."""
    if target == Decimal("0"):
        return BudgetStatus.OVER if actual > Decimal("0") else BudgetStatus.UNDER

    ratio = actual / target
    if ratio > OVER_BUDGET_THRESHOLD:
        return BudgetStatus.OVER
    if ratio >= NEAR_LIMIT_THRESHOLD:
        return BudgetStatus.NEAR
    return BudgetStatus.UNDER


def _lookback_months(target_year: int, target_month: int, n: int) -> list[tuple[int, int]]:
    """Return n (year, month) tuples preceding target_month, oldest first."""
    months = []
    year, month = target_year, target_month
    for _ in range(n):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        months.append((year, month))
    months.reverse()
    return months


# ---------------------------------------------------------------------------
# Read functions
# ---------------------------------------------------------------------------

def get_budgets(user_id: str, year: int, month: int) -> list[Budget]:
    """Return all budget targets for a user in a given month.

    Returns an empty list if no budgets are set. Never raises on missing data.
    Ordered by category_name ASC.
    """
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT b.id, b.user_id, b.category_id, c.name,"
                " b.amount, b.budget_year, b.budget_month"
                " FROM public.budgets b"
                " JOIN public.categories c ON c.id = b.category_id"
                " WHERE b.user_id = :uid"
                " AND b.budget_year = :y"
                " AND b.budget_month = :m"
                " ORDER BY c.name ASC"
            ),
            {"uid": user_id, "y": year, "m": month},
        ).fetchall()

    return [
        Budget(
            id=UUID(str(row[0])),
            user_id=str(row[1]),
            category_id=UUID(str(row[2])),
            category_name=row[3],
            amount=Decimal(str(row[4])),
            budget_year=int(row[5]),
            budget_month=int(row[6]),
        )
        for row in rows
    ]


def get_budget_progress(user_id: str, year: int, month: int) -> list[BudgetProgress]:
    """Return actual-vs-budget for every relevant category in the given month.

    Calls get_spend_by_category(user_id, DateRange.for_month(year, month))
    and get_budgets(user_id, year, month), then joins by category_id.

    The returned list includes:
    - Categories that have a budget target (even if actual spend is zero).
    - Categories that have actual spend in the period (even if no budget is set;
      these appear with budget=None and target=Decimal("0")).

    Uncategorized spend (category_id=None) is included with budget=None and
    category_name=None. Callers are responsible for rendering a display label.

    Ordering: budgeted categories first (by category_name ASC), then
    unbudgeted-but-spent categories (by actual DESC), then uncategorized.

    Never raises on empty data. Returns an empty list if no budgets and no spend.
    """
    from app.transactions.services import DateRange, get_spend_by_category

    period = DateRange.for_month(year, month)
    spend_rows = get_spend_by_category(user_id, period)
    budget_rows = get_budgets(user_id, year, month)

    # Index budgets by category_id for O(1) lookup
    budget_by_cat: dict[UUID, Budget] = {b.category_id: b for b in budget_rows}
    # Index spend by category_id (None key for uncategorized)
    spend_by_cat: dict[UUID | None, Decimal] = {
        s.category_id: s.spend for s in spend_rows
    }

    result: list[BudgetProgress] = []

    # 1. Budgeted categories (all, with actual spend or zero)
    for budget in sorted(budget_rows, key=lambda b: b.category_name):
        actual = spend_by_cat.get(budget.category_id, Decimal("0"))
        target = budget.amount
        variance = target - actual
        pct_used = (actual / target * Decimal("100")) if target > Decimal("0") else Decimal("0")
        status = _compute_status(target, actual)
        result.append(BudgetProgress(
            budget=budget,
            category_id=budget.category_id,
            category_name=budget.category_name,
            target=target,
            actual=actual,
            variance=variance,
            pct_used=pct_used,
            status=status,
        ))

    budgeted_cat_ids = set(budget_by_cat.keys())

    # 2. Unbudgeted-but-spent (named categories only, not None)
    unbudgeted = [
        s for s in spend_rows
        if s.category_id is not None and s.category_id not in budgeted_cat_ids
    ]
    # Sort by actual DESC
    unbudgeted_sorted = sorted(unbudgeted, key=lambda s: s.spend, reverse=True)
    for s in unbudgeted_sorted:
        target = Decimal("0")
        actual = s.spend
        variance = target - actual
        pct_used = Decimal("0")
        status = _compute_status(target, actual)
        result.append(BudgetProgress(
            budget=None,
            category_id=s.category_id,
            category_name=s.category_name,
            target=target,
            actual=actual,
            variance=variance,
            pct_used=pct_used,
            status=status,
        ))

    # 3. Uncategorized spend (category_id=None)
    if None in spend_by_cat:
        actual = spend_by_cat[None]
        target = Decimal("0")
        variance = target - actual
        status = _compute_status(target, actual)
        result.append(BudgetProgress(
            budget=None,
            category_id=None,
            category_name=None,
            target=target,
            actual=actual,
            variance=variance,
            pct_used=Decimal("0"),
            status=status,
        ))

    return result


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
    from app.transactions.services import DateRange, get_spend_by_category, get_spend_history

    lookback = _lookback_months(target_year, target_month, PROPOSAL_LOOKBACK_MONTHS)

    # Collect all categories with spend in any lookback month
    category_info: dict[UUID, str] = {}  # category_id -> category_name
    for year, month in lookback:
        period = DateRange.for_month(year, month)
        spend_rows = get_spend_by_category(user_id, period)
        for s in spend_rows:
            if s.category_id is not None:
                category_info[s.category_id] = s.category_name or ""

    if not category_info:
        return []

    proposals: list[ProposedBudget] = []

    for category_id, category_name in category_info.items():
        periods = [DateRange.for_month(y, m) for y, m in lookback]
        history = get_spend_history(user_id, category_id, periods)

        # Collect per-month totals for months with any spend
        monthly_totals = [ps.total_spend for ps in history if ps.total_spend > Decimal("0")]
        months_of_data = len(monthly_totals)

        if months_of_data == 0:
            continue

        average = sum(monthly_totals, Decimal("0")) / Decimal(str(months_of_data))
        proposed_amount = Decimal(str(int(average.to_integral_value())))

        proposals.append(ProposedBudget(
            category_id=category_id,
            category_name=category_name,
            proposed_amount=proposed_amount,
            months_of_data=months_of_data,
            average_monthly_spend=average,
        ))

    # Sort by category_name for consistent display
    proposals.sort(key=lambda p: p.category_name)
    return proposals


# ---------------------------------------------------------------------------
# Write functions
# ---------------------------------------------------------------------------

def upsert_budget(
    user_id: str,
    category_id: UUID,
    amount: Decimal,
    year: int,
    month: int,
) -> Budget:
    """Create or update the budget target for a category in a given month.

    Uses INSERT ... ON CONFLICT DO UPDATE so double-submits are idempotent.

    Raises ValueError if amount < 0, month not in 1..12, or year not in 2000..2100.
    Propagates DB exceptions (e.g. FK violation) without wrapping.
    Returns the persisted Budget row after upsert.
    """
    if amount < Decimal("0"):
        raise ValueError("amount must be >= 0")
    if not (1 <= month <= 12):
        raise ValueError("month must be between 1 and 12")
    if not (2000 <= year <= 2100):
        raise ValueError("year must be between 2000 and 2100")

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.budgets"
                " (user_id, category_id, amount, budget_year, budget_month)"
                " VALUES (:uid, :cid, :amount, :year, :month)"
                " ON CONFLICT (user_id, category_id, budget_year, budget_month)"
                " DO UPDATE SET amount = EXCLUDED.amount, updated_at = now()"
            ),
            {
                "uid": user_id,
                "cid": str(category_id),
                "amount": str(amount),
                "year": year,
                "month": month,
            },
        )

    # Re-query to return the full persisted row with category_name
    rows = get_budgets(user_id, year, month)
    for b in rows:
        if b.category_id == category_id:
            return b

    raise RuntimeError("upsert_budget: row not found after insert — this should not happen")


def delete_budget(user_id: str, budget_id: UUID) -> None:
    """Hard-delete a budget row.

    Verifies user_id ownership before deleting. Raises ValueError if the
    budget_id does not exist or does not belong to user_id.
    """
    engine = get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "DELETE FROM public.budgets"
                " WHERE id = :bid AND user_id = :uid"
            ),
            {"bid": str(budget_id), "uid": user_id},
        )
    if result.rowcount == 0:
        raise ValueError("Budget not found or does not belong to this user.")


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
    Returns 0 immediately if proposals is empty.
    """
    if not proposals:
        return 0

    # Determine existing budgets once, outside the transaction
    existing_budgets = get_budgets(user_id, year, month)
    existing_cat_ids: set[UUID] = {b.category_id for b in existing_budgets}

    engine = get_engine()
    written = 0

    with engine.begin() as conn:
        for proposal in proposals:
            if not replace_existing and proposal.category_id in existing_cat_ids:
                continue  # skip — already has a budget for this month

            conn.execute(
                text(
                    "INSERT INTO public.budgets"
                    " (user_id, category_id, amount, budget_year, budget_month)"
                    " VALUES (:uid, :cid, :amount, :year, :month)"
                    " ON CONFLICT (user_id, category_id, budget_year, budget_month)"
                    " DO UPDATE SET amount = EXCLUDED.amount, updated_at = now()"
                ),
                {
                    "uid": user_id,
                    "cid": str(proposal.category_id),
                    "amount": str(proposal.proposed_amount),
                    "year": year,
                    "month": month,
                },
            )
            written += 1

    return written
