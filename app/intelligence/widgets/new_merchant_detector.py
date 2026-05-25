"""New merchant detector widget.

Answers: "Which merchants did I visit for the first time this month?"

Public API:
    build_new_merchant_detector(user_id, period_months) -> NewMerchantDetectorVM
"""

import datetime
from dataclasses import dataclass
from typing import Optional

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class NewMerchantItem:
    description: str
    category_name: Optional[str]
    first_seen_str: str   # "Jan 5" format
    amount: float         # amount of first transaction
    total_spend: float    # total if visited multiple times this period


@dataclass(frozen=True)
class NewMerchantDetectorVM:
    title: str
    items: list[NewMerchantItem]  # sorted by first_seen desc (most recent), max 20
    period_months: int
    new_count: int


def build_new_merchant_detector(user_id: str, period_months: int = 6) -> NewMerchantDetectorVM:
    """Detect merchants seen for the first time in the most recent complete month."""
    now = datetime.datetime.now(datetime.timezone.utc)
    year, month = now.year, now.month

    months: list[tuple[int, int]] = []
    for _ in range(period_months):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        months.append((year, month))

    # months[0] = most recent, months[1..N] = older
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

    # Split into current month vs. prior months
    current_month_key = (latest_y, latest_m)
    prior_descriptions: set[str] = set()
    current_txns: list = []

    for t in all_txns:
        if float(t.amount) >= 0:
            continue
        key = (t.date.year, t.date.month)
        if key == current_month_key:
            current_txns.append(t)
        else:
            prior_descriptions.add(t.description)

    # New merchants: descriptions in current month not seen in prior months
    new_desc: dict[str, list] = {}
    for t in current_txns:
        if t.description not in prior_descriptions:
            new_desc.setdefault(t.description, []).append(t)

    items: list[NewMerchantItem] = []
    for desc, txns in new_desc.items():
        txns_sorted = sorted(txns, key=lambda t: t.date)
        first = txns_sorted[0]
        total = sum(abs(float(t.amount)) for t in txns)
        items.append(NewMerchantItem(
            description=desc,
            category_name=first.category_name,
            first_seen_str=first.date.strftime("%b") + " " + str(first.date.day),
            amount=round(abs(float(first.amount)), 2),
            total_spend=round(total, 2),
        ))

    # Sort by most recent first (by first transaction date desc)
    def _first_date(item: NewMerchantItem) -> datetime.date:
        for t in current_txns:
            if t.description == item.description:
                return t.date
        return datetime.date.min

    items.sort(key=_first_date, reverse=True)
    items = items[:20]

    return NewMerchantDetectorVM(
        title="New Merchant Detector",
        items=items,
        period_months=period_months,
        new_count=len(items),
    )


REGISTRY["new_merchant_detector"] = WidgetDef(
    key="new_merchant_detector",
    assembler=build_new_merchant_detector,
    template="intelligence/widgets/new_merchant_detector.html",
)
