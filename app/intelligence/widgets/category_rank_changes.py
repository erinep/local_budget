"""Category rank changes widget.

Answers: "Which categories moved up or down in my spending rankings?"

Public API:
    build_category_rank_changes(user_id, period_months) -> CategoryRankChangesVM
"""

import datetime
from dataclasses import dataclass
from typing import Optional

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class RankChangeItem:
    category_name: str
    current_rank: int
    prior_rank: Optional[int]  # None if new this period
    rank_change: int           # prior - current; positive = moved up (worse)
    current_spend: float
    prior_spend: float


@dataclass(frozen=True)
class CategoryRankChangesVM:
    title: str
    items: list[RankChangeItem]  # sorted by current_rank
    current_label: str           # "last 3 months"
    prior_label: str             # "prior 3 months"


def build_category_rank_changes(user_id: str, period_months: int = 6) -> CategoryRankChangesVM:
    """Return category rank movements between recent 3 and prior 3 months."""
    now = datetime.datetime.now(datetime.timezone.utc)
    year, month = now.year, now.month

    months: list[tuple[int, int]] = []
    for _ in range(6):
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

    # Rank current categories by spend
    current_ranked = sorted(recent_spend, key=lambda c: recent_spend[c], reverse=True)
    prior_ranked = sorted(prior_spend, key=lambda c: prior_spend[c], reverse=True)

    current_rank_map = {cat: i + 1 for i, cat in enumerate(current_ranked)}
    prior_rank_map = {cat: i + 1 for i, cat in enumerate(prior_ranked)}

    items: list[RankChangeItem] = []
    for cat in current_ranked[:10]:
        cur_rank = current_rank_map[cat]
        pri_rank = prior_rank_map.get(cat)
        rank_change = (pri_rank - cur_rank) if pri_rank is not None else 0
        items.append(RankChangeItem(
            category_name=cat,
            current_rank=cur_rank,
            prior_rank=pri_rank,
            rank_change=rank_change,
            current_spend=round(recent_spend[cat], 2),
            prior_spend=round(prior_spend.get(cat, 0.0), 2),
        ))

    return CategoryRankChangesVM(
        title="Category Rank Changes",
        items=items,
        current_label="last 3 months",
        prior_label="prior 3 months",
    )


REGISTRY["category_rank_changes"] = WidgetDef(
    key="category_rank_changes",
    assembler=build_category_rank_changes,
    template="intelligence/widgets/category_rank_changes.html",
)
