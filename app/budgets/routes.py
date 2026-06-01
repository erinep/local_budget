"""Budgeting Module routes — Phase 4 + Phase 5e.

ADR-0025 (Decision 9) / ADR-0026: Blueprint prefix /budgets.
ADR-0043: income owned by Account Settings; read here via get_user_settings().
ADR-0044: dollar-only storage; percentage derived at display time.

Route table:
  GET  /budgets/                    budget_progress              Budget page — all categories, editable targets
  POST /budgets/income              save_income                  Save monthly income (PRG)
  POST /budgets/save                save_all_budgets             Batch-save all budget targets (PRG)
  GET  /budgets/propose             propose_budget_preview       Preview history-based proposals
  POST /budgets/propose             apply_proposed_budgets_route Write proposed targets

All routes require authentication. All POST routes follow PRG (Post-Redirect-Get).
Progress view defaults to current UTC month; ?year=YYYY&month=MM overrides.

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
from app.account_settings.services import (
    list_categories,
    get_user_settings,
    upsert_user_settings,
)
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
    now = datetime.now(tz=timezone.utc)
    return now.year, now.month


def _parse_period(req) -> tuple[int, int]:
    default_year, default_month = _current_year_month()
    raw_year = req.args.get("year")
    raw_month = req.args.get("month")

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


def _compute_allocation(budgets, monthly_income):
    """Return allocation summary dict, or None when income is not set."""
    if not monthly_income or monthly_income <= Decimal("0"):
        return None
    total = sum((b.amount for b in budgets), Decimal("0"))
    unallocated = monthly_income - total
    pct = total / monthly_income * Decimal("100")
    return {
        "total_allocated": total,
        "total_unallocated": unallocated,
        "pct_allocated": pct,
        "monthly_income": monthly_income,
    }


def _build_rows(categories: list, progress: list) -> list[dict]:
    """Merge all user categories with budget progress for the current month.

    Every category gets a row. Categories with no budget and no spend show
    target=0 and actual=0. Uncategorized spend is appended at the end.
    """
    progress_by_cat = {
        str(r.category_id): r
        for r in progress
        if r.category_id is not None
    }

    rows = []
    for cat in categories:
        prog = progress_by_cat.get(cat["id"])
        if prog:
            rows.append({
                "id": cat["id"],
                "name": cat["name"],
                "target": prog.target,
                "actual": prog.actual,
                "variance": prog.variance,
                "pct_used": prog.pct_used,
                "status": prog.status,
            })
        else:
            rows.append({
                "id": cat["id"],
                "name": cat["name"],
                "target": Decimal("0"),
                "actual": Decimal("0"),
                "variance": Decimal("0"),
                "pct_used": Decimal("0"),
                "status": None,
            })

    for r in progress:
        if r.category_id is None and r.actual > Decimal("0"):
            rows.append({
                "id": None,
                "name": None,
                "target": Decimal("0"),
                "actual": r.actual,
                "variance": Decimal("0") - r.actual,
                "pct_used": Decimal("0"),
                "status": r.status,
            })

    return rows


# ---------------------------------------------------------------------------
# Income
# ---------------------------------------------------------------------------

@budgets_bp.route("/income", methods=["POST"])
@login_required
def save_income():
    """Save or clear the user's monthly income (PRG → budget progress)."""
    user_id = g.user.id
    raw = request.form.get("monthly_income", "").strip()

    if raw == "":
        try:
            upsert_user_settings(user_id, None)
            flash("Income cleared.", "success")
        except Exception:
            flash("An error occurred.", "error")
        return redirect(url_for("budgets.budget_progress"))

    try:
        income = Decimal(raw)
    except InvalidOperation:
        flash("Invalid income — please enter a number.", "error")
        return redirect(url_for("budgets.budget_progress"))

    try:
        upsert_user_settings(user_id, income)
        flash("Income saved.", "success")
    except ValueError as exc:
        flash(str(exc), "error")

    return redirect(url_for("budgets.budget_progress"))


# ---------------------------------------------------------------------------
# Budget page
# ---------------------------------------------------------------------------

@budgets_bp.route("/", methods=["GET"])
@login_required
def budget_progress():
    """Budget page — editable targets for all categories, actual spend for the month."""
    user_id = g.user.id
    year, month = _parse_period(request)

    categories = list_categories(user_id)
    progress = get_budget_progress(user_id, year, month)
    rows = _build_rows(categories, progress)

    prev_year, prev_month = _prev_month(year, month)
    next_year, next_month = _next_month(year, month)

    user_settings = get_user_settings(user_id)
    monthly_income = user_settings.monthly_income
    allocation = _compute_allocation(get_budgets(user_id), monthly_income)

    return render_template(
        "budgets/progress.html",
        rows=rows,
        year=year,
        month=month,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        monthly_income=monthly_income,
        allocation=allocation,
    )


# ---------------------------------------------------------------------------
# Batch save all budget targets
# ---------------------------------------------------------------------------

@budgets_bp.route("/save", methods=["POST"])
@login_required
def save_all_budgets():
    """Batch-save all budget targets from the budget page form (PRG).

    Form fields named amount_<category_uuid> are parsed.
    A value of 0 or empty removes the budget for that category if one exists.
    """
    user_id = g.user.id
    existing = {b.category_id: b for b in get_budgets(user_id)}
    errors = 0

    for key, value in request.form.items():
        if not key.startswith("amount_"):
            continue
        try:
            cat_id = UUID(key[len("amount_"):])
        except ValueError:
            continue

        raw = value.strip()
        try:
            amount = Decimal(raw) if raw else Decimal("0")
        except InvalidOperation:
            errors += 1
            continue

        if amount <= Decimal("0"):
            if cat_id in existing:
                try:
                    delete_budget(user_id, existing[cat_id].id)
                except ValueError:
                    pass
        else:
            try:
                upsert_budget(user_id, cat_id, amount)
            except ValueError:
                errors += 1

    if errors:
        flash(f"Budgets saved with {errors} invalid value(s) skipped.", "warning")
    else:
        flash("Budgets saved.", "success")

    return redirect(url_for("budgets.budget_progress"))


# ---------------------------------------------------------------------------
# Propose budget (history-based)
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
    """Write history-based proposed targets — gaps-only or replace-all (PRG)."""
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
        written = apply_proposed_budgets(user_id, proposals, replace_existing)
        if written == 0:
            flash("No new budgets applied (all categories already have standing targets).", "info")
        else:
            flash(f"{written} budget target(s) set.", "success")
    except Exception as exc:
        logger.error("apply_proposed_budgets failed: %s", type(exc).__name__)
        flash("An error occurred while applying proposed budgets.", "error")

    return redirect(url_for("budgets.budget_progress", year=year, month=month))
