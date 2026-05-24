"""Monthly-totals line graph widget (ADR-0039 Follow-up #1).

Answers: "How much do I spend per month?"

Public API:
    build_monthly_totals(user_id, period_months) -> MonthlyTotalsVM
"""

import calendar
import datetime
from dataclasses import dataclass
from decimal import Decimal

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import DateRange, get_spend_by_category


@dataclass(frozen=True)
class MonthlyPoint:
    month: str    # "YYYY-MM"
    label: str    # "Jan 2026"
    total: Decimal


@dataclass(frozen=True)
class MonthlyTotalsVM:
    title: str
    points: list[MonthlyPoint]
    period_months: int


def build_monthly_totals(user_id: str, period_months: int = 12) -> MonthlyTotalsVM:
    """Return total spend per month for the last period_months complete months.

    Calls get_spend_by_category once per month and sums across categories.
    Only active-account, outflow (amount < 0) transactions are included,
    per the service-layer contract in get_spend_by_category.

    Args:
        user_id:       Authenticated user's UUID string.
        period_months: Number of complete calendar months to look back.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    year, month = now.year, now.month

    months: list[tuple[int, int]] = []
    for _ in range(period_months):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        months.append((year, month))
    months = list(reversed(months))

    points: list[MonthlyPoint] = []
    for y, m in months:
        period = DateRange.for_month(y, m)
        spend_rows = get_spend_by_category(user_id, period)
        total = sum((row.spend for row in spend_rows), Decimal("0"))
        points.append(MonthlyPoint(
            month=f"{y}-{m:02d}",
            label=datetime.date(y, m, 1).strftime("%b %Y"),
            total=total,
        ))

    return MonthlyTotalsVM(
        title="Monthly Spending",
        points=points,
        period_months=period_months,
    )


REGISTRY["monthly_totals"] = WidgetDef(
    key="monthly_totals",
    assembler=build_monthly_totals,
    template="intelligence/widgets/monthly_totals.html",
)
