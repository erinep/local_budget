"""Spending concentration widget.

Answers: "How concentrated is my spending in my top categories?"

Public API:
    build_spending_concentration(user_id, period_months) -> SpendingConcentrationVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class SpendingConcentrationVM:
    title: str
    labels: list[str]        # month labels
    top1_pct: list[float]    # % of monthly spend in #1 category
    top3_pct: list[float]    # % of monthly spend in top 3 categories
    top5_pct: list[float]    # % of monthly spend in top 5 categories
    period_months: int


def build_spending_concentration(user_id: str, period_months: int = 6) -> SpendingConcentrationVM:
    """Return concentration percentages for top 1/3/5 categories per month."""
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

    # Oldest first
    ordered = list(reversed(months))
    labels = [datetime.date(y, m, 1).strftime("%b %Y") for y, m in ordered]

    top1_pct: list[float] = []
    top3_pct: list[float] = []
    top5_pct: list[float] = []

    for y, m in ordered:
        cat_spend: dict[str, float] = {}
        total = 0.0
        for t in all_txns:
            if float(t.amount) >= 0:
                continue
            if t.date.year != y or t.date.month != m:
                continue
            cat = t.category_name or "Uncategorized"
            amt = abs(float(t.amount))
            cat_spend[cat] = cat_spend.get(cat, 0.0) + amt
            total += amt

        if total == 0:
            top1_pct.append(0.0)
            top3_pct.append(0.0)
            top5_pct.append(0.0)
            continue

        sorted_vals = sorted(cat_spend.values(), reverse=True)
        top1 = sum(sorted_vals[:1]) / total * 100.0
        top3 = sum(sorted_vals[:3]) / total * 100.0
        top5 = sum(sorted_vals[:5]) / total * 100.0
        top1_pct.append(round(top1, 1))
        top3_pct.append(round(top3, 1))
        top5_pct.append(round(top5, 1))

    return SpendingConcentrationVM(
        title="Spending Concentration",
        labels=labels,
        top1_pct=top1_pct,
        top3_pct=top3_pct,
        top5_pct=top5_pct,
        period_months=period_months,
    )


REGISTRY["spending_concentration"] = WidgetDef(
    key="spending_concentration",
    assembler=build_spending_concentration,
    template="intelligence/widgets/spending_concentration.html",
)
