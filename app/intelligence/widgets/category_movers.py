"""Category movers widget — month-over-month spend delta per category.

Answers "Which categories are trending up?" by comparing the last two
complete calendar months and ranking categories by absolute change.

Compares full months only (no MTD distortion). Categories that appear in
only one of the two months are included with a zero baseline.

Public API:
    build_category_movers(user_id, period_months) -> CategoryMoversVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions

_TOP_N = 10


@dataclass(frozen=True)
class MoverItem:
    category_name: str
    current: float      # spend in the more recent complete month
    prior: float        # spend in the month before that
    delta: float        # current - prior (positive = spending more)
    pct_change: float   # delta / prior * 100, or None if prior is zero


@dataclass(frozen=True)
class CategoryMoversVM:
    title: str
    items: list          # list[MoverItem], sorted by abs(delta) desc
    current_label: str   # e.g. "April 2026"
    prior_label: str     # e.g. "March 2026"


def _fetch_month(user_id: str, date_from: datetime.date, date_to: datetime.date) -> list:
    txns = []
    offset = 0
    page_size = 200
    while True:
        page = get_transactions(user_id, TransactionFilters(
            limit=page_size, offset=offset,
            date_from=date_from, date_to=date_to,
        ))
        txns.extend(page.items)
        if len(txns) >= page.total_count:
            break
        offset += page_size
    return txns


def _spend_by_cat(txns: list) -> dict[str, float]:
    result: dict[str, float] = {}
    for t in txns:
        if float(t.amount) >= 0:
            continue
        label = t.category_name or "Uncategorized"
        result[label] = result.get(label, 0.0) + abs(float(t.amount))
    return result


def build_category_movers(user_id: str, period_months: int = 12) -> CategoryMoversVM:
    today = datetime.date.today()

    # Last two complete calendar months
    # "current" = most recent complete month; "prior" = the one before it
    y, m = today.year, today.month
    m -= 1
    if m == 0:
        m, y = 12, y - 1
    current_year, current_month = y, m

    m -= 1
    if m == 0:
        m, y = 12, y - 1
    prior_year, prior_month = y, m

    def month_range(yr, mo):
        date_from = datetime.date(yr, mo, 1)
        if mo == 12:
            date_to = datetime.date(yr + 1, 1, 1) - datetime.timedelta(days=1)
        else:
            date_to = datetime.date(yr, mo + 1, 1) - datetime.timedelta(days=1)
        return date_from, date_to

    current_txns = _fetch_month(user_id, *month_range(current_year, current_month))
    prior_txns   = _fetch_month(user_id, *month_range(prior_year,   prior_month))

    current_by_cat = _spend_by_cat(current_txns)
    prior_by_cat   = _spend_by_cat(prior_txns)

    all_cats = set(current_by_cat) | set(prior_by_cat)
    items = []
    for cat in all_cats:
        current = round(current_by_cat.get(cat, 0.0), 2)
        prior   = round(prior_by_cat.get(cat, 0.0), 2)
        delta   = round(current - prior, 2)
        pct     = round((delta / prior * 100), 1) if prior > 0 else None
        items.append(MoverItem(
            category_name=cat,
            current=current,
            prior=prior,
            delta=delta,
            pct_change=pct,
        ))

    items.sort(key=lambda x: abs(x.delta), reverse=True)
    items = items[:_TOP_N]

    month_names = ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]

    return CategoryMoversVM(
        title="Category Movers",
        items=items,
        current_label=f"{month_names[current_month - 1]} {current_year}",
        prior_label=f"{month_names[prior_month - 1]} {prior_year}",
    )


REGISTRY["category_movers"] = WidgetDef(
    key="category_movers",
    assembler=build_category_movers,
    template="intelligence/widgets/category_movers.html",
)
