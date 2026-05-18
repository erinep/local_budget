"""Budgeting Module routes — Phase 4.

ADR-0025, Decision 9: Blueprint prefix /budgets.

Route table:
  GET  /budgets/                    budget_progress       Actual-vs-budget view
  GET  /budgets/configure           configure_budgets     List & form to add/edit
  POST /budgets/configure           save_budget           Create or update one budget
  POST /budgets/<uuid>/delete       delete_budget_route   Hard delete a budget row
  GET  /budgets/propose             propose_budget_preview  Preview proposed budgets
  POST /budgets/propose             apply_proposed_budgets_route  Write proposed budgets

All routes require authentication. All POST routes follow PRG (Post-Redirect-Get).
Period defaults to current UTC month; ?year=YYYY&month=MM overrides.

ADR-0003: this blueprint calls Budgeting service functions only; no direct DB access.
ADR-0004: registered in app factory.
"""

import logging
from datetime import timezone, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from app.middleware.auth import login_required
from app.account_settings.services import list_categories
from app.budgets.services import (
    apply_proposed_budgets,
    delete_budget,
    get_budget_progress,
    get_budgets,
    propose_budgets,
    upsert_budget,
)

logger = logging.getLogger(__name__)

budgets_bp = Blueprint("budgets", __name__, url_prefix="/budgets")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_year_month() -> tuple[int, int]:
    """Return (year, month) for the current UTC date."""
    now = datetime.now(tz=timezone.utc)
    return now.year, now.month


def _parse_period(request) -> tuple[int, int]:
    """Parse ?year=YYYY&month=MM query params, falling back to current UTC month.

    Calls abort(400) if the params are present but invalid.
    """
    default_year, default_month = _current_year_month()
    raw_year = request.args.get("year")
    raw_month = request.args.get("month")

    if raw_year is None and raw_month is None:
        return default_year, default_month

    try:
        year = int(raw_year) if raw_year else default_year
        month = int(raw_month) if raw_month else default_month
    except (ValueError, TypeError):
        abort(400)

    if not (2000 <= year <= 2100) or not (1 <= month <= 12):
        abort(400)

    return year, month


def _prev_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


# ---------------------------------------------------------------------------
# Budget progress view (default landing)
# ---------------------------------------------------------------------------

@budgets_bp.route("/", methods=["GET"])
@login_required
def budget_progress():
    """Actual-vs-budget view for the selected month (defaults to current UTC month)."""
    user_id = g.user.id
    year, month = _parse_period(request)

    progress = get_budget_progress(user_id, year, month)
    prev_year, prev_month = _prev_month(year, month)
    next_year, next_month = _next_month(year, month)

    return render_template(
        "budgets/progress.html",
        progress=progress,
        year=year,
        month=month,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
    )


# ---------------------------------------------------------------------------
# Configure: list + add/edit form
# ---------------------------------------------------------------------------

@budgets_bp.route("/configure", methods=["GET"])
@login_required
def configure_budgets():
    """List existing budgets for the selected month; show form to add/edit."""
    user_id = g.user.id
    year, month = _parse_period(request)

    budgets = get_budgets(user_id, year, month)
    categories = list_categories(user_id)

    return render_template(
        "budgets/configure.html",
        budgets=budgets,
        categories=categories,
        year=year,
        month=month,
    )


@budgets_bp.route("/configure", methods=["POST"])
@login_required
def save_budget():
    """Create or update a single budget entry (PRG)."""
    user_id = g.user.id

    raw_category_id = request.form.get("category_id", "").strip()
    raw_amount = request.form.get("amount", "").strip()
    raw_year = request.form.get("year", "").strip()
    raw_month = request.form.get("month", "").strip()

    try:
        category_id = UUID(raw_category_id)
    except (ValueError, AttributeError):
        abort(400)

    try:
        amount = Decimal(raw_amount)
    except InvalidOperation:
        flash("Invalid amount — please enter a number.", "error")
        return redirect(url_for("budgets.configure_budgets"))

    try:
        year = int(raw_year)
        month = int(raw_month)
    except (ValueError, TypeError):
        abort(400)

    try:
        upsert_budget(user_id, category_id, amount, year, month)
        flash("Budget saved.", "success")
    except ValueError as exc:
        flash(str(exc), "error")

    return redirect(url_for("budgets.configure_budgets", year=year, month=month))


# ---------------------------------------------------------------------------
# Delete a budget
# ---------------------------------------------------------------------------

@budgets_bp.route("/<uuid:budget_id>/delete", methods=["POST"])
@login_required
def delete_budget_route(budget_id: UUID):
    """Hard-delete a budget row (PRG)."""
    user_id = g.user.id

    # Capture the period from form data so we can redirect back to the right month
    raw_year = request.form.get("year", "").strip()
    raw_month = request.form.get("month", "").strip()
    try:
        year = int(raw_year)
        month = int(raw_month)
    except (ValueError, TypeError):
        year, month = _current_year_month()

    try:
        delete_budget(user_id, budget_id)
        flash("Budget deleted.", "success")
    except ValueError:
        abort(404)

    return redirect(url_for("budgets.configure_budgets", year=year, month=month))


# ---------------------------------------------------------------------------
# Propose budget preview + apply
# ---------------------------------------------------------------------------

@budgets_bp.route("/propose", methods=["GET"])
@login_required
def propose_budget_preview():
    """Preview proposed budgets based on spending history."""
    user_id = g.user.id
    year, month = _parse_period(request)

    proposals = propose_budgets(user_id, year, month)

    return render_template(
        "budgets/propose.html",
        proposals=proposals,
        year=year,
        month=month,
    )


@budgets_bp.route("/propose", methods=["POST"])
@login_required
def apply_proposed_budgets_route():
    """Write proposed budgets — gaps-only or replace-all (PRG)."""
    user_id = g.user.id

    raw_year = request.form.get("year", "").strip()
    raw_month = request.form.get("month", "").strip()
    replace_existing = request.form.get("replace_existing") == "true"

    try:
        year = int(raw_year)
        month = int(raw_month)
    except (ValueError, TypeError):
        abort(400)

    proposals = propose_budgets(user_id, year, month)

    try:
        written = apply_proposed_budgets(user_id, proposals, year, month, replace_existing)
        if written == 0:
            flash("No new budgets applied (all categories already have budgets for this month).", "info")
        else:
            flash(f"{written} budget(s) applied.", "success")
    except Exception as exc:
        logger.error("apply_proposed_budgets failed: %s", type(exc).__name__)
        flash("An error occurred while applying proposed budgets.", "error")

    return redirect(url_for("budgets.budget_progress", year=year, month=month))
