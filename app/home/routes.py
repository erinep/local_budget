"""Home (dashboard) blueprint routes.

ADR-0011 — Navigation and Landing Page Contract. The dashboard is the
post-login landing surface at ``/`` and a cross-module composition surface;
it owns no data and renders inert links to other modules' surfaces in
Phase 2. In later phases it gains counts (Phase 3), a Budget card
(Phase 4), and narrative summaries (Phase 5).

This blueprint is intentionally outside ADR-0004's enumerated module list
because the dashboard is a presentation surface, not an architectural
module. See ADR-0011 point 5 for the rationale.

All routes require an authenticated user (ADR-0006).
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from flask import Blueprint, g, render_template

from app.middleware.auth import login_required

home_bp = Blueprint("home", __name__)


@home_bp.route("/", methods=["GET"])
@login_required
def index():
    """Render the post-login dashboard with a current-month spending summary."""
    spending_data = _get_spending_summary(g.user.id)
    return render_template("home/index.html", **spending_data)


def _get_spending_summary(user_id: str) -> dict:
    """Return current-month spending totals for the dashboard card.

    Returns a dict with has_transactions, total_spend, breakdown (top 3).
    Degrades gracefully if the DB is unavailable.
    """
    try:
        from app.transactions.services import TransactionFilters, get_transactions

        today = date.today()
        month_start = date(today.year, today.month, 1)
        filters = TransactionFilters(
            date_from=month_start,
            date_to=today,
            limit=500,
        )
        page = get_transactions(user_id, filters)

        if not page.items:
            return {"has_transactions": False, "total_spend": Decimal("0"), "breakdown": []}

        by_category: dict[str, Decimal] = defaultdict(Decimal)
        total = Decimal("0")
        for txn in page.items:
            if txn.amount < 0:
                spend = abs(txn.amount)
                total += spend
                label = txn.category_name or "Uncategorized"
                by_category[label] += spend

        top3 = sorted(by_category.items(), key=lambda x: x[1], reverse=True)[:3]
        return {
            "has_transactions": True,
            "total_spend": total,
            "breakdown": [{"label": k, "amount": v} for k, v in top3],
        }
    except Exception:
        return {"has_transactions": False, "total_spend": Decimal("0"), "breakdown": []}
