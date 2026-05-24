"""Category totals bar chart widget.

Answers: "Where is my money going this period?"

Public API:
    build_category_totals(user_id, period_months) -> CategoryTotalsVM
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import DateRange, get_spend_by_category


@dataclass(frozen=True)
class CategoryTotalItem:
    label: str
    spend: float
    is_uncategorized: bool


@dataclass(frozen=True)
class CategoryTotalsVM:
    title: str
    items: list[CategoryTotalItem]
    period_months: int


def build_category_totals(user_id: str, period_months: int = 12) -> CategoryTotalsVM:
    """Return total spend per category for the last period_months complete months.

    Uncategorized transactions are included and flagged so the chart can
    colour them distinctly.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    year, month = now.year, now.month

    months: list[tuple[int, int]] = []
    for _ in range(period_months):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        months.append((year, month))

    totals: dict[str, float] = {}
    uncategorized_key = "Uncategorized"

    for y, m in months:
        rows = get_spend_by_category(user_id, DateRange.for_month(y, m))
        for row in rows:
            if row.spend <= Decimal("0"):
                continue
            label = row.category_name if row.category_name else uncategorized_key
            totals[label] = totals.get(label, 0.0) + float(row.spend)

    # Categorized items sorted by spend desc; Uncategorized appended last
    categorized = sorted(
        [(label, spend) for label, spend in totals.items() if label != uncategorized_key],
        key=lambda x: x[1],
        reverse=True,
    )
    items = [CategoryTotalItem(label=l, spend=round(s, 2), is_uncategorized=False) for l, s in categorized]

    if uncategorized_key in totals:
        items.append(CategoryTotalItem(
            label=uncategorized_key,
            spend=round(totals[uncategorized_key], 2),
            is_uncategorized=True,
        ))

    return CategoryTotalsVM(
        title="Category Totals",
        items=items,
        period_months=period_months,
    )


REGISTRY["category_totals"] = WidgetDef(
    key="category_totals",
    assembler=build_category_totals,
    template="intelligence/widgets/category_totals.html",
)
