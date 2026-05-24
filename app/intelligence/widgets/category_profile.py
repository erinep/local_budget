"""Category profile widget — per-category transaction stats table.

Answers: "Are my categories well-defined?" by surfacing volume, average
transaction value, and standard deviation per category. A high coefficient
of variation (std_dev / mean) signals a category that is catching multiple
distinct spending behaviours and may benefit from being split.

Public API:
    build_category_profile(user_id, period_months) -> CategoryProfileVM
"""

import datetime
import math
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class CategoryProfileRow:
    label: str
    count: int
    total: float
    mean: float
    std_dev: float
    cv: float            # coefficient of variation: std_dev / mean
    consistency: str     # "Consistent" | "Mixed" | "Irregular" | "—"
    is_uncategorized: bool


@dataclass(frozen=True)
class CategoryProfileVM:
    title: str
    rows: list[CategoryProfileRow]
    period_months: int


def _consistency(cv: float, count: int) -> str:
    if count < 2:
        return "—"
    if cv < 0.5:
        return "Consistent"
    if cv < 1.0:
        return "Mixed"
    return "Irregular"


def build_category_profile(user_id: str, period_months: int = 12) -> CategoryProfileVM:
    """Return per-category transaction stats for the last period_months complete months.

    Only outflow transactions (amount < 0) are included, matching the sign
    convention used across all other intelligence widgets.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    first_of_current = datetime.date(now.year, now.month, 1)
    date_to = first_of_current - datetime.timedelta(days=1)

    year, month = now.year, now.month
    for _ in range(period_months):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    date_from = datetime.date(year, month, 1)

    # Page through all transactions in the period
    all_txns = []
    offset = 0
    page_size = 200
    while True:
        page = get_transactions(user_id, TransactionFilters(
            date_from=date_from,
            date_to=date_to,
            limit=page_size,
            offset=offset,
        ))
        all_txns.extend(page.items)
        if len(all_txns) >= page.total_count:
            break
        offset += page_size

    # Group outflow amounts by category
    category_amounts: dict[str, list[float]] = {}
    for txn in all_txns:
        if float(txn.amount) >= 0:
            continue
        label = txn.category_name or "Uncategorized"
        category_amounts.setdefault(label, []).append(abs(float(txn.amount)))

    rows: list[CategoryProfileRow] = []
    for label, amounts in category_amounts.items():
        count = len(amounts)
        total = sum(amounts)
        mean = total / count
        if count >= 2:
            std_dev = math.sqrt(sum((a - mean) ** 2 for a in amounts) / (count - 1))
        else:
            std_dev = 0.0
        cv = std_dev / mean if mean > 0 else 0.0
        rows.append(CategoryProfileRow(
            label=label,
            count=count,
            total=round(total, 2),
            mean=round(mean, 2),
            std_dev=round(std_dev, 2),
            cv=round(cv, 2),
            consistency=_consistency(cv, count),
            is_uncategorized=(label == "Uncategorized"),
        ))

    categorized = sorted(
        [r for r in rows if not r.is_uncategorized],
        key=lambda r: r.total,
        reverse=True,
    )
    uncategorized = [r for r in rows if r.is_uncategorized]

    return CategoryProfileVM(
        title="Category Profile",
        rows=categorized + uncategorized,
        period_months=period_months,
    )


REGISTRY["category_profile"] = WidgetDef(
    key="category_profile",
    assembler=build_category_profile,
    template="intelligence/widgets/category_profile.html",
)
