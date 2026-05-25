"""Financial health score widget.

Answers: "How healthy are my finances overall?"

Public API:
    build_financial_health_score(user_id, period_months) -> FinancialHealthScoreVM
"""

import datetime
import statistics
from dataclasses import dataclass

from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions
from app.budgets.services import BudgetStatus, get_budget_progress


@dataclass(frozen=True)
class HealthComponent:
    name: str
    score: float       # 0-20
    max_score: float   # 20
    label: str         # brief description of what drives this score


@dataclass(frozen=True)
class FinancialHealthScoreVM:
    title: str
    total_score: float           # 0-100
    grade: str                   # A (90+), B (75-89), C (60-74), D (45-59), F (<45)
    components: list[HealthComponent]
    period_months: int


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 45:
        return "D"
    return "F"


def build_financial_health_score(user_id: str, period_months: int = 6) -> FinancialHealthScoreVM:
    """Compute a 0-100 financial health score from 5 components."""
    now = datetime.datetime.now(datetime.timezone.utc)
    year, month = now.year, now.month

    months: list[tuple[int, int]] = []
    for _ in range(6):
        m_year, m_month = year, month
        m_month -= 1
        if m_month == 0:
            m_month = 12
            m_year -= 1
        year, month = m_year, m_month
        months.append((year, month))

    # Reset year/month for latest
    now = datetime.datetime.now(datetime.timezone.utc)
    year, month = now.year, now.month
    months = []
    for _ in range(6):
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

    outflows = [t for t in all_txns if float(t.amount) < 0]
    total_txn_count = len(all_txns)

    # --- Component 1: Categorization rate ---
    # Use latest complete month
    latest_month_txns = [
        t for t in all_txns
        if t.date.year == latest_y and t.date.month == latest_m
    ]
    if latest_month_txns:
        categorized = sum(1 for t in latest_month_txns if t.category_name and t.category_name != "Uncategorized")
        pct_categorized = categorized / len(latest_month_txns) * 100.0
    else:
        pct_categorized = 0.0
    cat_score = round(pct_categorized / 100.0 * 20.0, 2)
    cat_label = f"{pct_categorized:.0f}% of transactions categorized"

    # --- Component 2: Budget adherence ---
    latest_progress = get_budget_progress(user_id, latest_y, latest_m)
    budgeted = [p for p in latest_progress if p.budget is not None]
    if budgeted:
        under_count = sum(1 for p in budgeted if p.status == BudgetStatus.UNDER)
        adherence_pct = under_count / len(budgeted) * 100.0
        budget_score = round(adherence_pct / 100.0 * 20.0, 2)
        budget_label = f"{under_count}/{len(budgeted)} budgeted categories under budget"
    else:
        budget_score = 10.0
        budget_label = "No budgets set (neutral score)"

    # --- Component 3: Outlier frequency ---
    # Simple outlier detection: z-score > 2.5 per category
    cat_amounts: dict[str, list[float]] = {}
    for t in outflows:
        cat = t.category_name or "Uncategorized"
        cat_amounts.setdefault(cat, []).append(abs(float(t.amount)))

    outlier_count = 0
    for cat, amounts in cat_amounts.items():
        if len(amounts) < 3:
            continue
        mean = statistics.mean(amounts)
        stdev = statistics.stdev(amounts)
        if stdev == 0:
            continue
        for amt in amounts:
            if abs(amt - mean) / stdev > 2.5:
                outlier_count += 1

    if total_txn_count == 0:
        outlier_pct = 0.0
    else:
        outlier_pct = outlier_count / total_txn_count * 100.0

    if outlier_pct < 2.0:
        outlier_score = 20.0
    elif outlier_pct > 20.0:
        outlier_score = 0.0
    else:
        outlier_score = round(20.0 * (1.0 - (outlier_pct - 2.0) / 18.0), 2)
    outlier_label = f"{outlier_count} unusual transactions detected"

    # --- Component 4: Subscription load ---
    # Simplified: count descriptions that appear in 3+ distinct months
    desc_months: dict[str, set] = {}
    desc_total: dict[str, float] = {}
    for t in outflows:
        desc = t.description
        key = (t.date.year, t.date.month)
        desc_months.setdefault(desc, set()).add(key)
        desc_total[desc] = desc_total.get(desc, 0.0) + abs(float(t.amount))

    total_outflow = sum(abs(float(t.amount)) for t in outflows)
    sub_total = sum(
        desc_total[d] for d, m_set in desc_months.items() if len(m_set) >= 3
    )
    if total_outflow > 0:
        sub_pct = sub_total / total_outflow * 100.0
    else:
        sub_pct = 0.0

    if sub_pct < 10.0:
        sub_score = 20.0
    elif sub_pct > 40.0:
        sub_score = 0.0
    else:
        sub_score = round(20.0 * (1.0 - (sub_pct - 10.0) / 30.0), 2)
    sub_label = f"Subscriptions ~{sub_pct:.0f}% of total spend"

    # --- Component 5: Spending trend ---
    recent_set = set(months[:3])
    prior_set = set(months[3:])
    recent_total = sum(
        abs(float(t.amount))
        for t in outflows
        if (t.date.year, t.date.month) in recent_set
    )
    prior_total = sum(
        abs(float(t.amount))
        for t in outflows
        if (t.date.year, t.date.month) in prior_set
    )
    recent_avg = recent_total / 3.0
    prior_avg = prior_total / 3.0

    if prior_avg == 0:
        trend_score = 10.0
        trend_label = "No prior data for trend"
    elif recent_avg <= prior_avg:
        trend_score = 20.0
        trend_label = "Spending is flat or decreasing"
    else:
        increase_pct = (recent_avg - prior_avg) / prior_avg * 100.0
        if increase_pct >= 100.0:
            trend_score = 0.0
        else:
            trend_score = round(10.0 * (1.0 - increase_pct / 100.0), 2)
        trend_label = f"Spending up {increase_pct:.0f}% vs prior period"

    components = [
        HealthComponent(name="Categorization", score=cat_score, max_score=20.0, label=cat_label),
        HealthComponent(name="Budget Adherence", score=budget_score, max_score=20.0, label=budget_label),
        HealthComponent(name="Transaction Regularity", score=outlier_score, max_score=20.0, label=outlier_label),
        HealthComponent(name="Subscription Load", score=sub_score, max_score=20.0, label=sub_label),
        HealthComponent(name="Spending Trend", score=trend_score, max_score=20.0, label=trend_label),
    ]
    total_score = round(sum(c.score for c in components), 1)

    return FinancialHealthScoreVM(
        title="Financial Health Score",
        total_score=total_score,
        grade=_grade(total_score),
        components=components,
        period_months=period_months,
    )


REGISTRY["financial_health_score"] = WidgetDef(
    key="financial_health_score",
    assembler=build_financial_health_score,
    template="intelligence/widgets/financial_health_score.html",
)
