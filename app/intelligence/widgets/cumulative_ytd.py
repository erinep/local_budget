"""Cumulative YTD spend widget.

Answers: "How does my spending this year compare to last year?"

Public API:
    build_cumulative_ytd(user_id) -> CumulativeYTDVM
"""

import datetime
from dataclasses import dataclass
from typing import Optional

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class CumulativeYTDVM:
    title: str
    labels: list[str]                    # ["Jan", "Feb", ..., current month]
    current_year: list[float]            # cumulative spend by month end, current year
    prior_year: list[Optional[float]]    # same for prior year; None if no data
    current_year_label: str              # e.g. "2026"
    prior_year_label: str                # e.g. "2025"
    has_prior_year: bool


def build_cumulative_ytd(user_id: str) -> CumulativeYTDVM:
    """Return cumulative year-to-date spend for current and prior year."""
    today = datetime.date.today()
    cur_year = today.year
    prior_year_num = cur_year - 1
    cur_month = today.month

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    labels = month_names[:cur_month]

    page_size = 200

    def _fetch_year(year: int, up_to_month: int) -> list[float]:
        """Return monthly spend totals for Jan..up_to_month of year."""
        date_from = datetime.date(year, 1, 1)
        import calendar
        days_in_last = calendar.monthrange(year, up_to_month)[1]
        date_to = datetime.date(year, up_to_month, days_in_last)
        txns = []
        offset = 0
        while True:
            page = get_transactions(user_id, TransactionFilters(
                limit=page_size, offset=offset, date_from=date_from, date_to=date_to,
            ))
            txns.extend(page.items)
            if len(txns) >= page.total_count:
                break
            offset += page_size
        monthly: dict[int, float] = {m: 0.0 for m in range(1, up_to_month + 1)}
        for t in txns:
            if float(t.amount) >= 0:
                continue
            if t.date.year == year:
                monthly[t.date.month] = monthly.get(t.date.month, 0.0) + abs(float(t.amount))
        return [round(monthly.get(m, 0.0), 2) for m in range(1, up_to_month + 1)]

    cur_monthly = _fetch_year(cur_year, cur_month)
    prior_monthly = _fetch_year(prior_year_num, cur_month)

    # Build cumulative sums
    cur_cumulative: list[float] = []
    running = 0.0
    for v in cur_monthly:
        running += v
        cur_cumulative.append(round(running, 2))

    prior_cumulative: list[Optional[float]] = []
    running = 0.0
    has_prior = any(v > 0 for v in prior_monthly)
    for v in prior_monthly:
        running += v
        prior_cumulative.append(round(running, 2) if has_prior else None)

    if not has_prior:
        prior_cumulative = [None] * cur_month

    return CumulativeYTDVM(
        title="Cumulative YTD Spend",
        labels=labels,
        current_year=cur_cumulative,
        prior_year=prior_cumulative,
        current_year_label=str(cur_year),
        prior_year_label=str(prior_year_num),
        has_prior_year=has_prior,
    )


REGISTRY["cumulative_ytd"] = WidgetDef(
    key="cumulative_ytd",
    assembler=build_cumulative_ytd,
    template="intelligence/widgets/cumulative_ytd.html",
)
