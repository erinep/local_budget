"""Spend forecast widget.

Answers: "Am I on track to spend more or less than last month?"

Public API:
    build_spend_forecast(user_id) -> SpendForecastVM
"""

import calendar
import datetime
from dataclasses import dataclass
from typing import Optional

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class SpendForecastVM:
    title: str
    labels: list[str]              # day numbers "1".."31" for current month
    actuals: list[Optional[float]] # cumulative spend up to today; None for future days
    forecast: list[Optional[float]]# None for past days; linear projection from today onward
    today_day: int
    days_in_month: int
    actual_to_date: float
    projected_total: float
    last_month_total: float        # for comparison


def build_spend_forecast(user_id: str) -> SpendForecastVM:
    """Return cumulative actuals and linear spend forecast for the current month."""
    today = datetime.date.today()
    year, month = today.year, today.month
    days_in_month = calendar.monthrange(year, month)[1]
    today_day = today.day

    date_from = datetime.date(year, month, 1)
    date_to = today

    # Fetch current month transactions up to today
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

    # Build daily totals for days 1..today_day
    daily: dict[int, float] = {}
    for txn in all_txns:
        if float(txn.amount) >= 0:
            continue
        d = txn.date.day
        daily[d] = daily.get(d, 0.0) + abs(float(txn.amount))

    # Build cumulative actuals
    cumulative = 0.0
    actual_to_date = 0.0
    day_cumulative: list[float] = []
    for d in range(1, today_day + 1):
        cumulative += daily.get(d, 0.0)
        day_cumulative.append(round(cumulative, 2))
    actual_to_date = day_cumulative[-1] if day_cumulative else 0.0

    rate = actual_to_date / today_day if today_day > 0 else 0.0
    projected_total = round(rate * days_in_month, 2)

    # Build actuals list (None for future days)
    actuals: list[Optional[float]] = []
    for d in range(1, days_in_month + 1):
        if d <= today_day:
            actuals.append(day_cumulative[d - 1])
        else:
            actuals.append(None)

    # Build forecast list (None for past days before today)
    forecast: list[Optional[float]] = []
    for d in range(1, days_in_month + 1):
        if d < today_day:
            forecast.append(None)
        else:
            forecast.append(round(rate * d, 2))

    # Fetch last month total
    if month == 1:
        lm_year, lm_month = year - 1, 12
    else:
        lm_year, lm_month = year, month - 1
    lm_days = calendar.monthrange(lm_year, lm_month)[1]
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

    last_month_total = sum(abs(float(t.amount)) for t in lm_txns if float(t.amount) < 0)

    return SpendForecastVM(
        title="Spend Forecast",
        labels=[str(d) for d in range(1, days_in_month + 1)],
        actuals=actuals,
        forecast=forecast,
        today_day=today_day,
        days_in_month=days_in_month,
        actual_to_date=round(actual_to_date, 2),
        projected_total=projected_total,
        last_month_total=round(last_month_total, 2),
    )


REGISTRY["spend_forecast"] = WidgetDef(
    key="spend_forecast",
    assembler=build_spend_forecast,
    template="intelligence/widgets/spend_forecast.html",
)
