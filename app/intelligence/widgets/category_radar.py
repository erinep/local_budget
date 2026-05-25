"""Category radar widget — spider chart of this month vs. historical avg.

Public API:
    build_category_radar(user_id, period_months) -> CategoryRadarVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions

_TOP_N = 7


@dataclass(frozen=True)
class CategoryRadarVM:
    title: str
    labels: list            # category names (top N by historical spend)
    current_month: list     # spend this month per category
    historical_avg: list    # average monthly spend per category (last period_months)
    current_month_label: str  # e.g. "May 2026"
    period_months: int


def build_category_radar(user_id: str, period_months: int = 12) -> CategoryRadarVM:
    """Return radar chart data comparing current month to historical average."""
    today = datetime.date.today()
    current_month_label = today.strftime("%b %Y")

    # Date range for historical period (complete past months)
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
    hist_date_from = datetime.date(oldest_y, oldest_m, 1)
    if latest_m == 12:
        hist_date_to = datetime.date(latest_y + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        hist_date_to = datetime.date(latest_y, latest_m + 1, 1) - datetime.timedelta(days=1)

    # Fetch historical transactions
    hist_txns = []
    offset = 0
    page_size = 200
    while True:
        page = get_transactions(user_id, TransactionFilters(
            limit=page_size,
            offset=offset,
            date_from=hist_date_from,
            date_to=hist_date_to,
        ))
        hist_txns.extend(page.items)
        if len(hist_txns) >= page.total_count:
            break
        offset += page_size

    # Current month transactions (date_from = first of this month, date_to = today)
    curr_date_from = datetime.date(today.year, today.month, 1)
    curr_date_to = today
    curr_txns = []
    offset = 0
    while True:
        page = get_transactions(user_id, TransactionFilters(
            limit=page_size,
            offset=offset,
            date_from=curr_date_from,
            date_to=curr_date_to,
        ))
        curr_txns.extend(page.items)
        if len(curr_txns) >= page.total_count:
            break
        offset += page_size

    # Group historical outflows by (category, month) then average per category
    # key: (year, month, category_label) -> amount
    hist_monthly: dict[tuple, dict[str, float]] = {}
    for txn in hist_txns:
        if float(txn.amount) >= 0:
            continue
        label = txn.category_name or "Uncategorized"
        key = (txn.date.year, txn.date.month)
        hist_monthly.setdefault(key, {})
        hist_monthly[key][label] = hist_monthly[key].get(label, 0.0) + abs(float(txn.amount))

    # Compute per-category totals and averages across all historical months
    cat_month_totals: dict[str, list[float]] = {}
    for monthly_dict in hist_monthly.values():
        for cat, amt in monthly_dict.items():
            cat_month_totals.setdefault(cat, []).append(amt)

    # Avg per category (pad missing months with 0)
    cat_avg: dict[str, float] = {
        cat: sum(amts) / period_months
        for cat, amts in cat_month_totals.items()
    }

    # Top N categories by historical average
    top_cats = sorted(cat_avg.keys(), key=lambda c: cat_avg[c], reverse=True)[:_TOP_N]

    # Current month spend per top category
    curr_by_cat: dict[str, float] = {}
    for txn in curr_txns:
        if float(txn.amount) >= 0:
            continue
        label = txn.category_name or "Uncategorized"
        curr_by_cat[label] = curr_by_cat.get(label, 0.0) + abs(float(txn.amount))

    labels = list(top_cats)
    current_month = [round(curr_by_cat.get(c, 0.0), 2) for c in labels]
    historical_avg = [round(cat_avg.get(c, 0.0), 2) for c in labels]

    return CategoryRadarVM(
        title="Category Radar",
        labels=labels,
        current_month=current_month,
        historical_avg=historical_avg,
        current_month_label=current_month_label,
        period_months=period_months,
    )


REGISTRY["category_radar"] = WidgetDef(
    key="category_radar",
    assembler=build_category_radar,
    template="intelligence/widgets/category_radar.html",
)
