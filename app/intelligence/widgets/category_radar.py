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

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions

_TOP_N = 7
_TOP_TXN = 10
_DISPLAY_MONTHS = 12  # current MTD + 11 prior complete months
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
    labels: list   # category names (consistent across all months)
    months: list   # list[RadarMonthData], current month first


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

    # Build the list of month slots: current MTD + prior complete months
    slots: list[tuple[int, int, bool]] = []
    slots.append((today.year, today.month, True))
    y, m = now.year, now.month
    for _ in range(_DISPLAY_MONTHS - 1):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        slots.append((y, m, False))

    # Fetch transactions for each slot
    slot_txns: list[list] = []
    for sy, sm, is_current in slots:
        date_from = datetime.date(sy, sm, 1)
        if is_current:
            date_to = today
        else:
            if sm == 12:
                date_to = datetime.date(sy + 1, 1, 1) - datetime.timedelta(days=1)
            else:
                date_to = datetime.date(sy, sm + 1, 1) - datetime.timedelta(days=1)
        slot_txns.append(_fetch_month(user_id, date_from, date_to))

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
        label = f"{name} (MTD)" if is_current else name

        months.append(RadarMonthData(
            label=label,
            data=[round(by_cat.get(c, 0.0), 2) for c in top_cats],
            is_current=is_current,
            total=total,
            top_transactions=top_txns,
        ))

    return CategoryRadarVM(
        title="Category Radar",
        labels=list(top_cats),
        months=months,
    )


REGISTRY["category_radar"] = WidgetDef(
    key="category_radar",
    assembler=build_category_radar,
    template="intelligence/widgets/category_radar.html",
)
