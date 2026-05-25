"""Small purchase drain widget.

Answers: "How much am I spending on small purchases?"

Public API:
    build_small_purchase_drain(user_id, period_months) -> SmallPurchaseDrainVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions

_THRESHOLD = 25.0


@dataclass(frozen=True)
class SmallPurchaseDrainVM:
    title: str
    threshold: float           # 25.0
    total_count: int           # total small transactions in period
    total_spend: float         # total amount
    monthly_labels: list[str]
    monthly_counts: list[int]
    monthly_totals: list[float]
    period_months: int
    avg_per_month: float       # total_spend / period_months


def build_small_purchase_drain(user_id: str, period_months: int = 6) -> SmallPurchaseDrainVM:
    """Return statistics about transactions under $25."""
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

    # Oldest to newest
    ordered = list(reversed(months))
    month_key_set = {(y, m) for y, m in ordered}

    month_counts: dict[tuple[int, int], int] = {k: 0 for k in month_key_set}
    month_totals: dict[tuple[int, int], float] = {k: 0.0 for k in month_key_set}

    for txn in all_txns:
        amt = float(txn.amount)
        if amt >= 0 or abs(amt) >= _THRESHOLD:
            continue
        key = (txn.date.year, txn.date.month)
        if key in month_counts:
            month_counts[key] += 1
            month_totals[key] += abs(amt)

    labels = [datetime.date(y, m, 1).strftime("%b %Y") for y, m in ordered]
    counts_list = [month_counts[k] for k in ordered]
    totals_list = [round(month_totals[k], 2) for k in ordered]

    total_count = sum(counts_list)
    total_spend = round(sum(totals_list), 2)
    avg_per_month = round(total_spend / period_months, 2) if period_months > 0 else 0.0

    return SmallPurchaseDrainVM(
        title="Small Purchase Drain",
        threshold=_THRESHOLD,
        total_count=total_count,
        total_spend=total_spend,
        monthly_labels=labels,
        monthly_counts=counts_list,
        monthly_totals=totals_list,
        period_months=period_months,
        avg_per_month=avg_per_month,
    )


REGISTRY["small_purchase_drain"] = WidgetDef(
    key="small_purchase_drain",
    assembler=build_small_purchase_drain,
    template="intelligence/widgets/small_purchase_drain.html",
)
