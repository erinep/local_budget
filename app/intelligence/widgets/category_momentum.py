"""Category momentum widget.

Answers: "Which categories are accelerating or decelerating vs the prior period?"

Public API:
    build_category_momentum(user_id, period_months) -> CategoryMomentumVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class CategoryMomentumItem:
    category_name: str
    recent_avg: float    # avg monthly spend, last 3 months
    prior_avg: float     # avg monthly spend, 3 months before that
    change_pct: float    # (recent - prior) / prior * 100; 0 if prior == 0
    direction: str       # 'up', 'down', 'flat' (flat = abs(change_pct) < 5)


@dataclass(frozen=True)
class CategoryMomentumVM:
    title: str
    items: list[CategoryMomentumItem]  # sorted by abs(change_pct) desc
    period_label: str  # "last 3 vs prior 3 months"


def build_category_momentum(user_id: str, period_months: int = 6) -> CategoryMomentumVM:
    """Return momentum comparison for each category (recent 3 vs prior 3 months)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    year, month = now.year, now.month

    months: list[tuple[int, int]] = []
    for _ in range(6):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        months.append((year, month))

    # months[0] = most recent complete month, months[5] = oldest
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

    # months[0..2] = recent (most recent first), months[3..5] = prior
    recent_set = set(months[:3])
    prior_set = set(months[3:])

    recent_spend: dict[str, float] = {}
    prior_spend: dict[str, float] = {}

    for txn in all_txns:
        if float(txn.amount) >= 0:
            continue
        cat = txn.category_name
        if not cat or cat == "Uncategorized":
            continue
        key = (txn.date.year, txn.date.month)
        amt = abs(float(txn.amount))
        if key in recent_set:
            recent_spend[cat] = recent_spend.get(cat, 0.0) + amt
        elif key in prior_set:
            prior_spend[cat] = prior_spend.get(cat, 0.0) + amt

    all_cats = set(recent_spend) | set(prior_spend)
    items: list[CategoryMomentumItem] = []
    for cat in all_cats:
        r_avg = recent_spend.get(cat, 0.0) / 3.0
        p_avg = prior_spend.get(cat, 0.0) / 3.0
        if p_avg == 0:
            change_pct = 0.0
        else:
            change_pct = (r_avg - p_avg) / p_avg * 100.0
        if abs(change_pct) < 5:
            direction = "flat"
        elif change_pct > 0:
            direction = "up"
        else:
            direction = "down"
        items.append(CategoryMomentumItem(
            category_name=cat,
            recent_avg=round(r_avg, 2),
            prior_avg=round(p_avg, 2),
            change_pct=round(change_pct, 1),
            direction=direction,
        ))

    items.sort(key=lambda x: abs(x.change_pct), reverse=True)

    return CategoryMomentumVM(
        title="Category Momentum",
        items=items,
        period_label="last 3 vs prior 3 months",
    )


REGISTRY["category_momentum"] = WidgetDef(
    key="category_momentum",
    assembler=build_category_momentum,
    template="intelligence/widgets/category_momentum.html",
)
