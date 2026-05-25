"""Month-to-date budget progress widget.

Shows actual vs. target with projected end-of-month spend for each budgeted category.

Public API:
    build_budget_progress_mtd(user_id, period_months) -> BudgetProgressMTDVM
"""

import calendar
import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.budgets.services import get_budget_progress


@dataclass(frozen=True)
class BudgetProgressMTDItem:
    category_name: str
    target: float
    actual: float
    projected: float         # actual * (days_in_month / days_elapsed)
    pct_actual: float        # actual / target * 100, raw (can exceed 100)
    pct_projected: float     # projected / target * 100, raw (can exceed 100)
    status: str              # 'under', 'near', 'over', 'projected_over'


@dataclass(frozen=True)
class BudgetProgressMTDVM:
    title: str
    items: list              # list[BudgetProgressMTDItem] sorted by pct_actual desc
    current_month_label: str  # e.g. "May 2026"
    days_elapsed: int
    days_in_month: int
    pct_of_month: float       # days_elapsed / days_in_month * 100


def build_budget_progress_mtd(user_id: str, period_months: int = 12) -> BudgetProgressMTDVM:
    """Return MTD budget progress with end-of-month projections.

    period_months is accepted for interface compatibility but ignored — this
    widget always shows the current calendar month.
    """
    today = datetime.date.today()
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_elapsed = today.day
    pct_of_month = round(days_elapsed / days_in_month * 100, 1)
    current_month_label = today.strftime("%b %Y")

    budget_rows = get_budget_progress(user_id, today.year, today.month)

    items: list[BudgetProgressMTDItem] = []
    for row in budget_rows:
        target = float(row.target)
        actual = float(row.actual)

        if target <= 0:
            continue

        projected = actual * (days_in_month / days_elapsed) if days_elapsed > 0 else actual
        projected = round(projected, 2)

        pct_actual = round(actual / target * 100, 1) if target > 0 else 0.0
        pct_projected = round(projected / target * 100, 1) if target > 0 else 0.0

        if actual / target > 1.0:
            status = "over"
        elif projected / target > 1.0:
            status = "projected_over"
        elif actual / target >= 0.8:
            status = "near"
        else:
            status = "under"

        category_name = row.category_name or "Uncategorized"

        items.append(BudgetProgressMTDItem(
            category_name=category_name,
            target=round(target, 2),
            actual=round(actual, 2),
            projected=projected,
            pct_actual=pct_actual,
            pct_projected=pct_projected,
            status=status,
        ))

    items.sort(key=lambda x: x.pct_actual, reverse=True)

    return BudgetProgressMTDVM(
        title="Budget Progress",
        items=items,
        current_month_label=current_month_label,
        days_elapsed=days_elapsed,
        days_in_month=days_in_month,
        pct_of_month=pct_of_month,
    )


REGISTRY["budget_progress_mtd"] = WidgetDef(
    key="budget_progress_mtd",
    assembler=build_budget_progress_mtd,
    template="intelligence/widgets/budget_progress_mtd.html",
)
