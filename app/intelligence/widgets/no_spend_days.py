"""No-spend days widget.

Answers: "How many days per month do I avoid spending anything?"

Public API:
    build_no_spend_days(user_id, period_months) -> NoSpendDaysVM
"""

import calendar
import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class NoSpendDaysVM:
    title: str
    labels: list[str]   # month labels oldest first
    counts: list[int]   # no-spend day count per month
    period_months: int
    best_month: str     # label of month with most no-spend days
    best_count: int


def build_no_spend_days(user_id: str, period_months: int = 6) -> NoSpendDaysVM:
    """Return count of days with zero outflow transactions per month."""
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

    # Build set of (year, month, day) that have outflow transactions
    spend_days: set[tuple[int, int, int]] = set()
    for txn in all_txns:
        if float(txn.amount) < 0:
            spend_days.add((txn.date.year, txn.date.month, txn.date.day))

    # Oldest to newest for display
    ordered = list(reversed(months))
    labels: list[str] = []
    counts: list[int] = []

    for y, m in ordered:
        label = datetime.date(y, m, 1).strftime("%b %Y")
        days_in_month = calendar.monthrange(y, m)[1]
        spend_count = sum(
            1 for d in range(1, days_in_month + 1) if (y, m, d) in spend_days
        )
        no_spend = days_in_month - spend_count
        labels.append(label)
        counts.append(no_spend)

    if counts:
        best_idx = counts.index(max(counts))
        best_month = labels[best_idx]
        best_count = counts[best_idx]
    else:
        best_month = ""
        best_count = 0

    return NoSpendDaysVM(
        title="No-Spend Days",
        labels=labels,
        counts=counts,
        period_months=period_months,
        best_month=best_month,
        best_count=best_count,
    )


REGISTRY["no_spend_days"] = WidgetDef(
    key="no_spend_days",
    assembler=build_no_spend_days,
    template="intelligence/widgets/no_spend_days.html",
)
