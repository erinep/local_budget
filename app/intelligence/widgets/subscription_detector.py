"""Subscription detector widget — auto-detects recurring charges.

Groups transactions by normalized description, flags groups appearing in 3+
distinct months with consistent amounts (max variance < 20% of median).

Public API:
    build_subscription_detector(user_id, period_months) -> SubscriptionDetectorVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions

_MIN_MONTHS = 3
_MAX_VARIANCE_RATIO = 0.20


@dataclass(frozen=True)
class SubscriptionItem:
    description: str
    category_name: str | None
    typical_amount: float   # median of observed amounts
    months_seen: int        # how many distinct months it appeared
    total_paid: float       # sum of all matched transactions


@dataclass(frozen=True)
class SubscriptionDetectorVM:
    title: str
    items: list             # list[SubscriptionItem] sorted by typical_amount desc
    period_months: int
    monthly_total: float    # sum of typical_amounts (estimated monthly recurring cost)


def build_subscription_detector(user_id: str, period_months: int = 12) -> SubscriptionDetectorVM:
    """Detect recurring charges by normalized description and amount consistency."""
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

    # Group outflow transactions by normalized description
    # key: normalized_description -> list of (amount, month_key, category_name)
    groups: dict[str, list] = {}
    for txn in all_txns:
        if float(txn.amount) >= 0:
            continue
        normalized = txn.description.lower().strip()
        amount = abs(float(txn.amount))
        month_key = (txn.date.year, txn.date.month)
        groups.setdefault(normalized, []).append((amount, month_key, txn.category_name))

    items: list[SubscriptionItem] = []
    for norm_desc, entries in groups.items():
        distinct_months = {e[1] for e in entries}
        if len(distinct_months) < _MIN_MONTHS:
            continue

        amounts = [e[0] for e in entries]
        sorted_amounts = sorted(amounts)
        median_amount = sorted_amounts[len(sorted_amounts) // 2]

        if median_amount <= 0:
            continue

        min_amount = sorted_amounts[0]
        max_amount = sorted_amounts[-1]
        variance_ratio = (max_amount - min_amount) / median_amount
        if variance_ratio >= _MAX_VARIANCE_RATIO:
            continue

        # Use original-case description from first entry seen for display
        # We need to retrieve the original description — find it from transactions
        original_desc = ""
        for txn in all_txns:
            if txn.description.lower().strip() == norm_desc and float(txn.amount) < 0:
                original_desc = txn.description
                break

        category_name = entries[0][2]  # category from first entry
        total_paid = round(sum(amounts), 2)

        items.append(SubscriptionItem(
            description=original_desc or norm_desc,
            category_name=category_name,
            typical_amount=round(median_amount, 2),
            months_seen=len(distinct_months),
            total_paid=total_paid,
        ))

    # Sort by typical_amount descending
    items.sort(key=lambda x: x.typical_amount, reverse=True)
    monthly_total = round(sum(item.typical_amount for item in items), 2)

    return SubscriptionDetectorVM(
        title="Subscription Detector",
        items=items,
        period_months=period_months,
        monthly_total=monthly_total,
    )


REGISTRY["subscription_detector"] = WidgetDef(
    key="subscription_detector",
    assembler=build_subscription_detector,
    template="intelligence/widgets/subscription_detector.html",
)
