"""Categorization health widget — donut chart showing % of transactions categorized.

Answers: "How accurate is my categorization engine?"

Public API:
    build_categorization_health(user_id) -> CategorizationHealthVM
"""

from dataclasses import dataclass

from app.account_settings.services import count_uncategorized_transactions
from app.intelligence.widgets import REGISTRY, WidgetDef
from app.transactions.services import TransactionFilters, get_transactions


@dataclass(frozen=True)
class CategorizationHealthVM:
    total: int
    categorized: int
    uncategorized: int
    pct_categorized: float   # 0.0 – 100.0, rounded to 1 dp


def build_categorization_health(user_id: str) -> CategorizationHealthVM:
    """Return categorized vs uncategorized transaction counts across all time."""
    total = get_transactions(user_id, TransactionFilters(limit=1)).total_count
    uncategorized = count_uncategorized_transactions(user_id)
    categorized = max(total - uncategorized, 0)
    pct = round(categorized / total * 100, 1) if total > 0 else 0.0
    return CategorizationHealthVM(
        total=total,
        categorized=categorized,
        uncategorized=uncategorized,
        pct_categorized=pct,
    )


REGISTRY["categorization_health"] = WidgetDef(
    key="categorization_health",
    assembler=build_categorization_health,
    template="intelligence/widgets/categorization_health.html",
)
