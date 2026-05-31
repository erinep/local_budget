"""Category-trends line graph widget.

Answers: "How has spending in each category changed over time?"

Public API:
    build_category_trends(user_id, period_months) -> CategoryTrendsVM
"""

import calendar
import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import DateRange, get_spend_by_category_monthly


@dataclass(frozen=True)
class CategoryTrendsVM:
    title: str
    labels: list[str]       # ["Jan 2026", "Feb 2026", ..., "May 2026 (MTD)"]
    datasets: list[dict]    # [{"label": cat, "data": [float, ...]}, ...]
    period_months: int


def build_category_trends(user_id: str, period_months: int = 12) -> CategoryTrendsVM:
    """Return per-category spend for each of the last period_months complete months
    plus the current month (MTD), using a single batched query.

    Categories are sorted by total spend descending so the legend lists the
    biggest spenders first. Months with no spend for a category are recorded
    as 0.0.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    cur_year, cur_month = now.year, now.month

    # Build ordered list of (year, month) slots: complete prior months + current MTD
    slots: list[tuple[int, int]] = []
    y, m = cur_year, cur_month
    for _ in range(period_months):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        slots.append((y, m))
    slots = list(reversed(slots))
    slots.append((cur_year, cur_month))  # current month as MTD

    # Single query spanning the full range
    oldest_y, oldest_m = slots[0]
    last_day = calendar.monthrange(cur_year, cur_month)[1]
    date_from = datetime.date(oldest_y, oldest_m, 1)
    date_to = datetime.date(cur_year, cur_month, last_day)

    all_rows = get_spend_by_category_monthly(user_id, DateRange(date_from, date_to))

    # Index results by "YYYY-MM" key
    spend_by_month: dict[str, dict[str, float]] = {}
    cat_ids: dict[str, str | None] = {}

    for row in all_rows:
        mk = f"{row.year}-{row.month:02d}"
        cat = row.category_name or "Uncategorized"
        spend_by_month.setdefault(mk, {})[cat] = float(row.spend)
        if cat not in cat_ids:
            cat_ids[cat] = str(row.category_id) if row.category_id else None

    # Build labels and month_keys in slot order
    labels: list[str] = []
    month_keys: list[str] = []
    for i, (y, m) in enumerate(slots):
        is_current = (i == len(slots) - 1)
        base_label = datetime.date(y, m, 1).strftime("%b %Y")
        label = f"{base_label} (MTD)" if is_current else base_label
        mk = f"{y}-{m:02d}"
        labels.append(label)
        month_keys.append(mk)
        spend_by_month.setdefault(mk, {})  # ensure key exists for months with no data

    # Rank categories by total spend across all months
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
