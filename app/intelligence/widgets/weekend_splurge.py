"""Weekend splurge widget.

Answers: "Do I spend more on weekends than weekdays?"

Public API:
    build_weekend_splurge(user_id, period_months) -> WeekendSplurgeVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class WeekendSplurgeVM:
    title: str
    labels: list[str]            # month labels
    weekday_totals: list[float]  # Mon-Fri spend per month
    weekend_totals: list[float]  # Sat-Sun spend per month
    weekend_pcts: list[float]    # weekend / total * 100 per month
    period_months: int
    avg_weekend_pct: float       # average across all months


def build_weekend_splurge(user_id: str, period_months: int = 6) -> WeekendSplurgeVM:
    """Return weekday vs weekend spend breakdown per month."""
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

    ordered = list(reversed(months))
    weekday_map: dict[tuple[int, int], float] = {k: 0.0 for k in ordered}
    weekend_map: dict[tuple[int, int], float] = {k: 0.0 for k in ordered}

    for t in all_txns:
        if float(t.amount) >= 0:
            continue
        key = (t.date.year, t.date.month)
        if key not in weekday_map:
            continue
        amt = abs(float(t.amount))
        if t.date.weekday() >= 5:  # Saturday=5, Sunday=6
            weekend_map[key] += amt
        else:
            weekday_map[key] += amt

    labels = [datetime.date(y, m, 1).strftime("%b %Y") for y, m in ordered]
    weekday_totals = [round(weekday_map[k], 2) for k in ordered]
    weekend_totals = [round(weekend_map[k], 2) for k in ordered]
    weekend_pcts: list[float] = []

    for k in ordered:
        total = weekday_map[k] + weekend_map[k]
        pct = round(weekend_map[k] / total * 100.0, 1) if total > 0 else 0.0
        weekend_pcts.append(pct)

    avg_weekend_pct = round(sum(weekend_pcts) / len(weekend_pcts), 1) if weekend_pcts else 0.0

    return WeekendSplurgeVM(
        title="Weekend Splurge",
        labels=labels,
        weekday_totals=weekday_totals,
        weekend_totals=weekend_totals,
        weekend_pcts=weekend_pcts,
        period_months=period_months,
        avg_weekend_pct=avg_weekend_pct,
    )


REGISTRY["weekend_splurge"] = WidgetDef(
    key="weekend_splurge",
    assembler=build_weekend_splurge,
    template="intelligence/widgets/weekend_splurge.html",
)
