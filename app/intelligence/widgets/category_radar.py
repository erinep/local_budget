"""Category radar widget — spider chart toggling between recent months.

Shows top spending categories as radar axes. Pill buttons let you switch
between this month (MTD) and the previous 11 complete months. Each month
also shows total spend and top individual transactions inline, with unusual
transactions flagged (z-score >= 2.0 relative to that category's 12-month
per-transaction distribution).

Public API:
    build_category_radar(user_id, period_months) -> CategoryRadarVM
"""

import datetime
import math
from dataclasses import dataclass

from app.budgets.services import get_budgets
from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions

_TOP_N = 7
_TOP_TXN = 10
_PRIOR_MONTHS = 11  # complete months shown before current MTD (-1 through -11)
_OUTLIER_Z = 2.0


@dataclass(frozen=True)
class RadarTransaction:
    description: str
    category_name: str | None
    amount: float
    is_outlier: bool
    transaction_id: str | None = None


@dataclass(frozen=True)
class RadarMonthData:
    label: str
    data: list              # spend per category, aligned to CategoryRadarVM.labels
    is_current: bool
    total: float            # total outflow for this month
    top_transactions: list  # list[RadarTransaction], top _TOP_TXN by amount


@dataclass(frozen=True)
class CategoryRadarVM:
    title: str
    labels: list            # budgeted category names only (consistent across all months)
    months: list            # list[RadarMonthData]; .data values are % of budget (0–N)
    budget_data: list       # always [100.0, ...] — the normalised target polygon
    has_budgets: bool       # True when at least one budgeted category exists
    unbudgeted_cats: list   # top-spending categories excluded because they have no budget


def _fetch_range(user_id: str, date_from: datetime.date, date_to: datetime.date) -> list:
    """Fetch all transactions in [date_from, date_to] with a single paginated loop."""
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


def _cat_stats(all_txns: list) -> dict[str, tuple[float, float]]:
    """Return {category: (mean, std_dev)} for all outflow transactions."""
    amounts: dict[str, list[float]] = {}
    for t in all_txns:
        amt = float(t.amount)
        if amt >= 0:
            continue
        label = t.category_name or "Uncategorized"
        amounts.setdefault(label, []).append(abs(amt))

    stats: dict[str, tuple[float, float]] = {}
    for cat, vals in amounts.items():
        n = len(vals)
        mean = sum(vals) / n
        if n < 2:
            std_dev = 0.0
        else:
            variance = sum((v - mean) ** 2 for v in vals) / (n - 1)
            std_dev = math.sqrt(variance)
        stats[cat] = (mean, std_dev)
    return stats


def build_category_radar(user_id: str, period_months: int = 12) -> CategoryRadarVM:
    today = datetime.date.today()
    now = datetime.datetime.now(datetime.timezone.utc)

    # Build the list of month slots: current MTD + 11 prior complete months.
    # Using range(_PRIOR_MONTHS) explicitly so months -1 through -11 never
    # wrap around to duplicate the current month's name.
    slots: list[tuple[int, int, bool]] = [(today.year, today.month, True)]
    y, m = today.year, today.month
    for _ in range(_PRIOR_MONTHS):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        slots.append((y, m, False))

    # Fetch all transactions across the full range in one call, then group by month
    oldest_y, oldest_m, _ = slots[-1]
    range_date_from = datetime.date(oldest_y, oldest_m, 1)
    range_date_to = today
    all_txns = _fetch_range(user_id, range_date_from, range_date_to)

    # Group transactions by (year, month)
    txns_by_month: dict[tuple[int, int], list] = {}
    for t in all_txns:
        key = (t.date.year, t.date.month)
        txns_by_month.setdefault(key, []).append(t)

    slot_txns: list[list] = [
        txns_by_month.get((sy, sm), [])
        for sy, sm, _ in slots
    ]

    # Determine top categories by combined spend across all slots
    combined: dict[str, float] = {}
    for txns in slot_txns:
        for cat, amt in _spend_by_cat(txns).items():
            combined[cat] = combined.get(cat, 0.0) + amt

    top_cats = sorted(combined.keys(), key=lambda c: combined[c], reverse=True)[:_TOP_N]

    # Compute per-category stats across all transactions for outlier detection
    all_txns = [t for txns in slot_txns for t in txns]
    cat_stats = _cat_stats(all_txns)

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    months: list[RadarMonthData] = []
    for (sy, sm, is_current), txns in zip(slots, slot_txns):
        by_cat = _spend_by_cat(txns)

        outflows = [t for t in txns if float(t.amount) < 0]
        outflows.sort(key=lambda t: t.amount)  # most negative first

        top_txns = []
        for t in outflows[:_TOP_TXN]:
            amt = abs(float(t.amount))
            label = t.category_name or "Uncategorized"
            mean, std_dev = cat_stats.get(label, (0.0, 0.0))
            is_outlier = std_dev > 0 and ((amt - mean) / std_dev) >= _OUTLIER_Z
            top_txns.append(RadarTransaction(
                description=t.description,
                category_name=t.category_name,
                amount=round(amt, 2),
                is_outlier=is_outlier,
                transaction_id=str(t.id) if getattr(t, "id", None) else None,
            ))

        total = round(sum(abs(float(t.amount)) for t in outflows), 2)
        name = month_names[sm - 1]
        label = name

        months.append(RadarMonthData(
            label=label,
            data=[round(by_cat.get(c, 0.0), 2) for c in top_cats],
            is_current=is_current,
            total=total,
            top_transactions=top_txns,
        ))

    # Fetch standing budget targets; split top categories into budgeted / unbudgeted
    budgets = get_budgets(user_id)
    budget_by_cat: dict[str, float] = {b.category_name: float(b.amount) for b in budgets}

    budgeted_cats   = [c for c in top_cats if budget_by_cat.get(c, 0.0) > 0.0]
    unbudgeted_cats = [c for c in top_cats if budget_by_cat.get(c, 0.0) == 0.0]

    # Rebuild months with data normalised to % of budget for budgeted axes only
    normalised_months: list[RadarMonthData] = []
    for md in months:
        # md.data is indexed by top_cats; re-index to budgeted_cats
        raw_by_cat = dict(zip(top_cats, md.data))
        pct_data = [
            round(raw_by_cat.get(c, 0.0) / budget_by_cat[c] * 100.0, 1)
            for c in budgeted_cats
        ]
        normalised_months.append(RadarMonthData(
            label=md.label,
            data=pct_data,
            is_current=md.is_current,
            total=md.total,
            top_transactions=md.top_transactions,
        ))

    budget_data = [100.0] * len(budgeted_cats)

    return CategoryRadarVM(
        title="Category Radar",
        labels=budgeted_cats,
        months=normalised_months,
        budget_data=budget_data,
        has_budgets=len(budgeted_cats) > 0,
        unbudgeted_cats=unbudgeted_cats,
    )


REGISTRY["category_radar"] = WidgetDef(
    key="category_radar",
    assembler=build_category_radar,
    template="intelligence/widgets/category_radar.html",
)
