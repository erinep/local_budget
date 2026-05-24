"""Outlier transactions widget.

Answers: "Which transactions were unusually large relative to their category?"

Outliers are defined as transactions whose amount exceeds the category mean
by at least `threshold_sigma` standard deviations (sample std dev, n-1).
Categories with fewer than 2 transactions are excluded (std dev undefined).

Public API:
    build_outlier_transactions(user_id, period_months, threshold_sigma) -> OutlierTransactionsVM
"""

import datetime
import math
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class OutlierTransactionItem:
    description: str
    category_name: str | None
    amount: float
    date: datetime.date
    category_mean: float
    z_score: float


@dataclass(frozen=True)
class OutlierTransactionsVM:
    title: str
    items: list[OutlierTransactionItem]
    period_months: int
    threshold_sigma: float


def build_outlier_transactions(
    user_id: str,
    period_months: int = 12,
    threshold_sigma: float = 2.0,
) -> OutlierTransactionsVM:
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

    # Group outflow amounts by category key
    by_category: dict[str, list[tuple]] = {}
    for t in all_txns:
        if float(t.amount) >= 0:
            continue
        key = t.category_name or "Uncategorized"
        by_category.setdefault(key, []).append(t)

    # Compute per-category mean and sample std dev
    stats: dict[str, tuple[float, float]] = {}  # key -> (mean, std_dev)
    for key, txns in by_category.items():
        if len(txns) < 2:
            continue
        amounts = [abs(float(t.amount)) for t in txns]
        mean = sum(amounts) / len(amounts)
        variance = sum((a - mean) ** 2 for a in amounts) / (len(amounts) - 1)
        std_dev = math.sqrt(variance)
        if std_dev > 0:
            stats[key] = (mean, std_dev)

    outliers: list[OutlierTransactionItem] = []
    for t in all_txns:
        if float(t.amount) >= 0:
            continue
        key = t.category_name or "Uncategorized"
        if key not in stats:
            continue
        mean, std_dev = stats[key]
        amount = abs(float(t.amount))
        z_score = (amount - mean) / std_dev
        if z_score >= threshold_sigma:
            outliers.append(OutlierTransactionItem(
                description=t.description,
                category_name=t.category_name,
                amount=round(amount, 2),
                date=t.date,
                category_mean=round(mean, 2),
                z_score=round(z_score, 1),
            ))

    outliers.sort(key=lambda x: x.z_score, reverse=True)

    return OutlierTransactionsVM(
        title="Unusual Transactions",
        items=outliers,
        period_months=period_months,
        threshold_sigma=threshold_sigma,
    )


REGISTRY["outlier_transactions"] = WidgetDef(
    key="outlier_transactions",
    assembler=build_outlier_transactions,
    template="intelligence/widgets/outlier_transactions.html",
)
