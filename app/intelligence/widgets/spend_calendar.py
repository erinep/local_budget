"""Spend calendar widget — GitHub-style heatmap of daily spend over 365 days.

Public API:
    build_spend_calendar(user_id, period_months) -> SpendCalendarVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class SpendCalendarDay:
    date_str: str   # e.g. "Jan 15" for tooltip
    amount: float
    level: int      # 0=no spend, 1-4 = quartile intensity


@dataclass(frozen=True)
class SpendCalendarVM:
    title: str
    weeks: list      # weeks[col][row=dow 0=Mon..6=Sun], each element is SpendCalendarDay or None
    month_markers: list  # list of [col_index, month_abbr]
    period_days: int
    max_day_spend: float


def build_spend_calendar(user_id: str, period_months: int = 12) -> SpendCalendarVM:
    """Return 365-day spend heatmap data.

    period_months is accepted for interface compatibility but ignored — this
    widget always shows the trailing 365 days.
    """
    today = datetime.date.today()
    date_from = today - datetime.timedelta(days=364)
    date_to = today

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

    # Sum outflow amounts by date
    spend_by_date: dict[datetime.date, float] = {}
    for txn in all_txns:
        if float(txn.amount) >= 0:
            continue
        spend_by_date[txn.date] = spend_by_date.get(txn.date, 0.0) + abs(float(txn.amount))

    # Compute quartile thresholds from days that have spend
    spend_values = sorted(spend_by_date.values())
    max_day_spend = spend_values[-1] if spend_values else 0.0

    def _level(amount: float) -> int:
        if amount <= 0 or not spend_values:
            return 0
        n = len(spend_values)
        q1 = spend_values[n // 4]
        q2 = spend_values[n // 2]
        q3 = spend_values[(3 * n) // 4]
        if amount <= q1:
            return 1
        if amount <= q2:
            return 2
        if amount <= q3:
            return 3
        return 4

    # Start grid from the Monday on or before date_from
    # weekday() 0=Mon, 6=Sun
    start_dow = date_from.weekday()  # how many days since Monday
    grid_start = date_from - datetime.timedelta(days=start_dow)

    # Grid end: Sunday on or after date_to
    end_dow = date_to.weekday()
    days_to_sunday = (6 - end_dow) % 7
    grid_end = date_to + datetime.timedelta(days=days_to_sunday)

    total_days = (grid_end - grid_start).days + 1
    num_weeks = total_days // 7

    weeks: list[list] = []
    month_markers: list = []
    seen_months: set = set()

    for col in range(num_weeks):
        week: list = []
        week_start = grid_start + datetime.timedelta(weeks=col)
        for dow in range(7):
            day_date = week_start + datetime.timedelta(days=dow)
            if day_date < date_from or day_date > date_to:
                week.append(None)
            else:
                amount = spend_by_date.get(day_date, 0.0)
                date_str = day_date.strftime("%b") + " " + str(day_date.day)
                week.append(SpendCalendarDay(
                    date_str=date_str,
                    amount=round(amount, 2),
                    level=_level(amount),
                ))
                # Track month markers at column where each month first appears
                month_key = (day_date.year, day_date.month)
                if month_key not in seen_months and day_date.day <= 7:
                    seen_months.add(month_key)
                    month_markers.append([col, day_date.strftime("%b")])
        weeks.append(week)

    return SpendCalendarVM(
        title="Spend Calendar",
        weeks=weeks,
        month_markers=month_markers,
        period_days=365,
        max_day_spend=round(max_day_spend, 2),
    )


REGISTRY["spend_calendar"] = WidgetDef(
    key="spend_calendar",
    assembler=build_spend_calendar,
    template="intelligence/widgets/spend_calendar.html",
)
