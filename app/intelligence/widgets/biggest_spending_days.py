"""Biggest spending days widget.

Answers: "Which days saw the most spending in the period?"

Public API:
    build_biggest_spending_days(user_id, period_months) -> BigSpendingDaysVM
"""

import datetime
from dataclasses import dataclass
from typing import Optional

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class BigSpendDayItem:
    date_str: str   # "Jan 5" format
    total: float
    transaction_count: int
    top_category: Optional[str]  # category with most spend that day


@dataclass(frozen=True)
class BigSpendingDaysVM:
    title: str
    items: list[BigSpendDayItem]  # top 10, sorted by total desc
    period_months: int


def build_biggest_spending_days(user_id: str, period_months: int = 6) -> BigSpendingDaysVM:
    """Return the top 10 highest-spending days in the period."""
    now = datetime.datetime.now(datetime.timezone.utc)
    year, month = now.year, now.month

    months: list[tuple[int, int]] = []
    for _ in range(period_months):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        months.append((year, month))

    oldest_y, oldest_m = months[-1]
    latest_y, latest_m = months[0]
    date_from = datetime.date(oldest_y, oldest_m, 1)
    if latest_m == 12:
        date_to = datetime.date(latest_y + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        date_to = datetime.date(latest_y, latest_m + 1, 1) - datetime.timedelta(days=1)

    all_txns = []
    offset = 0
    page_size = 200
    while True:
        page = get_transactions(user_id, TransactionFilters(
            limit=page_size, offset=offset, date_from=date_from, date_to=date_to,
        ))
        all_txns.extend(page.items)
        if len(all_txns) >= page.total_count:
            break
        offset += page_size

    # Group by date
    day_totals: dict[datetime.date, float] = {}
    day_counts: dict[datetime.date, int] = {}
    day_cats: dict[datetime.date, dict[str, float]] = {}

    for txn in all_txns:
        if float(txn.amount) >= 0:
            continue
        d = txn.date
        amt = abs(float(txn.amount))
        day_totals[d] = day_totals.get(d, 0.0) + amt
        day_counts[d] = day_counts.get(d, 0) + 1
        cat = txn.category_name or "Uncategorized"
        if d not in day_cats:
            day_cats[d] = {}
        day_cats[d][cat] = day_cats[d].get(cat, 0.0) + amt

    sorted_days = sorted(day_totals.keys(), key=lambda d: day_totals[d], reverse=True)[:10]

    items: list[BigSpendDayItem] = []
    for d in sorted_days:
        cats = day_cats.get(d, {})
        top_cat = max(cats, key=lambda c: cats[c]) if cats else None
        items.append(BigSpendDayItem(
            date_str=d.strftime("%b") + " " + str(d.day),
            total=round(day_totals[d], 2),
            transaction_count=day_counts[d],
            top_category=top_cat,
        ))

    return BigSpendingDaysVM(
        title="Biggest Spending Days",
        items=items,
        period_months=period_months,
    )


REGISTRY["biggest_spending_days"] = WidgetDef(
    key="biggest_spending_days",
    assembler=build_biggest_spending_days,
    template="intelligence/widgets/biggest_spending_days.html",
)
