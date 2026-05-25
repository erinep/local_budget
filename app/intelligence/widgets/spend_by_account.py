"""Spend by account widget.

Answers: "Which accounts am I spending from the most?"

Public API:
    build_spend_by_account(user_id, period_months) -> SpendByAccountVM
"""

import datetime
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class AccountSpendItem:
    account_name: str
    total_spend: float
    transaction_count: int
    pct_of_total: float


@dataclass(frozen=True)
class SpendByAccountVM:
    title: str
    items: list[AccountSpendItem]  # sorted by total_spend desc
    total_spend: float
    period_months: int
    has_multiple_accounts: bool


def build_spend_by_account(user_id: str, period_months: int = 6) -> SpendByAccountVM:
    """Return spend breakdown by account."""
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

    acct_spend: dict[str, float] = {}
    acct_count: dict[str, int] = {}

    for txn in all_txns:
        if float(txn.amount) >= 0:
            continue
        name = txn.account_name
        acct_spend[name] = acct_spend.get(name, 0.0) + abs(float(txn.amount))
        acct_count[name] = acct_count.get(name, 0) + 1

    total_spend = sum(acct_spend.values())
    sorted_accounts = sorted(acct_spend, key=lambda a: acct_spend[a], reverse=True)

    items = [
        AccountSpendItem(
            account_name=acct,
            total_spend=round(acct_spend[acct], 2),
            transaction_count=acct_count[acct],
            pct_of_total=round(acct_spend[acct] / total_spend * 100, 1) if total_spend > 0 else 0.0,
        )
        for acct in sorted_accounts
    ]

    return SpendByAccountVM(
        title="Spend by Account",
        items=items,
        total_spend=round(total_spend, 2),
        period_months=period_months,
        has_multiple_accounts=len(items) > 1,
    )


REGISTRY["spend_by_account"] = WidgetDef(
    key="spend_by_account",
    assembler=build_spend_by_account,
    template="intelligence/widgets/spend_by_account.html",
)
