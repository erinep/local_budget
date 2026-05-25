"""Category seasonality heatmap widget.

Answers: "Which months are unusually high or low for each category?"

Public API:
    build_category_seasonality(user_id, period_months) -> CategorySeasonalityVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class SeasonalityCell:
    raw: float       # actual spend that month
    delta_pct: float # (raw - category_avg) / category_avg * 100; 0 if avg==0
    level: int       # -2=much below, -1=below, 0=avg, 1=above, 2=much above


@dataclass(frozen=True)
class SeasonalityRow:
    category_name: str
    cells: list[SeasonalityCell]  # one per month, oldest first


@dataclass(frozen=True)
class CategorySeasonalityVM:
    title: str
    month_labels: list[str]
    rows: list[SeasonalityRow]   # top 7 categories by total spend
    period_months: int


def _level(delta_pct: float) -> int:
    if delta_pct < -30:
        return -2
    if delta_pct < -10:
        return -1
    if delta_pct <= 10:
        return 0
    if delta_pct <= 30:
        return 1
    return 2


def build_category_seasonality(user_id: str, period_months: int = 6) -> CategorySeasonalityVM:
    """Return a category x month heatmap showing relative spend vs category average."""
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
            limit=page_size, offset=offset, date_from=date_from, date_to=date_to,
        ))
        all_txns.extend(page.items)
        if len(all_txns) >= page.total_count:
            break
        offset += page_size

    # cat -> (year, month) -> spend
    cat_month_spend: dict[str, dict[tuple[int, int], float]] = {}
    cat_total: dict[str, float] = {}

    for txn in all_txns:
        if float(txn.amount) >= 0:
            continue
        cat = txn.category_name
        if not cat or cat == "Uncategorized":
            continue
        amt = abs(float(txn.amount))
        key = (txn.date.year, txn.date.month)
        if cat not in cat_month_spend:
            cat_month_spend[cat] = {}
        cat_month_spend[cat][key] = cat_month_spend[cat].get(key, 0.0) + amt
        cat_total[cat] = cat_total.get(cat, 0.0) + amt

    top_cats = sorted(cat_total, key=lambda c: cat_total[c], reverse=True)[:7]

    # Oldest month first for display
    ordered_months = list(reversed(months))
    month_labels = [
        datetime.date(y, m, 1).strftime("%b %Y") for y, m in ordered_months
    ]

    rows: list[SeasonalityRow] = []
    for cat in top_cats:
        monthly = cat_month_spend.get(cat, {})
        values = [monthly.get(key, 0.0) for key in ordered_months]
        avg = sum(values) / len(values) if values else 0.0
        cells = []
        for v in values:
            if avg == 0:
                delta_pct = 0.0
            else:
                delta_pct = (v - avg) / avg * 100.0
            cells.append(SeasonalityCell(
                raw=round(v, 2),
                delta_pct=round(delta_pct, 1),
                level=_level(delta_pct),
            ))
        rows.append(SeasonalityRow(category_name=cat, cells=cells))

    return CategorySeasonalityVM(
        title="Category Seasonality",
        month_labels=month_labels,
        rows=rows,
        period_months=period_months,
    )


REGISTRY["category_seasonality"] = WidgetDef(
    key="category_seasonality",
    assembler=build_category_seasonality,
    template="intelligence/widgets/category_seasonality.html",
)
