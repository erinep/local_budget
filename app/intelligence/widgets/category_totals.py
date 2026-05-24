"""Category totals bar chart widget.

Answers: "Where is my money going this period?"

Public API:
    build_category_totals(user_id, period_months) -> CategoryTotalsVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class CategoryTotalItem:
    label: str
    spend: float
    is_uncategorized: bool


@dataclass(frozen=True)
class CategoryTotalsVM:
    title: str
    items: list[CategoryTotalItem]          # top 7 + Other + Uncategorized, ordered
    period_months: int
    category_amounts: dict[str, list[float]]  # label → individual amounts sorted desc


def build_category_totals(user_id: str, period_months: int = 12) -> CategoryTotalsVM:
    """Return total spend and individual transaction amounts per category.

    Categories are bucketed the same way as category_trends: top 7 by spend,
    remaining categorized spend pooled into "Other", Uncategorized appended last.
    """
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

    # Group outflow (description, amount) pairs by category
    raw: dict[str, list[tuple[str, float]]] = {}
    for txn in all_txns:
        if float(txn.amount) >= 0:
            continue
        label = txn.category_name or "Uncategorized"
        raw.setdefault(label, []).append((txn.description, abs(float(txn.amount))))

    totals = {label: sum(amt for _, amt in pairs) for label, pairs in raw.items()}

    uncategorized_key = "Uncategorized"
    ranked = sorted(
        [k for k in totals if k != uncategorized_key],
        key=lambda c: totals[c],
        reverse=True,
    )
    top_cats = ranked[:7]
    other_cats = ranked[7:]

    items: list[CategoryTotalItem] = [
        CategoryTotalItem(label=cat, spend=round(totals[cat], 2), is_uncategorized=False)
        for cat in top_cats
    ]
    def _build_txn_data(pairs: list[tuple[str, float]]) -> dict:
        sorted_pairs = sorted(pairs, key=lambda x: x[1], reverse=True)
        return {"labels": [p[0] for p in sorted_pairs], "values": [p[1] for p in sorted_pairs]}

    category_amounts: dict[str, dict] = {
        cat: _build_txn_data(raw.get(cat, [])) for cat in top_cats
    }

    if other_cats:
        other_spend = sum(totals[c] for c in other_cats)
        other_pairs = [pair for c in other_cats for pair in raw.get(c, [])]
        items.append(CategoryTotalItem(label="Other", spend=round(other_spend, 2), is_uncategorized=False))
        category_amounts["Other"] = _build_txn_data(other_pairs)

    if uncategorized_key in totals:
        items.append(CategoryTotalItem(
            label=uncategorized_key,
            spend=round(totals[uncategorized_key], 2),
            is_uncategorized=True,
        ))
        category_amounts[uncategorized_key] = _build_txn_data(raw.get(uncategorized_key, []))

    return CategoryTotalsVM(
        title="Category Totals",
        items=items,
        period_months=period_months,
        category_amounts=category_amounts,
    )


REGISTRY["category_totals"] = WidgetDef(
    key="category_totals",
    assembler=build_category_totals,
    template="intelligence/widgets/category_totals.html",
)
