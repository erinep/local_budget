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
        from app.transactions.services import DateRange, get_spend_by_category

        today = date.today()
        period = DateRange(date_from=date(today.year, today.month, 1), date_to=today)
        rows = get_spend_by_category(user_id, period)
        if not rows:
            return {"has_transactions": False, "total_spend": Decimal("0"), "breakdown": []}
        total = sum(r.spend for r in rows)
        breakdown = [
            {"label": r.category_name or "Uncategorized", "amount": r.spend}
            for r in rows[:3]
        ]
        return {"has_transactions": True, "total_spend": total, "breakdown": breakdown}
    except Exception:
        return {"has_transactions": False, "total_spend": Decimal("0"), "breakdown": []}
