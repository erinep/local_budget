"""Category-trends line graph widget.

Answers: "How has spending in each category changed over time?"

Public API:
    build_category_trends(user_id, period_months, granularity) -> CategoryTrendsVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import DateRange, get_spend_by_category_grouped

_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass(frozen=True)
class CategoryTrendsVM:
    title: str
    labels: list[str]       # display labels for the x-axis
    dates: list[str]        # "YYYY-MM-DD" period starts — used by JS for click-through URLs
    datasets: list[dict]    # [{"label": cat, "data": [float, ...], "category_id": id|None}]
    period_months: int
    granularity: str        # "day", "week", or "month"


def _enumerate_slots(
    granularity: str,
    date_from: datetime.date,
    date_to: datetime.date,
) -> list[datetime.date]:
    """Return ordered period_start dates covering [date_from, date_to]."""
    slots: list[datetime.date] = []
    if granularity == "day":
        d = date_from
        while d <= date_to:
            slots.append(d)
            d += datetime.timedelta(days=1)
    elif granularity == "week":
        # Snap to Monday on or before date_from (ISO week start)
        week_start = date_from - datetime.timedelta(days=date_from.weekday())
        while week_start <= date_to:
            slots.append(week_start)
            week_start += datetime.timedelta(weeks=1)
    else:  # month
        y, m = date_from.year, date_from.month
        while (y, m) <= (date_to.year, date_to.month):
            slots.append(datetime.date(y, m, 1))
            m += 1
            if m > 12:
                m = 1
                y += 1
    return slots


def _slot_label(granularity: str, slot: datetime.date, is_mtd: bool) -> str:
    if granularity == "month":
        label = f"{_MONTH_NAMES[slot.month - 1]} {slot.year}"
        return f"{label} (MTD)" if is_mtd else label
    else:
        # "Jan 5" — no leading zero, no year needed within a single chart
        return f"{_MONTH_NAMES[slot.month - 1]} {slot.day}"


def build_category_trends(
    user_id: str,
    period_months: int = 12,
    granularity: str = "month",
) -> CategoryTrendsVM:
    """Return per-category spend bucketed by granularity over the requested window.

    period_months=0 means the current calendar month only.
    period_months=N means N prior complete months plus the current month (MTD).
    granularity controls the bucket size: "day", "week", or "month".
    A single DB query covers the whole range; Python pivots into per-slot series.
    """
    if granularity not in ("day", "week", "month"):
        granularity = "month"

    today = datetime.date.today()
    cur_year, cur_month = today.year, today.month

    # Compute the query date range
    if period_months == 0:
        date_from = datetime.date(cur_year, cur_month, 1)
    else:
        y, m = cur_year, cur_month
        for _ in range(period_months):
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        date_from = datetime.date(y, m, 1)
    date_to = today

    # Single query for the full range
    all_rows = get_spend_by_category_grouped(
        user_id, DateRange(date_from, date_to), granularity
    )

    # Index rows by period_start date
    spend_by_slot: dict[datetime.date, dict[str, float]] = {}
    cat_ids: dict[str, str | None] = {}

    for row in all_rows:
        cat = row.category_name or "Uncategorized"
        spend_by_slot.setdefault(row.period_start, {})[cat] = float(row.spend)
        if cat not in cat_ids:
            cat_ids[cat] = str(row.category_id) if row.category_id else None

    # Enumerate all slots in range order (includes zero-spend slots)
    slots = _enumerate_slots(granularity, date_from, date_to)
    for slot in slots:
        spend_by_slot.setdefault(slot, {})

    # Build labels and ISO date strings
    labels: list[str] = []
    dates: list[str] = []
    for slot in slots:
        is_mtd = (
            granularity == "month"
            and slot.year == cur_year
            and slot.month == cur_month
        )
        labels.append(_slot_label(granularity, slot, is_mtd))
        dates.append(slot.isoformat())

    # Rank categories by total spend
    totals: dict[str, float] = {}
    for cat_map in spend_by_slot.values():
        for cat, amt in cat_map.items():
            totals[cat] = totals.get(cat, 0.0) + amt

    sorted_cats = sorted(totals, key=lambda c: totals[c], reverse=True)
    top_cats = sorted_cats[:7]
    other_cats = sorted_cats[7:]

    datasets = [
        {
            "label": cat,
            "category_id": cat_ids.get(cat),
            "data": [spend_by_slot[slot].get(cat, 0.0) for slot in slots],
        }
        for cat in top_cats
    ]

    if other_cats:
        datasets.append({
            "label": "Other",
            "category_id": None,
            "data": [
                sum(spend_by_slot[slot].get(cat, 0.0) for cat in other_cats)
                for slot in slots
            ],
        })

    return CategoryTrendsVM(
        title="Spending by Category",
        labels=labels,
        dates=dates,
        datasets=datasets,
        period_months=period_months,
        granularity=granularity,
    )


REGISTRY["category_trends"] = WidgetDef(
    key="category_trends",
    assembler=build_category_trends,
    template="intelligence/widgets/category_trends.html",
)
