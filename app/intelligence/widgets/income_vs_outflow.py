"""Income vs outflow widget.

Answers: "Am I spending more than I earn each month?"

Public API:
    build_income_vs_outflow(user_id, period_months) -> IncomeVsOutflowVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class IncomeVsOutflowVM:
    title: str
    labels: list[str]          # month labels
    income: list[float]        # sum of positive transactions per month
    outflow: list[float]       # sum of abs(negative transactions) per month
    net: list[float]           # income - outflow per month (can be negative)
    period_months: int
    has_income: bool           # True if any positive transactions found


def build_income_vs_outflow(user_id: str, period_months: int = 6) -> IncomeVsOutflowVM:
    """Return income, outflow, and net per month."""
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

    # Oldest first for display
    ordered = list(reversed(months))
    income_map: dict[tuple[int, int], float] = {k: 0.0 for k in ordered}
    outflow_map: dict[tuple[int, int], float] = {k: 0.0 for k in ordered}

    for txn in all_txns:
        amt = float(txn.amount)
        key = (txn.date.year, txn.date.month)
        if key not in income_map:
            continue
        if amt > 0:
            income_map[key] += amt
        else:
            outflow_map[key] += abs(amt)

    labels = [datetime.date(y, m, 1).strftime("%b %Y") for y, m in ordered]
    income_list = [round(income_map[k], 2) for k in ordered]
    outflow_list = [round(outflow_map[k], 2) for k in ordered]
    net_list = [round(income_map[k] - outflow_map[k], 2) for k in ordered]
    has_income = any(v > 0 for v in income_list)

    return IncomeVsOutflowVM(
        title="Income vs Outflow",
        labels=labels,
        income=income_list,
        outflow=outflow_list,
        net=net_list,
        period_months=period_months,
        has_income=has_income,
    )


REGISTRY["income_vs_outflow"] = WidgetDef(
    key="income_vs_outflow",
    assembler=build_income_vs_outflow,
    template="intelligence/widgets/income_vs_outflow.html",
)
