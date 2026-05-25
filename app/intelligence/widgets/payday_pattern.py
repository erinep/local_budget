"""Payday pattern widget.

Answers: "Is there a pattern in my spending by day of month?"

Public API:
    build_payday_pattern(user_id, period_months) -> PaydayPatternVM
"""

import calendar
import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class PaydayPatternVM:
    title: str
    labels: list[str]    # ["1", "2", ..., "31"]
    values: list[float]  # avg daily spend for that day-of-month
    counts: list[int]    # how many months had data for that day
    period_months: int


def build_payday_pattern(user_id: str, period_months: int = 6) -> PaydayPatternVM:
    """Return average outflow spend by day-of-month across the period."""
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

    # day_spend[day_of_month] -> total spend
    # day_month_count[day_of_month] -> number of months that have this day
    day_spend: dict[int, float] = {d: 0.0 for d in range(1, 32)}

    for t in all_txns:
        if float(t.amount) >= 0:
            continue
        day_spend[t.date.day] += abs(float(t.amount))

    # Count how many months had each day (based on month length)
    day_month_count: dict[int, int] = {d: 0 for d in range(1, 32)}
    for y, m in months:
        days_in_month = calendar.monthrange(y, m)[1]
        for d in range(1, days_in_month + 1):
            day_month_count[d] += 1

    labels: list[str] = []
    values: list[float] = []
    counts: list[int] = []

    for d in range(1, 32):
        n = day_month_count[d]
        labels.append(str(d))
        values.append(round(day_spend[d] / n, 2) if n > 0 else 0.0)
        counts.append(n)

    return PaydayPatternVM(
        title="Payday Pattern",
        labels=labels,
        values=values,
        counts=counts,
        period_months=period_months,
    )


REGISTRY["payday_pattern"] = WidgetDef(
    key="payday_pattern",
    assembler=build_payday_pattern,
    template="intelligence/widgets/payday_pattern.html",
)
