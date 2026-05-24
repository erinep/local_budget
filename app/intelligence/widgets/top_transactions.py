"""Top transactions widget.

Answers: "What were my biggest individual spends this period?"

Public API:
    build_top_transactions(user_id, period_months, limit) -> TopTransactionsVM
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class TopTransactionItem:
    rank: int
    description: str
    category_name: str | None
    amount: float
    date: datetime.date


@dataclass(frozen=True)
class TopTransactionsVM:
    title: str
    items: list[TopTransactionItem]
    period_months: int
    limit: int


def build_top_transactions(user_id: str, period_months: int = 12, limit: int = 20) -> TopTransactionsVM:
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

    outflows = [t for t in all_txns if float(t.amount) < 0]
    outflows.sort(key=lambda t: t.amount)  # most negative first

    items = [
        TopTransactionItem(
            rank=i + 1,
            description=t.description,
            category_name=t.category_name,
            amount=round(abs(float(t.amount)), 2),
            date=t.date,
        )
        for i, t in enumerate(outflows[:limit])
    ]

    return TopTransactionsVM(
        title="Top Transactions",
        items=items,
        period_months=period_months,
        limit=limit,
    )


REGISTRY["top_transactions"] = WidgetDef(
    key="top_transactions",
    assembler=build_top_transactions,
    template="intelligence/widgets/top_transactions.html",
)
