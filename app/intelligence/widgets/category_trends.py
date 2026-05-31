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
    """Return per-category spend for each of the last period_months complete months
    plus the current month (MTD).

    Categories are sorted by total spend descending so the legend lists the
    biggest spenders first. Months with no spend for a category are recorded
    as 0.0.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    year, month = now.year, now.month

    # Build the list of complete prior months
    months: list[tuple[int, int]] = []
    y, m = year, month
    for _ in range(period_months):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        months.append((y, m))
    months = list(reversed(months))

    # Append current month as MTD
    months.append((year, month))

    labels: list[str] = []
    month_keys: list[str] = []
    spend_by_month: dict[str, dict[str, float]] = {}
    cat_ids: dict[str, str | None] = {}  # category_name → UUID string

    for i, (y, m) in enumerate(months):
        is_current = (i == len(months) - 1)
        base_label = datetime.date(y, m, 1).strftime("%b %Y")
        label = f"{base_label} (MTD)" if is_current else base_label
        mk = f"{y}-{m:02d}"
        labels.append(label)
        month_keys.append(mk)

        rows = get_spend_by_category(user_id, DateRange.for_month(y, m))  # for current month, date_to is end-of-month; future dates have no transactions
        spend_by_month[mk] = {
            (row.category_name or "Uncategorized"): float(row.spend)
            for row in rows
            if row.spend > Decimal("0")
        }
        for row in rows:
            cat = row.category_name or "Uncategorized"
            if cat not in cat_ids:
                cat_ids[cat] = str(row.category_id) if row.category_id else None

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
            "category_id": cat_ids.get(cat),
            "data": [spend_by_month[mk].get(cat, 0.0) for mk in month_keys],
        }
        for cat in top_cats
    ]

    if other_cats:
        datasets.append({
            "label": "Other",
            "category_id": None,
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
