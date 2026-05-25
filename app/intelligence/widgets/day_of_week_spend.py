"""Day of week spend widget — polar area chart of average spend by weekday.

Public API:
    build_day_of_week_spend(user_id, period_months) -> DayOfWeekSpendVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions

_DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass(frozen=True)
class DayOfWeekSpendVM:
    title: str
    labels: list        # ["Mon", "Tue", ..., "Sun"]
    totals: list        # total outflow per day of week across period
    counts: list        # number of distinct transaction days per weekday
    averages: list      # totals[i] / counts[i] if counts[i] > 0 else 0
    period_months: int


def build_day_of_week_spend(user_id: str, period_months: int = 12) -> DayOfWeekSpendVM:
    """Return average spend broken down by day of week."""
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
            limit=page_size,
            offset=offset,
            date_from=date_from,
            date_to=date_to,
        ))
        all_txns.extend(page.items)
        if len(all_txns) >= page.total_count:
            break
        offset += page_size

    # Sum outflows and track distinct days per weekday (0=Mon, 6=Sun)
    dow_totals = [0.0] * 7
    dow_days: list[set] = [set() for _ in range(7)]

    for txn in all_txns:
        if float(txn.amount) >= 0:
            continue
        dow = txn.date.weekday()
        dow_totals[dow] += abs(float(txn.amount))
        dow_days[dow].add(txn.date)

    counts = [len(days) for days in dow_days]
    averages = [
        round(dow_totals[i] / counts[i], 2) if counts[i] > 0 else 0.0
        for i in range(7)
    ]
    totals = [round(t, 2) for t in dow_totals]

    return DayOfWeekSpendVM(
        title="Day of Week Spend",
        labels=_DAY_LABELS,
        totals=totals,
        counts=counts,
        averages=averages,
        period_months=period_months,
    )


REGISTRY["day_of_week_spend"] = WidgetDef(
    key="day_of_week_spend",
    assembler=build_day_of_week_spend,
    template="intelligence/widgets/day_of_week_spend.html",
)
