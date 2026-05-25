"""Transaction histogram widget.

Answers: "How are my transactions distributed by dollar amount?"

Public API:
    build_transaction_histogram(user_id, period_months) -> TransactionHistogramVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class TransactionHistogramVM:
    title: str
    labels: list[str]   # ["$0-10", "$10-25", "$25-50", "$50-100", "$100-250", "$250+"]
    counts: list[int]
    totals: list[float]
    period_months: int


_BUCKETS = [
    ("$0-10",    0,   10),
    ("$10-25",   10,  25),
    ("$25-50",   25,  50),
    ("$50-100",  50,  100),
    ("$100-250", 100, 250),
    ("$250+",    250, float("inf")),
]


def build_transaction_histogram(user_id: str, period_months: int = 6) -> TransactionHistogramVM:
    """Return count and total spend per dollar-amount bucket."""
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

    counts = [0] * len(_BUCKETS)
    totals = [0.0] * len(_BUCKETS)

    for txn in all_txns:
        amt = float(txn.amount)
        if amt >= 0:
            continue
        abs_amt = abs(amt)
        for i, (_, lo, hi) in enumerate(_BUCKETS):
            if lo <= abs_amt < hi:
                counts[i] += 1
                totals[i] += abs_amt
                break

    return TransactionHistogramVM(
        title="Transaction Size Distribution",
        labels=[b[0] for b in _BUCKETS],
        counts=counts,
        totals=[round(t, 2) for t in totals],
        period_months=period_months,
    )


REGISTRY["transaction_histogram"] = WidgetDef(
    key="transaction_histogram",
    assembler=build_transaction_histogram,
    template="intelligence/widgets/transaction_histogram.html",
)
