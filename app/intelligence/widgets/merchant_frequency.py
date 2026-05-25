"""Merchant frequency widget.

Answers: "Which merchants do I visit most often?"

Public API:
    build_merchant_frequency(user_id, period_months) -> MerchantFrequencyVM
"""

import datetime
from dataclasses import dataclass
from typing import Optional

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class MerchantFrequencyItem:
    description: str      # exact description from transaction
    visit_count: int
    total_spend: float
    category_name: Optional[str]
    avg_amount: float


@dataclass(frozen=True)
class MerchantFrequencyVM:
    title: str
    items: list[MerchantFrequencyItem]  # top 15 by visit_count
    period_months: int


def build_merchant_frequency(user_id: str, period_months: int = 6) -> MerchantFrequencyVM:
    """Return the top 15 most-visited merchants by outflow transaction count."""
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

    counts: dict[str, int] = {}
    totals: dict[str, float] = {}
    categories: dict[str, Optional[str]] = {}

    for txn in all_txns:
        if float(txn.amount) >= 0:
            continue
        desc = txn.description
        counts[desc] = counts.get(desc, 0) + 1
        totals[desc] = totals.get(desc, 0.0) + abs(float(txn.amount))
        categories[desc] = txn.category_name

    top = sorted(counts, key=lambda d: counts[d], reverse=True)[:15]
    items = [
        MerchantFrequencyItem(
            description=desc,
            visit_count=counts[desc],
            total_spend=round(totals[desc], 2),
            category_name=categories[desc],
            avg_amount=round(totals[desc] / counts[desc], 2),
        )
        for desc in top
    ]

    return MerchantFrequencyVM(
        title="Merchant Frequency",
        items=items,
        period_months=period_months,
    )


REGISTRY["merchant_frequency"] = WidgetDef(
    key="merchant_frequency",
    assembler=build_merchant_frequency,
    template="intelligence/widgets/merchant_frequency.html",
)
