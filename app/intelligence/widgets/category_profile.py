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


_TOP_TXNS_PER_CAT = 40


@dataclass(frozen=True)
class CategoryTransactionBar:
    transaction_id: str
    description: str
    amount: float


@dataclass(frozen=True)
class CategoryProfileRow:
    label: str
    category_id: str | None  # None for uncategorized rows
    count: int
    total: float
    mean: float
    std_dev: float
    cv: float            # coefficient of variation: std_dev / mean
    consistency: str     # "Consistent" | "Mixed" | "Irregular" | "—"
    is_uncategorized: bool
    top_transactions: list  # list[CategoryTransactionBar], top _TOP_TXNS_PER_CAT by amount desc


@dataclass(frozen=True)
class CategoryProfileVM:
    title: str
    rows: list[CategoryProfileRow]
    period_months: int
    total_txns: int
    categorized_count: int
    uncategorized_count: int
    pct_categorized: float
    consistent_count: int
    mixed_count: int
    irregular_count: int
    total_spend: float
    categorized_spend: float
    uncategorized_spend: float
    pct_spend_categorized: float


def _consistency(cv: float, count: int) -> str:
    if count < 2:
        return "—"
    if cv < 0.5:
        return "Consistent"
    if cv < 1.0:
        return "Mixed"
    return "Irregular"


def build_category_profile(user_id: str, period_months: int = 12) -> CategoryProfileVM:
    """Return per-category transaction stats across all time.

    All-time scope is intentional: CV measures the structural nature of a
    category (what kind of spending it catches), not a recent trend. More
    transactions produce a more reliable std dev.

    period_months is accepted but unused — kept for interface consistency
    with other widget assemblers.

    Only outflow transactions (amount < 0) are included.
    """
    all_txns = []
    offset = 0
    page_size = 200
    while True:
        page = get_transactions(user_id, TransactionFilters(
            limit=page_size,
            offset=offset,
        ))
        all_txns.extend(page.items)
        if len(all_txns) >= page.total_count:
            break
        offset += page_size

    # Health stats from all transactions (inflow + outflow)
    total_txns = len(all_txns)
    uncategorized_count = sum(1 for t in all_txns if not t.category_name)
    categorized_count = max(total_txns - uncategorized_count, 0)
    pct_categorized = round(categorized_count / total_txns * 100, 1) if total_txns > 0 else 0.0

    # Spend coverage — outflow only
    categorized_spend = sum(abs(float(t.amount)) for t in all_txns if float(t.amount) < 0 and t.category_name)
    uncategorized_spend = sum(abs(float(t.amount)) for t in all_txns if float(t.amount) < 0 and not t.category_name)
    total_spend = categorized_spend + uncategorized_spend
    pct_spend_categorized = round(categorized_spend / total_spend * 100, 1) if total_spend > 0 else 0.0

    # Group outflow transactions by category
    category_txns: dict[str, list] = {}
    category_ids: dict[str, str | None] = {}
    for txn in all_txns:
        if float(txn.amount) >= 0:
            continue
        label = txn.category_name or "Uncategorized"
        category_txns.setdefault(label, []).append(txn)
        if label not in category_ids:
            category_ids[label] = str(txn.category_id) if txn.category_id else None

    rows: list[CategoryProfileRow] = []
    for label, txns in category_txns.items():
        amounts = [abs(float(t.amount)) for t in txns]
        count = len(amounts)
        total = sum(amounts)
        mean = total / count
        if count >= 2:
            std_dev = math.sqrt(sum((a - mean) ** 2 for a in amounts) / (count - 1))
        else:
            std_dev = 0.0
        cv = std_dev / mean if mean > 0 else 0.0

        top_txns = sorted(txns, key=lambda t: abs(float(t.amount)), reverse=True)[:_TOP_TXNS_PER_CAT]
        top_bars = [
            CategoryTransactionBar(
                transaction_id=str(t.id),
                description=t.description,
                amount=round(abs(float(t.amount)), 2),
            )
            for t in top_txns
        ]

        rows.append(CategoryProfileRow(
            label=label,
            category_id=category_ids.get(label),
            count=count,
            total=round(total, 2),
            mean=round(mean, 2),
            std_dev=round(std_dev, 2),
            cv=round(cv, 2),
            consistency=_consistency(cv, count),
            is_uncategorized=(label == "Uncategorized"),
            top_transactions=top_bars,
        ))

    categorized = sorted(
        [r for r in rows if not r.is_uncategorized],
        key=lambda r: r.total,
        reverse=True,
    )
    uncategorized = [r for r in rows if r.is_uncategorized]

    all_rows = categorized + uncategorized
    return CategoryProfileVM(
        title="Category Profile",
        rows=all_rows,
        period_months=period_months,
        total_txns=total_txns,
        categorized_count=categorized_count,
        uncategorized_count=uncategorized_count,
        pct_categorized=pct_categorized,
        consistent_count=sum(1 for r in all_rows if r.consistency == "Consistent"),
        mixed_count=sum(1 for r in all_rows if r.consistency == "Mixed"),
        irregular_count=sum(1 for r in all_rows if r.consistency == "Irregular"),
        total_spend=round(total_spend, 2),
        categorized_spend=round(categorized_spend, 2),
        uncategorized_spend=round(uncategorized_spend, 2),
        pct_spend_categorized=pct_spend_categorized,
    )


REGISTRY["category_profile"] = WidgetDef(
    key="category_profile",
    assembler=build_category_profile,
    template="intelligence/widgets/category_profile.html",
)
