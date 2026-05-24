"""Intelligence Layer routes — dashboard.

Blueprint: intelligence_bp, url_prefix="/intelligence" (ADR-0004, ADR-0024).

Route table:
  GET /intelligence/dashboard          dashboard  Widget dashboard (Phase 5d, ADR-0039).
  GET /intelligence/widgets/<key>      widget     HTMX fragment endpoint for a single widget.
  GET /intelligence/report             →301       Permanent redirect to /intelligence/dashboard.
"""

from flask import Blueprint, abort, redirect, render_template, request, url_for, g

from app.intelligence.widgets import REGISTRY
import app.intelligence.widgets.monthly_totals   # noqa: F401 — registers widget
import app.intelligence.widgets.category_trends  # noqa: F401 — registers widget
from app.middleware.auth import login_required

intelligence_bp = Blueprint("intelligence", __name__, url_prefix="/intelligence")


def _monthly_totals_vm(user_id: str, period_months: int):
    from app.intelligence.widgets.monthly_totals import build_monthly_totals
    vm = build_monthly_totals(user_id, period_months)
    chart_data = {
        "labels": [p.label for p in vm.points],
        "values": [float(p.total) for p in vm.points],
    }
    return vm, chart_data


def _category_trends_vm(user_id: str, period_months: int):
    from app.intelligence.widgets.category_trends import build_category_trends
    vm = build_category_trends(user_id, period_months)
    chart_data = {
        "labels": vm.labels,
        "datasets": vm.datasets,
    }
    return vm, chart_data


@intelligence_bp.route("/dashboard", endpoint="dashboard")
@login_required
def dashboard():
    """Widget dashboard (Phase 5d, ADR-0039)."""
    period_months = min(max(request.args.get("months", 12, type=int), 1), 36)

    mt_vm, mt_chart = _monthly_totals_vm(g.user.id, period_months)
    ct_vm, ct_chart = _category_trends_vm(g.user.id, period_months)

    return render_template(
        "intelligence/dashboard.html",
        monthly_totals=mt_vm,
        monthly_totals_chart=mt_chart,
        category_trends=ct_vm,
        category_trends_chart=ct_chart,
    )


@intelligence_bp.route("/widgets/<key>", endpoint="widget")
@login_required
def widget(key: str):
    """HTMX fragment endpoint — returns a single widget's HTML (ADR-0039 §3)."""
    if key not in REGISTRY:
        abort(404)

    period_months = min(max(request.args.get("months", 12, type=int), 1), 36)

    if key == "monthly_totals":
        vm, chart_data = _monthly_totals_vm(g.user.id, period_months)
        return render_template(
            REGISTRY[key].template,
            monthly_totals=vm,
            monthly_totals_chart=chart_data,
        )

    if key == "category_trends":
        vm, chart_data = _category_trends_vm(g.user.id, period_months)
        return render_template(
            REGISTRY[key].template,
            category_trends=vm,
            category_trends_chart=chart_data,
        )

    abort(404)


@intelligence_bp.route("/report", endpoint="report")
def report_redirect():
    """Permanent redirect — /intelligence/report moved to /intelligence/dashboard."""
    return redirect(url_for("intelligence.dashboard"), 301)
