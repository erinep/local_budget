"""Intelligence Layer routes — report and dashboard.

Blueprint: intelligence_bp, url_prefix="/intelligence" (ADR-0004, ADR-0024).

Route table:
  GET /intelligence/report             report     Legacy report (retained until dashboard replaces it).
  GET /intelligence/dashboard          dashboard  New widget dashboard (Phase 5d, ADR-0039).
  GET /intelligence/widgets/<key>      widget     HTMX fragment endpoint for a single widget.
"""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.account_settings.services import count_uncategorized_transactions
from app.intelligence.services import build_report_view_model
from app.intelligence.widgets import REGISTRY
import app.intelligence.widgets.monthly_totals  # noqa: F401 — registers widget
from app.middleware.auth import login_required

intelligence_bp = Blueprint("intelligence", __name__, url_prefix="/intelligence")


@intelligence_bp.route("/report", endpoint="report")
@login_required
def report():
    """Legacy report page. Retained until the new dashboard covers its scope."""
    view_model = build_report_view_model(g.user.id)

    if view_model is None:
        flash("Upload a file to see your report.", "info")
        return redirect(url_for("transactions.upload"))

    uncategorized_count = count_uncategorized_transactions(g.user.id)
    return render_template("intelligence/report.html", uncategorized_count=uncategorized_count, **view_model)


@intelligence_bp.route("/dashboard", endpoint="dashboard")
@login_required
def dashboard():
    """New widget dashboard (Phase 5d, ADR-0039).

    Assembles all registered widgets for a full-page render. Each widget
    assembler is called with the period parsed from query params.
    """
    period_months = min(max(request.args.get("months", 12, type=int), 1), 36)
    from app.intelligence.widgets.monthly_totals import build_monthly_totals
    vm = build_monthly_totals(g.user.id, period_months)
    chart_data = {
        "labels": [p.label for p in vm.points],
        "values": [float(p.total) for p in vm.points],
    }
    return render_template(
        "intelligence/dashboard.html",
        monthly_totals=vm,
        monthly_totals_chart=chart_data,
    )


@intelligence_bp.route("/widgets/<key>", endpoint="widget")
@login_required
def widget(key: str):
    """HTMX fragment endpoint — returns a single widget's HTML.

    Widget configuration is parsed from query parameters and forwarded to
    the assembler as typed arguments (ADR-0039 §3).
    """
    if key not in REGISTRY:
        abort(404)

    if key == "monthly_totals":
        from app.intelligence.widgets.monthly_totals import build_monthly_totals
        period_months = min(max(request.args.get("months", 12, type=int), 1), 36)
        vm = build_monthly_totals(g.user.id, period_months)
        chart_data = {
            "labels": [p.label for p in vm.points],
            "values": [float(p.total) for p in vm.points],
        }
        return render_template(
            REGISTRY[key].template,
            monthly_totals=vm,
            monthly_totals_chart=chart_data,
        )

    abort(404)
