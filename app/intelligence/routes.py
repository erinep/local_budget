"""Intelligence Layer routes — dashboard.

Blueprint: intelligence_bp, url_prefix="/intelligence" (ADR-0004, ADR-0024).

Route table:
  GET /intelligence/dashboard          dashboard  Widget dashboard (Phase 5d, ADR-0039).
  GET /intelligence/widgets/<key>      widget     HTMX fragment endpoint for a single widget.
  GET /intelligence/report             →301       Permanent redirect to /intelligence/dashboard.
"""

from flask import Blueprint, abort, redirect, render_template, request, url_for, g

from app.intelligence.widgets import REGISTRY
import app.intelligence.widgets.category_trends       # noqa: F401
import app.intelligence.widgets.category_totals       # noqa: F401
import app.intelligence.widgets.category_profile      # noqa: F401
from app.middleware.auth import login_required

intelligence_bp = Blueprint("intelligence", __name__, url_prefix="/intelligence")

_ACCENT   = '#0f766e'
_ERROR    = '#dc2626'
_MUTED    = '#94a3b8'
_PALETTE  = ['#0f766e','#2563eb','#d97706','#7c3aed','#db2777','#059669','#ea580c','#0891b2']


def _category_trends_vm(user_id, period_months):
    from app.intelligence.widgets.category_trends import build_category_trends
    ct_vm = build_category_trends(user_id, period_months)
    n = len(ct_vm.labels)
    total = [sum(ds["data"][i] for ds in ct_vm.datasets) for i in range(n)]
    chart = {
        "labels": ct_vm.labels,
        "total": total,
        "datasets": ct_vm.datasets,
    }
    return ct_vm, chart


def _category_profile_vm(user_id, period_months):
    from app.intelligence.widgets.category_profile import build_category_profile
    vm = build_category_profile(user_id, period_months)
    return vm


def _category_totals_vm(user_id, period_months):
    from app.intelligence.widgets.category_totals import build_category_totals
    vm = build_category_totals(user_id, period_months)
    _TOTAL = '#475569'
    colors = [_ERROR if item.is_uncategorized else _TOTAL for item in vm.items]
    chart = {
        "labels": [item.label for item in vm.items],
        "values": [item.spend for item in vm.items],
        "colors": colors,
        "amounts": vm.category_amounts,
    }
    return vm, chart


@intelligence_bp.route("/dashboard", endpoint="dashboard")
@login_required
def dashboard():
    """Widget dashboard (Phase 5d, ADR-0039)."""
    period_months = min(max(request.args.get("months", 12, type=int), 1), 36)

    ct_vm,   ct_chart   = _category_trends_vm(g.user.id, period_months)
    ctot_vm, ctot_chart = _category_totals_vm(g.user.id, period_months)
    cp_vm               = _category_profile_vm(g.user.id, period_months)

    return render_template(
        "intelligence/dashboard.html",
        category_trends=ct_vm,   category_trends_chart=ct_chart,
        category_totals=ctot_vm, category_totals_chart=ctot_chart,
        category_profile=cp_vm,
    )


@intelligence_bp.route("/widgets/<key>", endpoint="widget")
@login_required
def widget(key: str):
    """HTMX fragment endpoint — returns a single widget's HTML (ADR-0039 §3)."""
    if key not in REGISTRY:
        abort(404)

    period_months = min(max(request.args.get("months", 12, type=int), 1), 36)

    if key == "category_trends":
        vm, chart = _category_trends_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_trends=vm, category_trends_chart=chart)

    if key == "category_totals":
        vm, chart = _category_totals_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_totals=vm, category_totals_chart=chart)

    if key == "category_profile":
        vm = _category_profile_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_profile=vm)

    abort(404)


@intelligence_bp.route("/report", endpoint="report")
def report_redirect():
    """Permanent redirect — /intelligence/report moved to /intelligence/dashboard."""
    return redirect(url_for("intelligence.dashboard"), 301)
