"""Category-trends line graph widget.

Answers: "How has spending in each category changed over time?"

Public API:
    build_category_trends(user_id, period_months) -> CategoryTrendsVM
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import DateRange, get_spend_by_category


@dataclass(frozen=True)
class CategoryTrendsVM:
    title: str
    labels: list[str]       # ["Jan 2026", "Feb 2026", ...]
    datasets: list[dict]    # [{"label": cat, "data": [float, ...]}, ...]
    period_months: int


def build_category_trends(user_id: str, period_months: int = 12) -> CategoryTrendsVM:
    """Return per-category spend for each of the last period_months complete months.

    Categories are sorted by total spend descending so the legend lists the
    biggest spenders first. Months with no spend for a category are recorded
    as 0.0.
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
    months = list(reversed(months))

    labels: list[str] = []
    month_keys: list[str] = []
    spend_by_month: dict[str, dict[str, float]] = {}

    for y, m in months:
        label = datetime.date(y, m, 1).strftime("%b %Y")
        mk = f"{y}-{m:02d}"
        labels.append(label)
        month_keys.append(mk)

        rows = get_spend_by_category(user_id, DateRange.for_month(y, m))
        spend_by_month[mk] = {
            (row.category_name or "Uncategorized"): float(row.spend)
            for row in rows
            if row.spend > Decimal("0")
        }

    # Collect all categories and rank by total spend
    totals: dict[str, float] = {}
    for cat_map in spend_by_month.values():
        for cat, amt in cat_map.items():
            totals[cat] = totals.get(cat, 0.0) + amt

    sorted_cats = sorted(totals, key=lambda c: totals[c], reverse=True)

    top_cats = sorted_cats[:7]
    other_cats = sorted_cats[7:]

    datasets = [
        {
            "label": cat,
            "data": [spend_by_month[mk].get(cat, 0.0) for mk in month_keys],
        }
        for cat in top_cats
    ]

    if other_cats:
        datasets.append({
            "label": "Other",
            "data": [
                sum(spend_by_month[mk].get(cat, 0.0) for cat in other_cats)
                for mk in month_keys
            ],
        })

    return CategoryTrendsVM(
        title="Spending by Category",
        labels=labels,
        datasets=datasets,
        period_months=period_months,
    )


REGISTRY["category_trends"] = WidgetDef(
    key="category_trends",
    assembler=build_category_trends,
    template="intelligence/widgets/category_trends.html",
)
