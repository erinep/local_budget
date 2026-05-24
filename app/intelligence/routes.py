"""Intelligence Layer routes — dashboard.

Blueprint: intelligence_bp, url_prefix="/intelligence" (ADR-0004, ADR-0024).

Route table:
  GET /intelligence/dashboard          dashboard  Widget dashboard (Phase 5d, ADR-0039).
  GET /intelligence/widgets/<key>      widget     HTMX fragment endpoint for a single widget.
  GET /intelligence/report             →301       Permanent redirect to /intelligence/dashboard.
"""

from flask import Blueprint, abort, redirect, render_template, request, url_for, g

from app.intelligence.widgets import REGISTRY
import app.intelligence.widgets.monthly_totals        # noqa: F401
import app.intelligence.widgets.category_trends       # noqa: F401
import app.intelligence.widgets.categorization_health # noqa: F401
import app.intelligence.widgets.category_totals       # noqa: F401
from app.middleware.auth import login_required

intelligence_bp = Blueprint("intelligence", __name__, url_prefix="/intelligence")

_ACCENT   = '#0f766e'
_ERROR    = '#dc2626'
_MUTED    = '#94a3b8'


def _monthly_totals_vm(user_id, period_months):
    from app.intelligence.widgets.monthly_totals import build_monthly_totals
    vm = build_monthly_totals(user_id, period_months)
    return vm, {"labels": [p.label for p in vm.points], "values": [float(p.total) for p in vm.points]}


def _category_trends_vm(user_id, period_months):
    from app.intelligence.widgets.category_trends import build_category_trends
    vm = build_category_trends(user_id, period_months)
    return vm, {"labels": vm.labels, "datasets": vm.datasets}


def _categorization_health_vm(user_id):
    from app.intelligence.widgets.categorization_health import build_categorization_health
    vm = build_categorization_health(user_id)
    chart = {
        "labels": ["Categorized", "Uncategorized"],
        "values": [vm.categorized, vm.uncategorized],
        "colors": [_ACCENT, _ERROR],
    }
    return vm, chart


def _category_totals_vm(user_id, period_months):
    from app.intelligence.widgets.category_totals import build_category_totals
    vm = build_category_totals(user_id, period_months)
    chart = {
        "labels": [item.label for item in vm.items],
        "values": [item.spend for item in vm.items],
        "colors": [_ERROR if item.is_uncategorized else _ACCENT for item in vm.items],
    }
    return vm, chart


@intelligence_bp.route("/dashboard", endpoint="dashboard")
@login_required
def dashboard():
    """Widget dashboard (Phase 5d, ADR-0039)."""
    period_months = min(max(request.args.get("months", 12, type=int), 1), 36)

    mt_vm,  mt_chart  = _monthly_totals_vm(g.user.id, period_months)
    ct_vm,  ct_chart  = _category_trends_vm(g.user.id, period_months)
    ch_vm,  ch_chart  = _categorization_health_vm(g.user.id)
    ctot_vm, ctot_chart = _category_totals_vm(g.user.id, period_months)

    return render_template(
        "intelligence/dashboard.html",
        monthly_totals=mt_vm,         monthly_totals_chart=mt_chart,
        category_trends=ct_vm,        category_trends_chart=ct_chart,
        categorization_health=ch_vm,  categorization_health_chart=ch_chart,
        category_totals=ctot_vm,      category_totals_chart=ctot_chart,
    )


@intelligence_bp.route("/widgets/<key>", endpoint="widget")
@login_required
def widget(key: str):
    """HTMX fragment endpoint — returns a single widget's HTML (ADR-0039 §3)."""
    if key not in REGISTRY:
        abort(404)

    period_months = min(max(request.args.get("months", 12, type=int), 1), 36)

    if key == "monthly_totals":
        vm, chart = _monthly_totals_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, monthly_totals=vm, monthly_totals_chart=chart)

    if key == "category_trends":
        vm, chart = _category_trends_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_trends=vm, category_trends_chart=chart)

    if key == "categorization_health":
        vm, chart = _categorization_health_vm(g.user.id)
        return render_template(REGISTRY[key].template, categorization_health=vm, categorization_health_chart=chart)

    if key == "category_totals":
        vm, chart = _category_totals_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_totals=vm, category_totals_chart=chart)

    abort(404)


@intelligence_bp.route("/report", endpoint="report")
def report_redirect():
    """Permanent redirect — /intelligence/report moved to /intelligence/dashboard."""
    return redirect(url_for("intelligence.dashboard"), 301)
