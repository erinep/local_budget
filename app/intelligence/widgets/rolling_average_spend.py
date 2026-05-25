"""Rolling average spend widget.

Answers: "What is my smoothed spending trend over time?"

Public API:
    build_rolling_average_spend(user_id, period_months) -> RollingAverageSpendVM
"""

import datetime
from dataclasses import dataclass
from typing import Optional

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class RollingAverageSpendVM:
    title: str
    labels: list[str]                    # month labels
    monthly_totals: list[float]          # raw monthly spend
    rolling_3m: list[Optional[float]]    # 3-month rolling avg; None for first 2 months
    period_months: int


def build_rolling_average_spend(user_id: str, period_months: int = 12) -> RollingAverageSpendVM:
    """Return monthly spend totals and 3-month rolling average."""
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

    # Oldest first
    ordered = list(reversed(months))
    month_totals: dict[tuple[int, int], float] = {k: 0.0 for k in ordered}

    for txn in all_txns:
        if float(txn.amount) >= 0:
            continue
        key = (txn.date.year, txn.date.month)
        if key in month_totals:
            month_totals[key] += abs(float(txn.amount))

    labels = [datetime.date(y, m, 1).strftime("%b %Y") for y, m in ordered]
    monthly = [round(month_totals[k], 2) for k in ordered]

    rolling: list[Optional[float]] = []
    for i, _ in enumerate(ordered):
        if i < 2:
            rolling.append(None)
        else:
            avg = (monthly[i - 2] + monthly[i - 1] + monthly[i]) / 3.0
            rolling.append(round(avg, 2))

    return RollingAverageSpendVM(
        title="Rolling Average Spend",
        labels=labels,
        monthly_totals=monthly,
        rolling_3m=rolling,
        period_months=period_months,
    )


REGISTRY["rolling_average_spend"] = WidgetDef(
    key="rolling_average_spend",
    assembler=build_rolling_average_spend,
    template="intelligence/widgets/rolling_average_spend.html",
)
