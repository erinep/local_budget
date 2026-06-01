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
    get_budgets,
    propose_budgets,
    upsert_budget,
)
from app.transactions.services import DateRange, get_spend_by_category

logger = logging.getLogger(__name__)

budgets_bp = Blueprint("budgets", __name__, url_prefix="/budgets")

_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_period(req) -> tuple[int, int]:
    now = datetime.now(tz=timezone.utc)
    default_year, default_month = now.year, now.month
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


def _status_color(target: Decimal, actual: Decimal) -> str:
    """Server-side mirror of the JS statusColor() function."""
    if target <= Decimal("0"):
        return "#b91c1c" if actual > Decimal("0") else "rgba(88,65,38,0.15)"
    ratio = actual / target
    if ratio > Decimal("1.0"):
        return "#b91c1c"
    if ratio >= Decimal("0.8"):
        return "#d97706"
    return "#3b82f6"


def _four_month_periods() -> list[tuple[int, int, bool]]:
    """Return (year, month, is_current) for the current month and 3 prior."""
    now = datetime.now(tz=timezone.utc)
    y, m = now.year, now.month
    periods = []
    for i in range(4):
        periods.append((y, m, i == 0))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return periods


def _build_multi_month_rows(
    user_id: str,
    categories: list,
    budgets: list,
    monthly_income,
) -> list[dict]:
    """Build table rows, each with 4 months of actual spend.

    Fetches spend for the current month and the 3 prior complete months.
    Returns one row per user category (no uncategorized rows).
    """
    slider_max = int(monthly_income) if monthly_income else 5000
    budget_by_cat: dict[UUID, object] = {b.category_id: b for b in budgets}
    periods = _four_month_periods()

    # Fetch spend for each of the 4 months
    monthly_spends = []
    for (py, pm, is_current) in periods:
        period = DateRange.for_month(py, pm)
        spend_rows = get_spend_by_category(user_id, period)
        spend_by_cat: dict[UUID, Decimal] = {
            s.category_id: s.spend
            for s in spend_rows
            if s.category_id is not None
        }
        monthly_spends.append({
            "label": _MONTH_NAMES[pm - 1],
            "is_current": is_current,
            "spend": spend_by_cat,
        })

    rows = []
    for cat in categories:
        cat_id = UUID(cat["id"])
        budget = budget_by_cat.get(cat_id)
        target = budget.amount if budget else Decimal("0")

        monthly_actuals = []
        for ms in monthly_spends:
            actual = ms["spend"].get(cat_id, Decimal("0"))
            actual_fill = min(float(actual) / slider_max * 100, 100) if slider_max else 0
            actual_pct = (
                round(float(actual / monthly_income * 100))
                if monthly_income and actual > Decimal("0")
                else 0
            )
            monthly_actuals.append({
                "label": ms["label"],
                "is_current": ms["is_current"],
                "actual": actual,
                "actual_fill": actual_fill,
                "actual_pct_label": actual_pct,
                "s_color": _status_color(target, actual),
            })

        rows.append({
            "id": cat["id"],
            "name": cat["name"],
            "target": target,
            "monthly_actuals": monthly_actuals,
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
    """Budget page — editable targets and 4 months of actual spend per category."""
    user_id = g.user.id

    categories = list_categories(user_id)
    budgets = get_budgets(user_id)
    user_settings = get_user_settings(user_id)
    monthly_income = user_settings.monthly_income
    allocation = _compute_allocation(budgets, monthly_income)
    rows = _build_multi_month_rows(user_id, categories, budgets, monthly_income)

    return render_template(
        "budgets/progress.html",
        rows=rows,
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

    return redirect(url_for("budgets.budget_progress"))
