"""Budget win rate widget.

Answers: "How often do I stay under budget for each category?"

Public API:
    build_budget_win_rate(user_id, period_months) -> BudgetWinRateVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.budgets.services import BudgetStatus, get_budget_progress


@dataclass(frozen=True)
class BudgetWinRateItem:
    category_name: str
    under_count: int      # months under budget
    total_months: int     # months with a budget set
    win_rate: float       # under_count / total_months * 100
    current_streak: int   # consecutive recent months under budget


@dataclass(frozen=True)
class BudgetWinRateVM:
    title: str
    items: list[BudgetWinRateItem]  # sorted by win_rate desc
    period_months: int


def build_budget_win_rate(user_id: str, period_months: int = 6) -> BudgetWinRateVM:
    """Return win rate and streak per budgeted category."""
    now = datetime.datetime.now(datetime.timezone.utc)
    year, month = now.year, now.month

    months: list[tuple[int, int]] = []
    for _ in range(period_months):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        months.append((year, month))

    # months[0] = most recent, months[-1] = oldest
    # month_results[cat] -> list of (is_under, month_index) most_recent first
    cat_results: dict[str, list[bool]] = {}

    for idx, (y, m) in enumerate(months):
        progress_list = get_budget_progress(user_id, y, m)
        for progress in progress_list:
            cat = progress.category_name
            if cat is None:
                continue
            if progress.budget is None:
                continue
            is_under = progress.status == BudgetStatus.UNDER
            if cat not in cat_results:
                cat_results[cat] = []
            cat_results[cat].append(is_under)

    items: list[BudgetWinRateItem] = []
    for cat, results in cat_results.items():
        total = len(results)
        under_count = sum(1 for r in results if r)
        win_rate = round(under_count / total * 100, 1) if total > 0 else 0.0

        # Streak: count consecutive True values from start of list (most recent)
        streak = 0
        for r in results:
            if r:
                streak += 1
            else:
                break

        items.append(BudgetWinRateItem(
            category_name=cat,
            under_count=under_count,
            total_months=total,
            win_rate=win_rate,
            current_streak=streak,
        ))

    items.sort(key=lambda x: x.win_rate, reverse=True)

    return BudgetWinRateVM(
        title="Budget Win Rate",
        items=items,
        period_months=period_months,
    )


REGISTRY["budget_win_rate"] = WidgetDef(
    key="budget_win_rate",
    assembler=build_budget_win_rate,
    template="intelligence/widgets/budget_win_rate.html",
)
