"""Intelligence Layer routes — dashboard.

Blueprint: intelligence_bp, url_prefix="/intelligence" (ADR-0004, ADR-0024).

Route table:
  GET /intelligence/dashboard          dashboard  Widget dashboard (Phase 5d, ADR-0039).
  GET /intelligence/widgets/<key>      widget     HTMX fragment endpoint for a single widget.
  GET /intelligence/report             →301       Permanent redirect to /intelligence/dashboard.
"""

from flask import Blueprint, abort, redirect, render_template, request, url_for, g

from app.intelligence.widgets import REGISTRY
import app.intelligence.widgets.category_trends         # noqa: F401
import app.intelligence.widgets.category_trends_stacked # noqa: F401
import app.intelligence.widgets.category_profile        # noqa: F401
import app.intelligence.widgets.category_radar          # noqa: F401
import app.intelligence.widgets.category_movers         # noqa: F401
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


def _category_radar_vm(user_id, period_months):
    from app.intelligence.widgets.category_radar import build_category_radar
    vm = build_category_radar(user_id, period_months)
    chart = {
        "labels": vm.labels,
        "months": [
            {"label": m.label, "data": m.data, "is_current": m.is_current}
            for m in vm.months
        ],
    }
    return vm, chart


def _category_movers_vm(user_id, period_months):
    from app.intelligence.widgets.category_movers import build_category_movers
    return build_category_movers(user_id, period_months)


def _category_profile_vm(user_id, period_months):
    from app.intelligence.widgets.category_profile import build_category_profile
    vm = build_category_profile(user_id, period_months)
    row_charts = [
        [{"id": t.transaction_id, "label": t.description, "amount": t.amount}
         for t in row.top_transactions]
        for row in vm.rows
    ]
    return vm, row_charts


@intelligence_bp.route("/dashboard", endpoint="dashboard")
@login_required
def dashboard():
    """Widget dashboard (Phase 5d, ADR-0039)."""
    period_months = min(max(request.args.get("months", 12, type=int), 0), 36)

    ct_vm,   ct_chart   = _category_trends_vm(g.user.id, period_months)
    cp_vm,   cp_charts  = _category_profile_vm(g.user.id, period_months)
    cr_vm,   cr_chart   = _category_radar_vm(g.user.id, period_months)
    cm_vm               = _category_movers_vm(g.user.id, period_months)
    return render_template(
        "intelligence/dashboard.html",
        category_trends=ct_vm,         category_trends_chart=ct_chart,
        category_profile=cp_vm,        category_profile_charts=cp_charts,
        category_radar=cr_vm,          category_radar_chart=cr_chart,
        category_movers=cm_vm,
        period_months=period_months,
    )


@intelligence_bp.route("/widgets/<key>", endpoint="widget")
@login_required
def widget(key: str):
    """HTMX fragment endpoint — returns a single widget's HTML (ADR-0039 §3)."""
    if key not in REGISTRY:
        abort(404)

    period_months = min(max(request.args.get("months", 12, type=int), 0), 36)

    if key in ("category_trends", "category_trends_stacked"):
        vm, chart = _category_trends_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_trends=vm, category_trends_chart=chart)

    if key == "category_profile":
        vm, cp_charts = _category_profile_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_profile=vm, category_profile_charts=cp_charts)

    if key == "category_radar":
        vm, chart = _category_radar_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_radar=vm, category_radar_chart=chart)

    if key == "category_movers":
        vm = _category_movers_vm(g.user.id, period_months)
        return render_template(REGISTRY[key].template, category_movers=vm)

    abort(404)


@intelligence_bp.route("/report", endpoint="report")
def report_redirect():
    """Permanent redirect — /intelligence/report moved to /intelligence/dashboard."""
    return redirect(url_for("intelligence.dashboard"), 301)
