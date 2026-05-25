"""Budget trend heatmap widget.

Answers: "Which categories do I consistently overspend, and is my budget
discipline improving or getting worse over time?"

Renders a category × month heatmap where each cell is coloured by
BudgetStatus (UNDER / NEAR / OVER). Only categories with a standing budget
target in at least one look-back month are included.

Public API:
    build_budget_trend(user_id, period_months) -> BudgetTrendVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef


@dataclass(frozen=True)
class BudgetTrendCell:
    status: str      # 'under' | 'near' | 'over' | 'no_data'
    pct_used: float
    actual: float


@dataclass(frozen=True)
class BudgetTrendRow:
    category_name: str
    cells: list[BudgetTrendCell]  # oldest month first


@dataclass(frozen=True)
class BudgetTrendVM:
    title: str
    month_labels: list[str]
    rows: list[BudgetTrendRow]
    period_months: int


def build_budget_trend(user_id: str, period_months: int = 6) -> BudgetTrendVM:
    from app.budgets.services import BudgetStatus, get_budget_progress

    now = datetime.datetime.now(datetime.timezone.utc)
    year, month = now.year, now.month

    months: list[tuple[int, int]] = []
    for _ in range(period_months):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        months.append((year, month))
    months.reverse()  # oldest first

    month_labels = [
        datetime.date(y, m, 1).strftime("%b %Y")
        for y, m in months
    ]

    monthly_progress: list[dict[str, tuple]] = []
    budgeted_categories: dict[str, None] = {}

    for y, m in months:
        rows = get_budget_progress(user_id, y, m)
        month_data: dict[str, tuple] = {}
        for row in rows:
            if row.target <= 0:
                continue
            name = row.category_name or "Uncategorized"
            budgeted_categories[name] = None
            month_data[name] = (row.status, float(row.pct_used), float(row.actual))
        monthly_progress.append(month_data)

    _STATUS_MAP = {
        BudgetStatus.UNDER: "under",
        BudgetStatus.NEAR:  "near",
        BudgetStatus.OVER:  "over",
    }

    rows_out: list[BudgetTrendRow] = []
    for cat_name in budgeted_categories:
        cells: list[BudgetTrendCell] = []
        for month_data in monthly_progress:
            if cat_name in month_data:
                status_enum, pct, actual = month_data[cat_name]
                cells.append(BudgetTrendCell(
                    status=_STATUS_MAP.get(status_enum, "no_data"),
                    pct_used=round(pct, 1),
                    actual=round(actual, 2),
                ))
            else:
                cells.append(BudgetTrendCell(status="no_data", pct_used=0.0, actual=0.0))
        rows_out.append(BudgetTrendRow(category_name=cat_name, cells=cells))

    rows_out.sort(key=lambda r: r.category_name)

    return BudgetTrendVM(
        title="Budget Trend",
        month_labels=month_labels,
        rows=rows_out,
        period_months=period_months,
    )


REGISTRY["budget_trend"] = WidgetDef(
    key="budget_trend",
    assembler=build_budget_trend,
    template="intelligence/widgets/budget_trend.html",
)
