"""Daily spend average widget.

Answers: "What is my average daily spending rate?"

Public API:
    build_daily_spend_average(user_id, period_months) -> DailySpendAverageVM
"""

import calendar
import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class DailySpendAverageVM:
    title: str
    this_month_daily_avg: float      # actual spend / days elapsed this month
    last_month_daily_avg: float      # last month total / days in last month
    period_avg: float                # period total / total period days
    this_month_label: str            # e.g. "May 2026"
    days_elapsed: int
    sparkline_labels: list[str]      # last period_months month labels
    sparkline_values: list[float]    # daily avg per month
    period_months: int


def build_daily_spend_average(user_id: str, period_months: int = 12) -> DailySpendAverageVM:
    """Return daily spend averages for current month, last month, and rolling period."""
    now = datetime.datetime.now(datetime.timezone.utc)
    year, month = now.year, now.month

    # Build complete months list
    months: list[tuple[int, int]] = []
    y, m = year, month
    for _ in range(period_months):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        months.append((y, m))

    oldest_y, oldest_m = months[-1]
    latest_y, latest_m = months[0]
    date_from = datetime.date(oldest_y, oldest_m, 1)
    if latest_m == 12:
        date_to = datetime.date(latest_y + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        date_to = datetime.date(latest_y, latest_m + 1, 1) - datetime.timedelta(days=1)

    page_size = 200

    # Fetch period transactions
    all_txns = []
    offset = 0
    while True:
        page = get_transactions(user_id, TransactionFilters(
            limit=page_size, offset=offset, date_from=date_from, date_to=date_to,
        ))
        all_txns.extend(page.items)
        if len(all_txns) >= page.total_count:
            break
        offset += page_size

    ordered = list(reversed(months))  # oldest first
    month_totals: dict[tuple[int, int], float] = {k: 0.0 for k in ordered}

    for t in all_txns:
        if float(t.amount) >= 0:
            continue
        key = (t.date.year, t.date.month)
        if key in month_totals:
            month_totals[key] += abs(float(t.amount))

    sparkline_labels = [datetime.date(y, m, 1).strftime("%b %Y") for y, m in ordered]
    sparkline_values: list[float] = []
    total_period_spend = 0.0
    total_period_days = 0

    for y, m in ordered:
        days_in_month = calendar.monthrange(y, m)[1]
        monthly_total = month_totals[(y, m)]
        daily_avg = round(monthly_total / days_in_month, 2)
        sparkline_values.append(daily_avg)
        total_period_spend += monthly_total
        total_period_days += days_in_month

    period_avg = round(total_period_spend / total_period_days, 2) if total_period_days > 0 else 0.0

    # Current month
    today = datetime.date.today()
    days_elapsed = today.day
    cur_date_from = datetime.date(today.year, today.month, 1)
    cur_date_to = today

    cur_txns = []
    offset = 0
    while True:
        page = get_transactions(user_id, TransactionFilters(
            limit=page_size, offset=offset, date_from=cur_date_from, date_to=cur_date_to,
        ))
        cur_txns.extend(page.items)
        if len(cur_txns) >= page.total_count:
            break
        offset += page_size

    cur_total = sum(abs(float(t.amount)) for t in cur_txns if float(t.amount) < 0)
    this_month_daily_avg = round(cur_total / days_elapsed, 2) if days_elapsed > 0 else 0.0
    this_month_label = today.strftime("%b %Y")

    # Last month
    if today.month == 1:
        lm_year, lm_month = today.year - 1, 12
    else:
        lm_year, lm_month = today.year, today.month - 1
    lm_days = calendar.monthrange(lm_year, lm_month)[1]

    # Use data from the already-fetched period if available
    lm_key = (lm_year, lm_month)
    if lm_key in month_totals:
        lm_total = month_totals[lm_key]
    else:
        lm_from = datetime.date(lm_year, lm_month, 1)
        lm_to = datetime.date(lm_year, lm_month, lm_days)
        lm_txns = []
        offset = 0
        while True:
            page = get_transactions(user_id, TransactionFilters(
                limit=page_size, offset=offset, date_from=lm_from, date_to=lm_to,
            ))
            lm_txns.extend(page.items)
            if len(lm_txns) >= page.total_count:
                break
            offset += page_size
        lm_total = sum(abs(float(t.amount)) for t in lm_txns if float(t.amount) < 0)

    last_month_daily_avg = round(lm_total / lm_days, 2)

    return DailySpendAverageVM(
        title="Daily Spend Average",
        this_month_daily_avg=this_month_daily_avg,
        last_month_daily_avg=last_month_daily_avg,
        period_avg=period_avg,
        this_month_label=this_month_label,
        days_elapsed=days_elapsed,
        sparkline_labels=sparkline_labels,
        sparkline_values=sparkline_values,
        period_months=period_months,
    )


REGISTRY["daily_spend_average"] = WidgetDef(
    key="daily_spend_average",
    assembler=build_daily_spend_average,
    template="intelligence/widgets/daily_spend_average.html",
)
